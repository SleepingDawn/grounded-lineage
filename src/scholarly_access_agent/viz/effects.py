"""effects: dot-and-whisker of evidence `results` matching a quantity, across records."""
from __future__ import annotations

import re
from pathlib import Path

from scholarly_access_agent.evidence import LABEL_NONE, derive_label

from .common import (
    VizError,
    access_channel,
    access_key,
    design_of,
    design_scale,
    finish,
    load_records,
    result_label,
    study_label,
    year_of,
)

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
        return (a + b) / 2, lo if lo is not None else a, hi if hi is not None else b
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
    return "".join(num) + ("/" + "".join(den) if den else "")


def build(topic: Path, quantity: str, unit: str | None = None, band: tuple[float, float] | None = None,
          band_label: str | None = None, sort: str = "year") -> tuple[dict, dict]:
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

    rows, seen = [], {}
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
        study = study_label(rec, stem)
        cond = str(r.get("condition") or "").strip()
        row = study + (f" · {cond}" if cond else "")
        if len(row) > 34:
            row = row[:33] + "…"
        seen[row] = seen.get(row, 0) + 1
        if seen[row] > 1:
            row = f"{row} ({seen[row]})"
        page = r.get("pdf_page")
        rows.append({
            "row": row, "study": study, "record": stem, "id": r.get("id") or "",
            "year": int(year_of(rec, stem)) if year_of(rec, stem).isdigit() else 9999,
            "quantity": str(r.get("quantity") or ""), "value": value, "lo": lo, "hi": hi,
            "printed": str(r.get("value")), "unit": str(r.get("unit") or ""), "condition": cond or "-",
            "page": "-" if page in (None, "") else str(page), "section": str(r.get("section") or "-"),
            "label": lab, "version": str(rec.get("version") or "-"), "design": design_of(rec),
        })
    if not rows:
        raise VizError(f"all {len(matched)} matching results are unread (미확인) or unparsable")
    if sort == "value":
        rows.sort(key=lambda d: (d["value"], d["year"]))
    else:
        rows.sort(key=lambda d: (d["year"], d["value"]))
    order = [d["row"] for d in rows]
    y = {"field": "row", "type": "nominal", "sort": order, "title": None,
         "axis": {"labelLimit": {"expr": "containerSize()[0] < 520 ? 110 : 200"}, "labelFontSize": 11}}
    color = {"field": "design", "type": "nominal", "title": "연구 설계",
             "scale": design_scale(d["design"] for d in rows), "legend": {"columns": 2}}
    xt = {"title": f"값 ({unit_shown})" if unit_shown else "값", "scale": {"zero": False, "nice": True},
          "axis": {"tickCount": {"expr": "ceil(width / 70)"}}}
    layers = []
    if band:
        lo, hi = sorted(band)
        layers.append({
            "data": {"values": [{"lo": lo, "hi": hi, "mid": (lo + hi) / 2, "text": band_label or "기준 범위"}]},
            "layer": [
                {"mark": {"type": "rect", "color": "#56B4E9", "opacity": 0.18},
                 "encoding": {"x": {"field": "lo", "type": "quantitative", **xt}, "x2": {"field": "hi"}}},
                {"mark": {"type": "text", "baseline": "bottom", "dy": -3, "fontSize": 10, "color": "#59636e"},
                 "encoding": {"x": {"field": "mid", "type": "quantitative", **xt}, "y": {"value": 0},
                              "text": {"field": "text"}}},
            ],
        })
    tooltip = [{"field": "study", "title": "연구"}, {"field": "quantity", "title": "양"},
               {"field": "printed", "title": "값(인쇄)"}, {"field": "unit", "title": "단위"},
               {"field": "condition", "title": "조건"}, {"field": "page", "title": "PDF 쪽"},
               {"field": "section", "title": "위치"}, {"field": "label", "title": "확인 수준"},
               {"field": "version", "title": "판"}, {"field": "record", "title": "기록"}]
    layers.append({"transform": [{"filter": "isValid(datum.lo) && isValid(datum.hi)"}],
                   "mark": {"type": "rule", "strokeWidth": 1.6},
                   "encoding": {"y": y, "x": {"field": "lo", "type": "quantitative", **xt}, "x2": {"field": "hi"},
                                "color": color, "tooltip": tooltip}})
    layers.append({"mark": {"type": "point", "shape": "circle", "filled": True, "opacity": 1, "size": 80,
                            "strokeWidth": 1.8},
                   "encoding": {"y": y, "x": {"field": "value", "type": "quantitative", **xt}, "color": color,
                                "stroke": color,
                                "fillOpacity": access_channel(d["label"] for d in rows),
                                "tooltip": tooltip}})
    spec = finish({
        "usermeta": {"access_key": access_key(d["label"] for d in rows)},
        "width": "container", "height": 26 * len(order), "autosize": {"type": "fit-x", "contain": "padding"},
        "data": {"values": rows},
        "layer": layers,
    })
    studies = len({d["record"] for d in rows})
    notes = []
    if unread:
        notes.append(f"미확인 {unread}건 생략")
    if unparsed:
        notes.append(f"값을 읽지 못한 {len(unparsed)}건 생략 ({', '.join(unparsed[:4])})")
    meta = {"points": len(rows), "studies": studies, "notes": notes, "unit": unit_shown,
            "source": f"evidence/ {studies}편의 results ({len(rows)}개 값, quantity ~ /{quantity}/)"}
    return spec, meta
