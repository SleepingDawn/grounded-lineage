"""Citation keys in report Markdown: render them in house style and trace them back to records.

  scholarly-access-agent report trace <report.md> [--evidence DIR] [--json]

A report cites an evidence record by its file stem: `[@larkin2014]`, `[@larkin2014, p.9]`,
`[@larkin2014, §IV.A]`, a stored result `[@larkin2014#k300]`, several at once
`[@a, p.3; @b]`. `render-report` replaces each with "(Larkin 외, 2014 [5], p.9)" (reference
number = order of first citation) and a `<!-- references -->` line with a numbered table.
`trace` checks every cited sentence: unknown keys or result ids (error), locators the record
does not have (warning), numbers that appear in none of the cited records (warning) and
uncited numbers in the summary section (warning). Code spans and fenced blocks are left alone.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

from scholarly_access_agent import evidence as ev

REFERENCES_MARKER = "<!-- references -->"
_KEY = r"[^\s,;#\[\]@?()]+"
CITATION = re.compile(r"(?<![!\\])\[(@" + _KEY + r"[^\[\]]*)\](?!\()")
ITEM = re.compile(r"^\s*@(?P<key>" + _KEY + r")(?:#(?P<rid>[^\s,;\]]+))?\s*(?:,\s*(?P<loc>[^;]*?))?\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")
CODE_SPAN = re.compile(r"(`+)(?!`).*?(?<!`)\1(?!`)")
HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
SUMMARY_HEADING = re.compile(r"요약|한눈에|summary", re.I)
TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")
HANGUL = re.compile(r"[가-힣]")
ABBREVIATIONS = ("al.", "e.g.", "i.e.", "fig.", "figs.", "eq.", "eqs.", "ref.", "refs.", "vs.", "cf.",
                 "approx.", "ca.", "no.", "vol.", "sec.", "p.", "pp.", "ch.", "et.")

# Numbers are parsed by number_tokens() below (sign, decimals, thousands, powers of ten).
NOT_A_VALUE = re.compile(
    r"(?:\b(?:Fig(?:ure)?s?|Tables?|Eqs?|Equations?|Sec(?:tion)?s?|Refs?|Chapter|Ch|No|Vol|pp?)\.?|"
    r"그림|표|식|§)\s*\d+(?:\.\d+)*[A-Za-z]?(?:\s*[-–]\s*\d+)?", re.I)
# A version number written after a name with two or more capitals ("SPICE 2", "ANI 2"), not followed
# by a unit, a decimal part, thousands or more digits: part of the name, not a value.
NAME_VERSION = re.compile(r"\b([A-Z][A-Za-z\-]*[A-Z][A-Za-z\-]*)\s+\d{1,2}(?!\d|[.,]\d|\s*[A-Za-zµμÅ°%‰])")
URL = re.compile(r"(?:https?://|doi:|www\.)\S+", re.I)
LINK_TARGET = re.compile(r"(!?\[[^\]]*\])\([^)]*\)")
HTML_TAG = re.compile(r"<[^>]+>")


# ---------------------------------------------------------------- records

def find_topic(markdown_path: str | Path) -> Path | None:
    """The report's folder, or its parent (ideas/README.md), when it holds evidence/."""
    folder = Path(markdown_path).expanduser().resolve().parent
    return next((f for f in (folder, folder.parent) if (f / "evidence").is_dir()), None)


def load_records(evidence_dir: Path | None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for file in sorted(evidence_dir.glob("*.json")) if evidence_dir and evidence_dir.is_dir() else []:
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            out[file.stem] = data
    return out


def results(record: dict) -> list[dict]:
    return [r for r in (record.get("results") or []) if isinstance(r, dict)]


def _result(record: dict, rid: str | None) -> dict | None:
    return next((r for r in results(record) if str(r.get("id")) == rid), None) if rid else None


# ---------------------------------------------------------------- authors

def _family(name: Any) -> str:
    if isinstance(name, dict):
        return str(name.get("family") or name.get("last") or name.get("name") or "").strip()
    text = re.sub(r"\([^)]*\)?", "", str(name or "")).strip()  # 이도경 (Lee, Dokyung) -> 이도경
    if not text:
        return ""
    if HANGUL.search(text):
        return text
    if "," in text:
        return text.split(",")[0].strip()
    return text.split()[-1]


def author_names(record: dict) -> tuple[list[str], bool]:
    """(family names, "et al." given) from `authors`: "A; B", a list of strings or {family} objects."""
    authors = record.get("authors")
    et_al = bool(re.search(r"\bet\.?\s*al\b", str(authors or "")))
    if isinstance(authors, list):
        parts = authors
    elif isinstance(authors, str):
        text = re.sub(r"\([^)]*\)?", "", authors)
        if ";" in text:
            parts = text.split(";")
        elif re.search(r"\s(?:and|&)\s", text):
            parts = re.split(r",\s*|\s+(?:and|&)\s+", text)
        elif text.count(",") == 1 and len(text.split(",")[0].split()) == 1:
            parts = [text]  # "Family, Given"
        else:
            parts = text.split(",")
    else:
        parts = []
    names = [_family(p) for p in parts
             if not (isinstance(p, str) and re.fullmatch(r"\s*(?:et\.?\s*al\.?)?\s*", p))]
    names = [re.sub(r"\s*\bet\.?\s*al\.?$", "", n).strip() for n in names]
    return [n for n in names if n], et_al


def short_authors(record: dict, key: str) -> str:
    """"Larkin 외", "Kim & Cheng", "Larkin"; the key's letters when the record has no authors."""
    names, et_al = author_names(record)
    if not names:
        stem = re.match(r"[^\d_-]+", key)
        return (stem.group(0) if stem else key).capitalize()
    if len(names) == 2 and not et_al:
        return f"{names[0]} & {names[1]}"
    return names[0] + (" 외" if len(names) > 1 or et_al else "")


def year_of(record: dict, key: str) -> str:
    year = record.get("year")
    if year:
        return str(year)
    match = re.search(r"(19|20)\d{2}", key)
    return match.group(0) if match else "n.d."


def doi_of(record: dict) -> str | None:
    for field in ("journal_version", "paper_id", "doi"):
        value = record.get(field)
        if isinstance(value, str):
            match = ev.DOI_RE.search(value)
            if match:
                return match.group(0).rstrip(".,;)")
    return None


# ---------------------------------------------------------------- parsing

def _masked(line: str) -> str:
    """The line with code spans blanked out (same length, so offsets still match)."""
    return CODE_SPAN.sub(lambda m: "\x00" * len(m.group(0)), line)


def parse_citation(inner: str) -> list[dict[str, str | None]] | None:
    """`@a#r, p.3; @b` -> [{"key", "rid", "loc"}, ...]; None when it is not a citation."""
    items = []
    for part in inner.split(";"):
        match = ITEM.match(part)
        if not match:
            return None
        items.append({"key": match.group("key"), "rid": match.group("rid"),
                      "loc": (match.group("loc") or "").strip() or None})
    return items


def citations_in(line: str) -> list[tuple[int, int, list[dict]]]:
    out = []
    for match in CITATION.finditer(_masked(line)):
        items = parse_citation(line[match.start(1):match.end(1)])
        if items:
            out.append((match.start(), match.end(), items))
    return out


def _lines(text: str) -> Iterable[tuple[int, str, str]]:
    """(line number, line with its ending, kind) with kind "code", "comment" or "text"."""
    fence = None
    comment = False
    for number, line in enumerate(text.splitlines(keepends=True), start=1):
        match = FENCE.match(line)
        if fence:
            if match and match.group(1) == fence:
                fence = None
            yield number, line, "code"
            continue
        if match:
            fence = match.group(1)
            yield number, line, "code"
            continue
        if comment or line.lstrip().startswith("<!--"):
            comment = "-->" not in line
            yield number, line, "comment"
            continue
        yield number, line, "text"


# ---------------------------------------------------------------- rendering

def result_locator(result: dict) -> str:
    page = result.get("pdf_page")
    if page not in (None, "", [], 0):
        return f"p.{'-'.join(map(str, page)) if isinstance(page, list) else page}"
    section = str(result.get("section") or "").strip()
    return section if not section or section.startswith("§") else "§" + section


def render_citations(text: str, records: dict[str, dict]) -> tuple[str, list[str]]:
    """Replace citation keys and the references marker. Text without either comes back unchanged."""
    order: dict[str, int] = {}
    cited_locators: dict[str, list[str]] = {}
    warnings: list[str] = []
    out: list[str] = []
    marker_seen = False
    for _, line, kind in _lines(text):
        if kind == "comment" and line.strip() == REFERENCES_MARKER:
            marker_seen = True
            out.append(line)
            continue
        if kind != "text":
            out.append(line)
            continue
        found = citations_in(line)
        if not found:
            out.append(line)
            continue
        pieces, last = [], 0
        for start, end, items in found:
            known, unknown = [], []
            for item in items:
                key = item["key"]
                record = records.get(key)
                if record is None:
                    unknown.append(f"[\\@{key}?]")
                    warnings.append(f"citation_unknown_key: {key}")
                    continue
                number = order.setdefault(key, len(order) + 1)
                locator = item["loc"]
                if item["rid"]:
                    res = _result(record, item["rid"])
                    if res is None:
                        warnings.append(f"citation_unknown_result: {key}#{item['rid']}")
                    elif not locator:
                        locator = result_locator(res) or None
                if locator:
                    cited_locators.setdefault(key, []).append(locator)
                known.append(f"{short_authors(record, key)}, {year_of(record, key)} [{number}]"
                             + (f", {locator}" if locator else ""))
            rendered = " ".join(([f"({'; '.join(known)})"] if known else []) + unknown)
            pieces += [line[last:start], rendered]
            last = end
        pieces.append(line[last:])
        out.append("".join(pieces))
    if not order and not warnings and not marker_seen:
        return text, []
    result = "".join(out)
    if marker_seen:
        table = references_table(order, records)
        result = "".join(table if kind == "comment" and line.strip() == REFERENCES_MARKER else line
                         for _, line, kind in _lines(result))
    return result, list(dict.fromkeys(warnings))


def _cell(value: Any) -> str:
    return " ".join(str(value if value is not None else "").split()).replace("|", "\\|")


def references_table(order: dict[str, int], records: dict[str, dict]) -> str:
    rows = ["| 번호 | 문헌 | 읽은 판 | 근거 |", "|---|---|---|---|"]
    for key, number in sorted(order.items(), key=lambda kv: kv[1]):
        record = records[key]
        parts = [_cell(record.get("title") or key)]
        venue = record.get("venue") or record.get("journal")
        if venue:
            parts.append("*" + _cell(venue) + "*")
        parts.append(year_of(record, key))
        doi = doi_of(record)
        if doi:
            parts.append(f"[doi:{_cell(doi)}](https://doi.org/{doi})")
        label = ev.derive_label(record)
        basis = label["label"] + (f" ({label['locator']})" if label["locator"] else "")
        rows.append(f"| {number} | {'. '.join(parts)} | {_cell(record.get('version') or '-')} | {_cell(basis)} |")
    if len(rows) == 2:
        rows.append("| - | (인용된 문헌 없음) | - | - |")
    return "\n".join(rows) + "\n"


def citation_pass(markdown_path: str | Path, text: str) -> tuple[str, list[str]]:
    """Render-time pass: (Markdown to render, warnings). Never raises."""
    if "[@" not in text and REFERENCES_MARKER not in text:
        return text, []
    try:
        topic = find_topic(markdown_path)
        return render_citations(text, load_records(topic / "evidence" if topic else None))
    except Exception as exc:  # the citation pass must never break a render
        return text, [f"citation_pass_failed: {type(exc).__name__}"]


# ---------------------------------------------------------------- numbers

_SUPERSCRIPT = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺", "0123456789-+")
_MINUS = "-−‐‑–"  # hyphen, minus sign, hyphens and en dash used as a minus before a number
# A sign counts only when it does not follow a digit, letter, closing bracket or decimal point:
# "−0.5", "(−3", "= -2" are negative; "14–24" (range) and "MACE-MP-0" (name) are not.
_SIGN = r"(?P<sign>(?<![\w.,)\]])[" + _MINUS + r"+])?"
_EXPONENT = (r"(?:[eE](?P<e1>[" + _MINUS + r"+]?\d+)"                       # 1.2e-3
             r"|\s*[×x·*]\s*10\s*(?:\^|\*\*)\s*(?P<e2>[" + _MINUS + r"+]?\d+)"  # 1.2 × 10^-3
             r"|\s*[×x·*]\s*10(?P<e3>[⁻⁺]?[⁰¹²³⁴⁵⁶⁷⁸⁹]+)"                      # 1.2×10⁻³
             r"|\s*[×x·*]\s*10(?P<e4>[" + _MINUS + r"]\d+))?")                   # 1.2×10-3 (plain text)
SCI_NUMBER = re.compile(_SIGN + r"(?<![A-Za-z0-9_.,])(?P<mant>\d{1,3}(?:,\d{3})+|\d+)(?P<frac>\.\d+)?" + _EXPONENT)
LOOSE_SCI_NUMBER = re.compile(_SIGN + r"(?P<mant>\d{1,3}(?:,\d{3})+(?![\d])|\d+)(?P<frac>\.\d+)?" + _EXPONENT)
# A bare power of ten: 10^-3, 10**-3, 10⁻³.
_BARE_POWER = re.compile(r"\s*(?:(?:\^|\*\*)\s*(?P<p1>[" + _MINUS + r"+]?\d+)|(?P<p2>[⁻⁺]?[⁰¹²³⁴⁵⁶⁷⁸⁹]+))")


def _exponent(text: str | None) -> int | None:
    if not text:
        return None
    text = text.translate(_SUPERSCRIPT)
    for ch in _MINUS:
        text = text.replace(ch, "-")
    try:
        return int(text)
    except ValueError:
        return None


def number_tokens(text: str, strict: bool = True) -> list[tuple[str, float]]:
    """(as written, value) for each number, keeping its sign and any power of ten.

    Ranges ("14–24") and ± give both ends; "1.2×10⁻³", "1.2 × 10^-3", "1.2e-3" and a bare
    "10^-3" are read as one value."""
    out = []
    pattern = SCI_NUMBER if strict else LOOSE_SCI_NUMBER
    pos = 0
    while True:
        match = pattern.search(text, pos)
        if not match:
            break
        pos = match.end()
        mant = match.group("mant")
        frac = match.group("frac") or ""
        raw = match.group(0).strip()
        try:
            value = float(mant.replace(",", "") + frac)
        except ValueError:
            continue
        exp = _exponent(match.group("e1") or match.group("e2") or match.group("e3") or match.group("e4"))
        if exp is None and mant == "10" and not frac:
            power = _BARE_POWER.match(text, match.end())
            if power:
                exp = _exponent(power.group("p1") or power.group("p2"))
                if exp is not None:
                    value, raw = 1.0, raw + power.group(0).strip()
                    pos = power.end()
        if exp is not None:
            value *= 10.0 ** exp
        if match.group("sign") and match.group("sign") != "+":
            value = -value
        out.append((raw, value))
    return out


def values_match(written: str, value: float, candidate: float) -> bool:
    """Same sign; exact for integers, within 1% for decimals and powers of ten."""
    if (value < 0) != (candidate < 0) and value != 0 and candidate != 0:
        return False
    if "." in written or any(m in written for m in ("e", "E", "×", "^", "x", "·", "*")) \
            or any(ch in written for ch in "⁰¹²³⁴⁵⁶⁷⁸⁹"):
        return abs(value - candidate) <= 0.01 * max(abs(value), abs(candidate)) + 1e-300
    return value == candidate


def _texts(value: Any) -> Iterable[str]:
    if value is None:
        return
    if isinstance(value, (list, tuple)):
        for v in value:
            yield from _texts(v)
    elif isinstance(value, dict):
        for v in value.values():
            yield from _texts(v)
    else:
        yield str(value)


def record_numbers(record: dict) -> list[float]:
    """Numbers a report may take from this record: results, criteria judgments/reasons, summaries, year."""
    texts: list[str] = [str(record.get("year") or "")]
    for res in results(record):
        for field in ("value", "lo", "hi", "condition"):
            texts.extend(_texts(res.get(field)))
    for criterion in record.get("criteria") or []:
        if isinstance(criterion, dict):
            texts.extend(_texts(criterion.get("judgment")))
            texts.extend(_texts(criterion.get("reason")))
            for loc in criterion.get("evidence") or []:
                if isinstance(loc, dict):
                    for field in ("summary", "quote"):
                        texts.extend(_texts(loc.get(field)))
    return [v for t in texts for _, v in number_tokens(t, strict=False)]


def _prose(text: str) -> str:
    """Sentence text with markup, links, URLs and figure/table/section numbers removed."""
    text = CODE_SPAN.sub(" ", text)
    text = LINK_TARGET.sub(r"\1", text)
    text = URL.sub(" ", text)
    text = HTML_TAG.sub(" ", text)
    text = NAME_VERSION.sub(r"\1", text)
    return NOT_A_VALUE.sub(" ", text)


# ---------------------------------------------------------------- locators

def _norm_section(text: str) -> str:
    return re.sub(r"\s+", "", str(text)).lstrip("§").lower().rstrip(".")


def _pages(value: Any) -> set[int]:
    if isinstance(value, bool) or value in (None, "", 0):
        return set()
    if isinstance(value, int):
        return {value}
    if isinstance(value, list):
        nums = [v for v in value if isinstance(v, int) and not isinstance(v, bool)]
        if len(nums) == 2 and nums[0] < nums[1]:
            return set(range(nums[0], nums[1] + 1))
        return set(nums)
    match = re.fullmatch(r"\s*(\d+)\s*(?:[-–]\s*(\d+))?\s*", str(value))
    if match:
        a, b = int(match.group(1)), int(match.group(2) or match.group(1))
        return set(range(a, b + 1)) if a <= b else {a}
    return set()


def locator_found(record: dict, loc: str) -> bool:
    places = ev.locators(record) + results(record)
    pages = set().union(*(_pages(p.get("pdf_page")) for p in places)) if places else set()
    sections = [str(p.get("section") or "") for p in places if str(p.get("section") or "").strip()]
    wanted_pages: list[int] = []
    for m in re.finditer(r"\bpp?\.\s*(\d+)(?:\s*[-–]\s*(\d+))?", loc):
        first = int(m.group(1))
        last = int(m.group(2)) if m.group(2) and int(m.group(2)) >= first else first
        wanted_pages += range(first, last + 1)
    wanted_sections = [m.group(1) for m in re.finditer(r"§\s*([^\s,;]+)", loc)]
    if not wanted_pages and not wanted_sections:
        target = _norm_section(loc)
        return any(target in _norm_section(s) for s in sections)
    if any(p not in pages for p in wanted_pages):
        return False
    for wanted in wanted_sections:
        target = _norm_section(wanted)
        if not any(_norm_section(s) == target or _norm_section(s).startswith(target)
                   or _norm_section(ev.short_section(s.lstrip("§"))) == target for s in sections):
            return False
    return True


# ---------------------------------------------------------------- sentences

def _split_sentences(text: str) -> list[str]:
    pieces = re.split(r"(?<=[.?!])\s+|(?<=。)", text)
    out: list[str] = []
    for piece in pieces:
        if out and out[-1].split() and out[-1].split()[-1].lower() in ABBREVIATIONS:
            out[-1] += " " + piece
        else:
            out.append(piece)
    return [p.strip() for p in out if p.strip()]


def sentences(text: str) -> list[dict[str, Any]]:
    """Sentences with their line number, citations and whether they sit in the summary section."""
    out: list[dict[str, Any]] = []
    summary_level: int | None = None
    for number, line, kind in _lines(text):
        if kind != "text":
            continue
        raw = line.rstrip("\r\n")
        heading = HEADING.match(raw)
        if heading:
            level = len(heading.group(1))
            if summary_level is not None and level <= summary_level:
                summary_level = None
            if summary_level is None and SUMMARY_HEADING.search(heading.group(2)):
                summary_level = level
        if not raw.strip() or TABLE_SEPARATOR.match(raw) and "-" in raw:
            continue
        found = citations_in(raw)
        placeholders: list[list[dict]] = []
        pieces, last = [], 0
        for start, end, items in found:
            pieces += [raw[last:start], f"\x01{len(placeholders)}\x01"]
            placeholders.append(items)
            last = end
        pieces.append(raw[last:])
        body = "".join(pieces)
        if heading:
            body = re.sub(r"^\s{0,3}#{1,6}\s+", "", body)
        stripped = re.sub(r"^\s*(?:>\s*)*(?:(?:[-*+]|\d+[.)])\s+)?", "", body)
        chunks = [stripped] if raw.lstrip().startswith("|") or heading else _split_sentences(stripped)
        for chunk in chunks:
            cites = [placeholders[int(i)] for i in re.findall(r"\x01(\d+)\x01", chunk)]
            plain = re.sub(r"\x01\d+\x01", " ", chunk)
            out.append({"line": number, "text": re.sub(r"\x01(\d+)\x01", "[cite]", chunk).strip(),
                        "citations": [item for c in cites for item in c], "plain": plain,
                        "summary": summary_level is not None and not heading, "heading": bool(heading)})
    return out


# ---------------------------------------------------------------- trace

def _finding(level: str, line: int, rule: str, message: str, text: str = "") -> dict[str, Any]:
    return {"level": level, "line": line, "rule": rule, "message": message, "sentence": _short(text, 90)}


def _short(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def trace_text(text: str, records: dict[str, dict]) -> dict[str, Any]:
    from scholarly_access_agent.evidence import is_preliminary

    findings: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for sentence in sentences(text):
        numbers = number_tokens(_prose(sentence["plain"]))
        line, shown = sentence["line"], sentence["text"]
        if not sentence["citations"]:
            if numbers and sentence["summary"]:
                findings.append(_finding("warning", line, "uncited_number",
                                         f"number(s) {', '.join(n for n, _ in numbers)} in the summary "
                                         "without a citation", shown))
            continue
        keys = list(dict.fromkeys(item["key"] for item in sentence["citations"]))
        known = [k for k in keys if k in records]
        for item in sentence["citations"]:
            key = item["key"]
            if key not in records:
                findings.append(_finding("error", line, "unknown_key", f"no evidence/{key}.json", shown))
                continue
            record = records[key]
            if item["rid"] and _result(record, item["rid"]) is None:
                findings.append(_finding("error", line, "unknown_result",
                                         f"{key} has no result id {item['rid']}", shown))
            if item["loc"] and not locator_found(record, item["loc"]):
                findings.append(_finding("warning", line, "locator_not_in_record",
                                         f"{key}: {item['loc']} is not among its locators or results", shown))
        pool = {k: record_numbers(records[k]) for k in known}
        checked = []
        for written, value in numbers:
            where = [k for k, values in pool.items() if any(values_match(written, value, v) for v in values)]
            checked.append({"number": written, "found_in": where})
            if known and not where:
                findings.append(_finding("warning", line, "number_not_in_record",
                                         f"{written} not in {', '.join(known)}", shown))
            elif sentence["summary"] and where and all(is_preliminary(records[k]) for k in where):
                findings.append(_finding("warning", line, "summary_rests_on_preliminary",
                                         f"{written} comes only from preliminary evidence ({', '.join(where)}); "
                                         "the summary needs a peer-reviewed full-text source or a 예비 근거 label",
                                         shown))
        rows.append({"line": line, "text": shown, "keys": keys, "numbers": checked})
    counts = {level: sum(1 for f in findings if f["level"] == level) for level in ("error", "warning")}
    return {"ok": counts["error"] == 0, "sentences": rows, "findings": findings,
            "summary": {"cited_sentences": len(rows), "errors": counts["error"], "warnings": counts["warning"]}}


def trace_report(markdown_path: str | Path, evidence_dir: str | Path | None = None) -> dict[str, Any]:
    path = Path(markdown_path).expanduser().resolve()
    if evidence_dir is None:
        topic = find_topic(path)
        evidence_dir = topic / "evidence" if topic else None
    folder = Path(evidence_dir).expanduser().resolve() if evidence_dir else None
    text = path.read_text(encoding="utf-8")
    records = load_records(folder)
    result = trace_text(text, records)
    # figures: `![..](figs/x.html)` with a sibling figs/x.fig.json must resolve to evidence like a citation
    from scholarly_access_agent.viz.figure import check_report
    figures = check_report(text, path.parent, records)
    if figures:
        result["findings"] = sorted(result["findings"] + figures, key=lambda f: f["line"])
        for level in ("error", "warning"):
            result["summary"][level + "s"] = sum(1 for f in result["findings"] if f["level"] == level)
        result["ok"] = result["summary"]["errors"] == 0
    result["summary"]["figure_findings"] = len(figures)
    return {"report": str(path), "evidence_folder": str(folder) if folder else None, **result}


def summary_line(result: dict[str, Any]) -> str:
    s = result["summary"]
    return f"report_trace: {s['errors']} errors, {s['warnings']} warnings"


def render_warnings(markdown_path: str | Path) -> list[str]:
    """Trace summary for render-report: only when the report cites keys or sits by evidence/."""
    try:
        path = Path(markdown_path).expanduser().resolve()
        text = path.read_text(encoding="utf-8")
        if find_topic(path) is None and not any(citations_in(l) for _, l, k in _lines(text) if k == "text"):
            return []
        result = trace_report(path)
        return [summary_line(result) + f" (run `scholarly-access-agent report trace {path.name}`)"]
    except Exception as exc:  # the trace must never break a render
        return [f"report_trace_failed: {type(exc).__name__}"]


# ---------------------------------------------------------------- cli

def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(prog="scholarly-access-agent report", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    tr = sub.add_parser("trace", help="Check cited sentences against evidence records; exit 1 on errors.")
    tr.add_argument("path", help="report Markdown file")
    tr.add_argument("--evidence", help="evidence folder (default: evidence/ next to the report or its parent)")
    tr.add_argument("--json", action="store_true", help="print JSON")
    a = ap.parse_args(argv)
    path = Path(a.path).expanduser()
    if not path.is_file():
        print(f"not a file: {a.path}", file=sys.stderr)
        return 2
    result = trace_report(path, a.evidence)
    if a.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
    else:
        if result["evidence_folder"] is None:
            print("no evidence/ folder found next to the report (or its parent)")
        if result["findings"]:
            print(ev._table(["level", "line", "rule", "message", "sentence"],
                            ([f["level"], f["line"], f["rule"], f["message"], f["sentence"]]
                             for f in result["findings"])))
            print()
        s = result["summary"]
        print(f"{s['errors']} errors, {s['warnings']} warnings in {s['cited_sentences']} cited sentences")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
