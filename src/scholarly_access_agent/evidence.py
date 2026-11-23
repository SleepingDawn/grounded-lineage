"""Lint evidence records and derive the report's read-depth labels from them.

  scholarly-access-agent evidence lint <topic folder or evidence folder> [--json]
  scholarly-access-agent evidence labels <topic folder> [--markdown | --json]

How much of a paper was read is stated by the record (`access`, `read_via`, each
locator's `read_mode`), never by hand in the report. `lint` checks that these fields
agree with each other and with `version`; it also re-derives novelty verdicts
(`ideas/novelty/*.json`) from the overlap grades. `labels` prints the Korean label
(본문 확인 / 발췌 확인 / 인용 맥락만 / 초록만 확인 / 미확인) and a short locator per record.
Format: skills/snu-library-scholarly-access/references/evidence-format.md.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any, Iterable

FULLTEXT = ("fulltext_pdf", "fulltext_html")
LEGACY_FULLTEXT = "fulltext"
ACCESS = FULLTEXT + ("excerpts", "secondary", "abstract_only", "unavailable")
READ_MODES = ("pages", "sections", "terms", "figure", "caption", "citing")
BODY_MODES = ("pages", "sections", "figure")
EXCERPT_MODES = ("terms", "caption")
READ_VIA = ("read_pdf", "read_url", "web_summary", "citing_paper", "manual", "none")
PRELIMINARY_VENUES = ("conference_abstract", "preprint")
PRELIMINARY_ACCESS = ("excerpts", "secondary", "abstract_only")

LABEL_BODY = "본문 확인"
LABEL_EXCERPTS = "발췌 확인"
LABEL_SECONDARY = "인용 맥락만"
LABEL_ABSTRACT = "초록만 확인"
LABEL_NONE = "미확인"

GRADES = {"exact": 5, "high": 4, "medium": 3, "low": 2, "none": 1}
VERDICTS = ("not-novel", "reframe", "provisional", "novel")

DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>]+", re.IGNORECASE)
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
SECTION_ID_RE = re.compile(r"^\s*((?:[IVXLC]+|\d+|[A-Z])(?:\.[A-Za-z0-9]+)*)\b")


# ---------------------------------------------------------------- record helpers

def locators(record: dict) -> list[dict]:
    """All criteria[].evidence[] items that are objects."""
    out = []
    for criterion in record.get("criteria") or []:
        if isinstance(criterion, dict):
            out.extend(e for e in (criterion.get("evidence") or []) if isinstance(e, dict))
    return out


def _has_page(loc: dict) -> bool:
    return loc.get("pdf_page") not in (None, "", [], 0)


def _has_section(loc: dict) -> bool:
    return bool(str(loc.get("section") or "").strip())


def _is_fulltext(access: Any) -> bool:
    return access in FULLTEXT or access == LEGACY_FULLTEXT


def _journal_doi(record: dict) -> str | None:
    for key in ("journal_version", "paper_id", "doi"):
        value = record.get(key)
        if isinstance(value, str):
            match = DOI_RE.search(value)
            if match and not match.group(0).lower().startswith("10.48550/"):  # arXiv DOIs
                return match.group(0).rstrip(".,;)")
    return None


def _is_preprint_version(version: Any) -> bool:
    text = str(version or "").strip().lower()
    if not text:
        return False
    if text.startswith(("arxiv", "preprint")):
        return True
    if not re.search(r"\b(arxiv|preprint)\b", text):
        return False
    # "publisher PDF ...; arXiv fallback not needed", "Journal version via PMC ... from arXiv" are not preprint reads
    return not re.search(r"publisher|journal version (via|read)|version of record|typeset", text)


def _route_has_dated_journal_retry(route: Any) -> bool:
    text = str(route or "")
    for match in DATE_RE.finditer(text):
        window = text[max(0, match.start() - 60): match.end() + 60].lower()
        if "journal" in window and re.search(r"retr(y|ied|ies)|re-?tried|attempt", window):
            return True
    return False


def short_section(section: str, limit: int = 28) -> str:
    section = " ".join(str(section).split())
    match = SECTION_ID_RE.match(section)
    if match:
        return match.group(1)
    return section if len(section) <= limit else section[: limit - 1].rstrip() + "…"


def format_locator(loc: dict | None) -> str:
    if not loc:
        return ""
    parts = []
    if _has_section(loc):
        parts.append("§" + short_section(loc["section"]))
    if _has_page(loc):
        page = loc["pdf_page"]
        parts.append(f"p.{'-'.join(map(str, page)) if isinstance(page, list) else page}")
    return " ".join(parts)


# ---------------------------------------------------------------- labels

def derive_label(record: dict) -> dict[str, str]:
    """{"label", "locator", "basis"} for one evidence record."""
    access = record.get("access")
    read_via = record.get("read_via")
    locs = locators(record)
    first = next((l for l in locs if _has_page(l) or _has_section(l)), locs[0] if locs else None)
    if _is_fulltext(access):
        body = [l for l in locs if l.get("read_mode") in BODY_MODES]
        if not body and read_via in ("read_pdf", "read_url"):
            body = [l for l in locs if not l.get("read_mode") and (_has_page(l) or _has_section(l))]
        if body:
            basis = "read_mode " + body[0]["read_mode"] if body[0].get("read_mode") else f"locator + read_via {read_via}"
            return {"label": LABEL_BODY, "locator": format_locator(body[0]), "basis": basis}
        modes = {l.get("read_mode") for l in locs}
        if locs and modes <= set(EXCERPT_MODES):
            basis = "all locators read_mode terms/caption"
        elif read_via not in ("read_pdf", "read_url"):
            basis = f"no read_mode and read_via {read_via or 'missing'}: whole-passage reading not shown"
        else:
            basis = "no locator read as pages/sections/figure"
        return {"label": LABEL_EXCERPTS, "locator": format_locator(first), "basis": basis}
    if access == "excerpts":
        return {"label": LABEL_EXCERPTS, "locator": format_locator(first), "basis": "access excerpts"}
    if access == "secondary":
        return {"label": LABEL_SECONDARY, "locator": format_locator(first), "basis": "access secondary"}
    if access == "abstract_only":
        return {"label": LABEL_ABSTRACT, "locator": "", "basis": "access abstract_only"}
    return {"label": LABEL_NONE, "locator": "", "basis": f"access {access or 'missing'}"}


# ---------------------------------------------------------------- lint

def _finding(level: str, file: str, rule: str, message: str) -> dict[str, str]:
    return {"level": level, "file": file, "rule": rule, "message": message}


def lint_record(record: Any, file: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    err = lambda rule, msg: out.append(_finding("error", file, rule, msg))  # noqa: E731
    warn = lambda rule, msg: out.append(_finding("warning", file, rule, msg))  # noqa: E731
    if not isinstance(record, dict):
        err("not_an_object", "record is not a JSON object")
        return out
    for key in ("paper_id", "title"):
        if not str(record.get(key) or "").strip():
            err(f"missing_{key}", f"{key} is missing")

    access = record.get("access")
    read_via = record.get("read_via")
    locs = locators(record)
    if access in (None, ""):
        err("access_missing", f"access is missing (one of {', '.join(ACCESS)})")
    elif access == LEGACY_FULLTEXT:
        warn("access_legacy_fulltext", "ambiguous: say fulltext_pdf/fulltext_html, or excerpts")
    elif access not in ACCESS:
        err("access_invalid", f"access {access!r} is not one of {', '.join(ACCESS)}")

    if _is_fulltext(access) and not any(_has_page(l) or _has_section(l) for l in locs):
        err("fulltext_without_locator", f"access {access} but no locator has pdf_page or section")
    if access in ("abstract_only", "unavailable") and any(_has_page(l) for l in locs):
        err("pdf_page_without_fulltext", f"access {access} but locators cite pdf_page")
    if read_via == "web_summary" and _is_fulltext(access):
        err("web_summary_fulltext", "read_via web_summary is a model-written summary, not full text")

    if _is_preprint_version(record.get("version")):
        doi = _journal_doi(record)
        reason = record.get("preprint_fallback_reason")
        has_reason = reason is not None and str(reason).strip().lower() not in ("", "null", "none")
        if doi and not has_reason:
            if _route_has_dated_journal_retry(record.get("route")):
                warn("preprint_reason_in_route", f"preprint read with journal DOI {doi}; set "
                     "preprint_fallback_reason (route documents a dated journal retry)")
            else:
                err("preprint_without_reason", f"version is a preprint but the record has journal DOI {doi} "
                    "and no preprint_fallback_reason")

    if read_via in (None, ""):
        warn("read_via_missing", f"read_via is missing (one of {', '.join(READ_VIA)})")
    elif read_via not in READ_VIA:
        warn("read_via_unknown", f"read_via {read_via!r} is not one of {', '.join(READ_VIA)}")
    for key in ("venue_type", "evidence_role"):
        if not record.get(key):
            warn(f"{key}_missing", f"{key} is missing")
    bad_modes = sorted({str(l["read_mode"]) for l in locs if l.get("read_mode") not in (None, *READ_MODES)})
    if bad_modes:
        warn("read_mode_unknown", f"read_mode {', '.join(bad_modes)} not one of {', '.join(READ_MODES)}")
    if (access in FULLTEXT and locs and all(l.get("read_mode") in EXCERPT_MODES for l in locs)):
        warn("fulltext_terms_only", "all locators are read_mode terms/caption: access should be excerpts")

    venue = record.get("venue_type")
    if venue in PRELIMINARY_VENUES or access in PRELIMINARY_ACCESS:
        why = f"venue_type {venue}" if venue in PRELIMINARY_VENUES else f"access {access}"
        out.append(_finding("info", file, "preliminary_evidence", f"예비 근거 only ({why})"))
    return out


def derive_verdict(record: dict) -> tuple[str, str]:
    """Novelty verdict from the closest papers' grades: (verdict, reason)."""
    closest = [c for c in (record.get("closest") or []) if isinstance(c, dict)]
    if not closest:
        return "provisional", "no closest papers graded"
    graded = [(GRADES.get(str(c.get("grade") or "").strip().lower(), 0), c) for c in closest]
    if any(g == GRADES["exact"] for g, _ in graded):
        return "not-novel", "a closest paper is graded Exact"
    if any(g == GRADES["high"] for g, _ in graded):
        return "reframe", "a closest paper is graded High"
    unverified = [c for g, c in graded if g == 0]
    if unverified:
        return "provisional", f"{unverified[0].get('paper_id', '?')} has no grade (unverified)"
    top = max(g for g, _ in graded)
    for g, c in graded:
        if g == top and (not _is_fulltext(c.get("access")) or c.get("read_via") == "web_summary"):
            return "provisional", (f"highest-graded paper {c.get('paper_id', '?')} not read in full "
                                   f"(access {c.get('access')}, read_via {c.get('read_via')})")
    return "novel", "all closest papers Medium or lower, highest-graded read in full"


def lint_novelty(record: Any, file: str) -> tuple[list[dict[str, str]], dict[str, Any]]:
    out: list[dict[str, str]] = []
    if not isinstance(record, dict):
        return [_finding("error", file, "not_an_object", "record is not a JSON object")], {}
    derived, reason = derive_verdict(record)
    stored = str(record.get("verdict") or "").strip().lower()
    row = {"file": file, "card": record.get("card"), "stored": stored or None, "derived": derived, "reason": reason}
    for c in record.get("closest") or []:
        if isinstance(c, dict) and c.get("access") == LEGACY_FULLTEXT:
            out.append(_finding("warning", file, "access_legacy_fulltext",
                                f"{c.get('paper_id', '?')}: ambiguous: say fulltext_pdf/fulltext_html, or excerpts"))
    if not stored:
        out.append(_finding("error", file, "novelty_verdict_missing", f"verdict missing; derived {derived} ({reason})"))
    elif stored != derived:
        if stored == "reframe" and record.get("reframed_from"):
            out.append(_finding("warning", file, "novelty_reframed",
                                f"stored reframe accepted for a rewritten card; derived {derived} ({reason})"))
        else:
            out.append(_finding("error", file, "novelty_verdict_mismatch",
                                f"stored {stored} but derived {derived} ({reason})"))
    elif derived == "reframe" and record.get("reframed_from"):
        out.append(_finding("warning", file, "novelty_second_high",
                            "rewritten card graded High again: a second High makes it not-novel"))
    return out, row


def _load(path: Path) -> tuple[Any, str | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def resolve_folders(path: str | Path) -> tuple[Path, Path | None, Path | None]:
    """(topic, evidence dir, novelty dir) for a topic folder or an evidence folder."""
    path = Path(path).expanduser()
    if (path / "evidence").is_dir():
        topic, evidence = path, path / "evidence"
    elif path.is_dir() and (path.name == "evidence" or any(
            '"paper_id"' in f.read_text(encoding="utf-8", errors="replace") for f in path.glob("*.json"))):
        topic, evidence = path.parent, path
    else:
        topic, evidence = path, None
    novelty = topic / "ideas" / "novelty"
    return topic, evidence, novelty if novelty.is_dir() else None


def lint_folder(path: str | Path) -> dict[str, Any]:
    topic, evidence, novelty = resolve_folders(path)
    findings: list[dict[str, str]] = []
    novelty_rows: list[dict[str, Any]] = []
    records = 0
    for folder, kind in ((evidence, "evidence"), (novelty, "novelty")):
        if folder is None:
            continue
        for file in sorted(folder.glob("*.json")):
            name = file.relative_to(topic).as_posix() if file.is_relative_to(topic) else file.name
            data, problem = _load(file)
            if problem:
                findings.append(_finding("error", name, "invalid_json", problem))
                continue
            if kind == "evidence":
                records += 1
                findings.extend(lint_record(data, name))
            else:
                found, row = lint_novelty(data, name)
                findings.extend(found)
                if row:
                    novelty_rows.append(row)
    counts = {level: sum(1 for f in findings if f["level"] == level) for level in ("error", "warning", "info")}
    return {
        "ok": counts["error"] == 0 and evidence is not None,
        "topic": str(topic),
        "evidence_folder": str(evidence) if evidence else None,
        "summary": {"records": records, "novelty_records": len(novelty_rows), "errors": counts["error"],
                    "warnings": counts["warning"], "info": counts["info"]},
        "findings": findings,
        "novelty": novelty_rows,
    }


def labels_folder(path: str | Path) -> list[dict[str, Any]]:
    topic, evidence, _ = resolve_folders(path)
    rows = []
    for file in sorted(evidence.glob("*.json")) if evidence else []:
        data, problem = _load(file)
        if problem or not isinstance(data, dict):
            rows.append({"file": file.name, "title": "", "label": LABEL_NONE, "locator": "",
                         "basis": "unreadable record", "venue_type": None, "version": None})
            continue
        rows.append({"file": file.name, "title": _short(data.get("title"), 50), **derive_label(data),
                     "venue_type": data.get("venue_type"), "version": _short(data.get("version"), 40)})
    return rows


def summary_line(result: dict[str, Any], folder: str | Path) -> str:
    s = result["summary"]
    return (f"evidence_lint: {s['errors']} errors, {s['warnings']} warnings, {s['info']} info "
            f"(run `scholarly-access-agent evidence lint {folder}`)")


# ---------------------------------------------------------------- output

def _short(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def _table(headers: list[str], rows: Iterable[list[str]]) -> str:
    rows = [[str(c) for c in r] for r in rows]
    widths = [max([_width(h)] + [_width(r[i]) for r in rows]) for i, h in enumerate(headers)]
    line = lambda cells: "  ".join(c + " " * (w - _width(c)) for c, w in zip(cells, widths)).rstrip()  # noqa: E731
    return "\n".join([line(headers), line(["-" * w for w in widths])] + [line(r) for r in rows])


def _cell(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|")


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(prog="scholarly-access-agent evidence", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    lint = sub.add_parser("lint", help="Check evidence (and novelty) records; exit 1 on any error.")
    lint.add_argument("path", help="topic folder or its evidence/ folder")
    lint.add_argument("--json", action="store_true", help="print JSON instead of a table")
    lab = sub.add_parser("labels", help="Derived read-depth label and locator per evidence record.")
    lab.add_argument("path", help="topic folder or its evidence/ folder")
    fmt = lab.add_mutually_exclusive_group()
    fmt.add_argument("--markdown", action="store_true", help="print a Markdown pipe table for a report")
    fmt.add_argument("--json", action="store_true", help="print JSON")
    a = ap.parse_args(argv)

    if not Path(a.path).expanduser().is_dir():
        print(f"not a folder: {a.path}", file=sys.stderr)
        return 2
    if a.command == "lint":
        result = lint_folder(a.path)
        if a.json:
            print(json.dumps(result, ensure_ascii=False, indent=1))
        else:
            if result["evidence_folder"] is None:
                print(f"no evidence/ folder found under {a.path}")
            if result["findings"]:
                print(_table(["level", "file", "rule", "message"],
                             ([f["level"], f["file"], f["rule"], f["message"]] for f in result["findings"])))
            if result["novelty"]:
                print()
                print(_table(["novelty", "stored", "derived", "reason"],
                             ([r["file"], r["stored"] or "-", r["derived"], r["reason"]] for r in result["novelty"])))
            print()
            s = result["summary"]
            print(f"{s['errors']} errors, {s['warnings']} warnings, {s['info']} info in {s['records']} evidence "
                  f"and {s['novelty_records']} novelty records")
        return 0 if result["summary"]["errors"] == 0 and result["evidence_folder"] else 1

    rows = labels_folder(a.path)
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
    elif a.markdown:
        print("| 파일 | 제목 | 확인 수준 | 위치 | venue_type | version |")
        print("|---|---|---|---|---|---|")
        for r in rows:
            print("| " + " | ".join(_cell(r[k]) for k in ("file", "title", "label", "locator", "venue_type", "version"))
                  + " |")
    else:
        print(_table(["file", "title", "label", "locator", "venue_type", "version"],
                     ([r["file"], r["title"], r["label"], r["locator"], r["venue_type"] or "-", r["version"]]
                      for r in rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
