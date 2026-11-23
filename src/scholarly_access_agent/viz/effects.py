"""effects: a forest plot of every evidence result whose quantity matches a regex, across records.

A thin wrapper over the row-chart renderer that `viz figure` also uses (viz/rows.py): it collects the results by
quantity, then draws them grouped by study design, ordered by year or value inside each group, with the read depth
as the point fill (full = 본문 확인, half = 발췌 확인, hollow = 초록만 / 인용 맥락만)."""
from __future__ import annotations

import re
from pathlib import Path

from scholarly_access_agent.evidence import LABEL_NONE, derive_label

from .common import VizError, design_of, fill_of, load_records, result_label, study_label, year_of
from .rows import HALF_PATH, axis_domain, decimals_for, row_chart  # noqa: F401  (re-exported for callers)

NUM = r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?"
RANGE_RE = re.compile(rf"^\s*[~≈]?\s*({NUM})\s*(?:-|–|—|~|to|…|\.\.)\s*({NUM})\s*$")
PM_RE = re.compile(rf"^\s*({NUM})\s*(?:±|\+/-|\+-)\s*({NUM})\s*$")
SINGLE_RE = re.compile(rf"^\s*[~≈<>≤≥]?\s*({NUM})\s*$")


def parse_value(result: dict) -> tuple[float, float | None, float | None] | None:
    """(value, lo, hi) from a result; a printed range "14-24" becomes lo/hi with its midpoint as the value."""
    raw, lo, hi = result.get("value"), result.get("lo"), result.get("hi")

    def num(x):
        if isinstance(x, bool) or x is None or x == "":
            return None
        if isinstance(x, (int, float)):
            return float(x)
        m = SINGLE_RE.match(str(x).replace(",", ""))
        return float(m.group(1)) if m else None

    lo, hi = num(lo), num(hi)
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw), lo, hi
    text = str(raw if raw is not None else "").replace(",", "").strip()
    m = RANGE_RE.match(text)
    if m:
        a, b = sorted((float(m.group(1)), float(m.group(2))))
        return round((a + b) / 2, 10), lo if lo is not None else a, hi if hi is not None else b
    m = PM_RE.match(text)
    if m:
        v, e = float(m.group(1)), float(m.group(2))
        return v, lo if lo is not None else v - e, hi if hi is not None else v + e
    v = num(text)
    if v is None:
        return None
    return v, lo, hi


def norm_unit(unit: str) -> str:
    """Comparable unit key: "W/mK", "W/(m K)", "W m^-1 K^-1" and "W·m⁻¹·K⁻¹" all give "w/mk"."""
    u = str(unit or "").strip().lower().replace("−", "-").replace("–", "-").replace("⁻¹", "-1").replace("^", "")
    u = re.sub(r"[(){}\[\]]", " ", u)
    num, den, below = [], [], False
    for tok in re.split(r"[\s·*]+", u):
        if not tok:
            continue
        if tok.endswith("-1") and len(tok) > 2:
            den.append(tok[:-2])
            continue
        head, *rest = tok.split("/")
        if head:
            (den if below else num).append(head)
        if rest:
            below = True
            den.extend(r for r in rest if r)
    out = "".join(num) + ("/" + "".join(den) if den else "")
    return "%" if out in ("percent", "pct", "퍼센트", "%") else out


def quantity_name(rows: list[dict]) -> str:
    """The most common quantity string without a trailing parenthetical: "kappa (GK)" -> "kappa"."""
    names: dict[str, int] = {}
    for d in rows:
        n = re.sub(r"\s*\([^()]*\)\s*$", "", d["quantity"]).strip() or d["quantity"]
        names[n] = names.get(n, 0) + 1
    return max(names, key=lambda k: names[k]) if names else "값"


def _collect(topic: Path, quantity: str, unit: str | None) -> tuple[list[dict], str, int, list[str]]:
    try:
        rx = re.compile(quantity, re.IGNORECASE)
    except re.error as exc:
        raise VizError(f"--quantity is not a valid regular expression: {exc}") from exc
    records = load_records(topic)
    if not records:
        raise VizError(f"no evidence records under {topic}")
    matched, unparsed, unread = [], [], 0
    for stem, rec in records:
        label = derive_label(rec)["label"]
        for r in rec.get("results") or []:
            if not isinstance(r, dict) or not rx.search(str(r.get("quantity") or "")):
                continue
            matched.append((stem, rec, label, r))
    if not matched:
        raise VizError(f"no results match quantity /{quantity}/ in {len(records)} evidence records")
    units: dict[str, list[str]] = {}
    for _, _, _, r in matched:
        units.setdefault(norm_unit(r.get("unit") or ""), []).append(str(r.get("unit") or "(none)"))
    found = ", ".join(f"{v[0]} ({len(v)})" for v in units.values())
    if unit is not None:
        want = norm_unit(unit)
        matched = [m for m in matched if norm_unit(m[3].get("unit") or "") == want]
        if not matched:
            raise VizError(f"no /{quantity}/ results in unit {unit!r}; units found: {found}")
    elif len(units) > 1:
        raise VizError(f"mixed units for /{quantity}/: {found}. Pass --unit to choose one.")
    unit_shown = str(matched[0][3].get("unit") or "")

    rows = []
    for stem, rec, label, r in matched:
        lab = result_label(label, r)
        if lab == LABEL_NONE:
            unread += 1
            continue
        parsed = parse_value(r)
        if parsed is None:
            unparsed.append(f"{stem}:{r.get('id') or '?'}")
            continue
        value, lo, hi = parsed
        page = r.get("pdf_page")
        yr = year_of(rec, stem)
        rows.append({
            "study": study_label(rec, stem), "record": stem, "id": r.get("id") or "",
            "year": int(yr) if yr.isdigit() else 9999,
            "quantity": str(r.get("quantity") or ""), "value": value, "lo": lo, "hi": hi,
            "printed": str(r.get("value")), "unit": str(r.get("unit") or ""),
            "condition": str(r.get("condition") or "").strip() or "-",
            "page": "-" if page in (None, "") else str(page), "section": str(r.get("section") or "-"),
            "label": lab, "fill": fill_of(lab), "version": str(rec.get("version") or "-"), "design": design_of(rec),
            "range_printed": bool(RANGE_RE.match(str(r.get("value") or "").replace(",", ""))),
        })
    if not rows:
        raise VizError(f"all {len(matched)} matching results are unread (미확인) or unparsable")
    return rows, unit_shown, unread, unparsed


def build(topic: Path, quantity: str, unit: str | None = None, band: tuple[float, float] | None = None,
          band_label: str | None = None, sort: str = "year", title: str | None = None) -> tuple[dict, dict]:
    rows, unit_shown, unread, unparsed = _collect(topic, quantity, unit)
    qn = quantity_name(rows)
    blabel = (band_label or "기준").strip()
    sub = [f"{qn}{f' ({unit_shown})' if unit_shown else ''} · "
           f"{len({d['record'] for d in rows})}편에서 {len(rows)}개 값"]
    if band:
        lo, hi = sorted(band)
        sub.append(f"{sum(1 for d in rows if lo <= d['value'] <= hi)}개가 {blabel} 범위 안")
    designs = {d["design"] for d in rows}
    sub.append(("설계별, " if len(designs) > 1 else "") + ("값 순" if sort == "value" else "연도 순"))
    spec, info = row_chart(rows, unit=unit_shown, x_title=f"{qn} ({unit_shown})" if unit_shown else qn,
                           title=title or f"연구마다 {qn} 값은 얼마나 다른가?", subtitle=" · ".join(sub),
                           band=band, band_label=band_label, sort=sort, group_by="design", color="design")
    notes = []
    if unread:
        notes.append(f"미확인 {unread}건 생략")
    if unparsed:
        notes.append(f"값을 읽지 못한 {len(unparsed)}건 생략 ({', '.join(unparsed[:4])})")
    meta = {"points": info["points"], "studies": info["studies"], "notes": notes, "unit": unit_shown,
            "grouped": info["grouped"],
            "source": f"evidence/ {info['studies']}편의 results ({info['points']}개 값, quantity ~ /{quantity}/)"}
    return spec, meta
