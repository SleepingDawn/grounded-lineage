"""effects: a forest plot of evidence `results` matching a quantity, across records.

Rows are grouped by study design (a small header per group when there is more than one design) and ordered by year
or value inside each group. Each row shows the study and its condition at the left, the value and its range as a dot
and capped whisker, and the value again in a column at the right. The point fill says how deeply the number was read
(full = 본문 확인, half = 발췌 확인, hollow = 초록만 / 인용 맥락만)."""
from __future__ import annotations

import math
import re
from pathlib import Path

from scholarly_access_agent.evidence import LABEL_NONE, derive_label

from .common import (
    DESIGNS,
    LIGHT,
    UNKNOWN_DESIGN,
    VizError,
    access_legend,
    design_of,
    design_scale,
    fill_of,
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

# Row geometry in px; y is drawn without a scale, so rows keep these heights at every width.
# Wide: study + condition in a left column, the dot on the same line, the value in a right column.
# Narrow (container < NARROW px): study and value on line 1, condition on line 2, the dot full-width on line 3.
ROW_H, ROW_HN = 42, 62
HEAD_H = 30         # a design-group header
TOP = 26            # strip above the first row: column heads and the reference-band label
LABEL_W, VALUE_W = 220, 76
NARROW = 560
DOT = 160           # point area (px^2), r ~ 7
HALF_PATH = "M0,-1A1,1,0,0,0,0,1Z"       # left half-disc in Vega's unit box
HALF_SIZE = round(DOT * 4 / math.pi)     # a custom path spans sqrt(size)/2 per unit: match the circle's radius
CLIP_REACH = 0.5    # a whisker may run this fraction of the points' span past them before it is cut with an arrow


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


def quantity_name(rows: list[dict]) -> str:
    """The most common quantity string without a trailing parenthetical: "kappa (GK)" -> "kappa"."""
    names: dict[str, int] = {}
    for d in rows:
        n = re.sub(r"\s*\([^()]*\)\s*$", "", d["quantity"]).strip() or d["quantity"]
        names[n] = names.get(n, 0) + 1
    return max(names, key=lambda k: names[k]) if names else "값"


def decimals_for(span: float) -> int:
    """Decimals that resolve about a hundredth of the axis span: span 1.2 -> 2, span 12 -> 1, span 120 -> 0."""
    if span <= 0:
        return 2
    return max(0, min(3, 1 - math.floor(math.log10(span)) + 1))


def axis_domain(rows: list[dict], band: tuple[float, float] | None) -> tuple[list[float], float, float]:
    """(domain, allowed lo, allowed hi). Every point and the band are inside; a whisker is inside unless it runs more
    than CLIP_REACH x the core span past it, in which case it is cut at the allowed edge and drawn with an arrow."""
    core = [d["value"] for d in rows] + (list(band) if band else [])
    lo, hi = min(core), max(core)
    span = hi - lo or abs(hi) * 0.2 or 1.0
    allow_lo, allow_hi = lo - CLIP_REACH * span, hi + CLIP_REACH * span
    ends_lo = [max(d["lo"], allow_lo) for d in rows if d["lo"] is not None]
    ends_hi = [min(d["hi"], allow_hi) for d in rows if d["hi"] is not None]
    ext_lo, ext_hi = min([lo] + ends_lo), max([hi] + ends_hi)
    pad = (ext_hi - ext_lo or span) * 0.06
    return [ext_lo - pad, ext_hi + pad], allow_lo, allow_hi


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


def layout(rows: list[dict], sort: str) -> tuple[list[dict], list[dict], list[dict], dict, bool]:
    """Order rows into design groups (fixed design order; year or value inside a group) and give each a pixel
    centre for both layouts: `y` (wide) and `yn` (narrow).

    Returns (ordered rows, group headers, separators, {"wide": height, "narrow": height}, grouped)."""
    design_order = [d[1] for d in DESIGNS + [UNKNOWN_DESIGN]]
    key = (lambda d: (d["value"], d["year"])) if sort == "value" else (lambda d: (d["year"], d["value"]))
    present = [g for g in design_order if any(d["design"] == g for d in rows)]
    grouped = len(present) > 1
    ordered, headers, seps = [], [], []
    y = yn = TOP
    for g in present:
        members = sorted((d for d in rows if d["design"] == g), key=key)
        if grouped:
            if headers:
                seps.append({"y": y, "yn": yn, "kind": "group"})
            headers.append({"design": g, "y": y + HEAD_H / 2 + 3, "yn": yn + HEAD_H / 2 + 3,
                            "text": f"{g} · {len(members)}개 값", "n": len(members)})
            y, yn = y + HEAD_H, yn + HEAD_H
        for i, d in enumerate(members):
            if i:
                seps.append({"y": y, "yn": yn, "kind": "row"})
            d["y"], d["yn"] = y + ROW_H / 2, yn + ROW_HN / 2
            ordered.append(d)
            y, yn = y + ROW_H, yn + ROW_HN
    return ordered, headers, seps, {"wide": int(y) + 2, "narrow": int(yn) + 2}, grouped


def at_y(wide: float, narrow: float, field: str = "y", name: str = "py") -> tuple[list[dict], dict]:
    """(transform, y encoding) placing a mark `wide` px from the row centre in the wide layout and `narrow` px from
    it in the narrow one. y has no scale: the value is the pixel position."""
    calc = f"narrow ? datum.{field}n + ({narrow}) : datum.{field} + ({wide})"
    return [{"calculate": calc, "as": name}], {"field": name, "type": "quantitative", "scale": None, "axis": None}


def build(topic: Path, quantity: str, unit: str | None = None, band: tuple[float, float] | None = None,
          band_label: str | None = None, sort: str = "year", title: str | None = None) -> tuple[dict, dict]:
    rows, unit_shown, unread, unparsed = _collect(topic, quantity, unit)
    band = tuple(sorted(band)) if band else None
    blabel = (band_label or "기준").strip()
    domain, allow_lo, allow_hi = axis_domain(rows, band)
    span = domain[1] - domain[0]
    dec = decimals_for(span)
    ordered, headers, seps, heights, grouped = layout(rows, sort)

    def fmt(x: float) -> str:
        return f"{x:.{dec}f}"

    for i, d in enumerate(ordered):
        d["order"] = i
        d["lo_draw"] = None if d["lo"] is None else max(d["lo"], allow_lo)
        d["hi_draw"] = None if d["hi"] is None else min(d["hi"], allow_hi)
        d["clip_lo"] = d["lo"] is not None and d["lo"] < allow_lo
        d["clip_hi"] = d["hi"] is not None and d["hi"] > allow_hi
        # a whisker shorter than about the dot itself gets no caps (they would only blot the dot)
        d["caps"] = d["lo_draw"] is not None and d["hi_draw"] is not None and (d["hi_draw"] - d["lo_draw"]) / span > 0.03
        if d["range_printed"] and d["lo"] is not None and d["hi"] is not None:
            d["value_text"] = f"{fmt(d['lo'])}–{fmt(d['hi'])}"
        else:
            d["value_text"] = fmt(d["value"])
        rng = "" if d["lo"] is None or d["hi"] is None else f" [{fmt(d['lo'])}, {fmt(d['hi'])}]"
        d["shown"] = f"{fmt(d['value'])}{rng} {unit_shown}".strip()

    qn = quantity_name(ordered)
    scale = design_scale(d["design"] for d in ordered)
    colors = dict(zip(scale["domain"], scale["range"]))

    # ---- encodings
    xs = {"type": "quantitative", "scale": {"domain": domain, "nice": False, "zero": False}}
    x_axis = {"title": f"{qn} ({unit_shown})" if unit_shown else qn, "orient": "bottom",
              "grid": True, "gridColor": LIGHT["rule"], "domain": False, "ticks": False,
              "labelPadding": 6, "titlePadding": 8, "labelFontSize": 12, "labelColor": LIGHT["muted"],
              "titleFontSize": 12.5, "titleFontWeight": 500, "titleColor": LIGHT["muted"],
              "tickCount": {"expr": "max(3, floor(width / 90))"}, "labelFlush": True,
              "format": f".{min(dec, 2)}~f"}
    color = {"field": "design", "type": "nominal", "scale": scale, "legend": None}
    tooltip = [{"field": "study", "title": "연구"}, {"field": "condition", "title": "조건"},
               {"field": "shown", "title": "값"}, {"field": "printed", "title": "인쇄된 값"},
               {"field": "page", "title": "PDF 쪽"}, {"field": "section", "title": "위치"},
               {"field": "label", "title": "읽은 범위"}, {"field": "version", "title": "판"},
               {"field": "design", "title": "설계"}, {"field": "record", "title": "기록"}]
    left = {"expr": "-labelW"}
    right = {"expr": "width + valueW"}
    wide_only = {"expr": "narrow ? 0 : 1"}
    mark_t, mark_y = at_y(0, 17)      # dot, whisker, caps, arrows
    study_t, study_y = at_y(-8, -18)
    cond_t, cond_y = at_y(9, 0)
    value_t, value_y = at_y(0, -18)
    head_t, head_y = at_y(0, 0)

    layers: list[dict] = [
        # an invisible point at each domain end carries the x axis; the column heads sit in the top strip
        {"data": {"values": [{"x": domain[0]}, {"x": domain[1]}]},
         "mark": {"type": "point", "opacity": 0, "y": 0},
         "encoding": {"x": {"field": "x", **xs, "axis": x_axis}}},
        {"data": {"values": [{"t": "연구 · 조건"}]},
         "mark": {"type": "text", "align": "left", "baseline": "alphabetic", "x": left, "y": TOP - 9,
                  "fontSize": 12, "fontWeight": 500, "color": LIGHT["muted"], "opacity": wide_only},
         "encoding": {"text": {"field": "t"}}},
        {"data": {"values": [{"t": "값"}]},
         "mark": {"type": "text", "align": "right", "baseline": "alphabetic", "x": right, "y": TOP - 9,
                  "fontSize": 12, "fontWeight": 500, "color": LIGHT["muted"], "opacity": wide_only},
         "encoding": {"text": {"field": "t"}}},
    ]
    if band:
        blo, bhi = band
        text = f"{blabel} {fmt(blo)}–{fmt(bhi)} {unit_shown}".strip()
        where = ((blo + bhi) / 2 - domain[0]) / span
        align, at = ("left", blo) if where < 0.3 else ("right", bhi) if where > 0.7 else ("center", (blo + bhi) / 2)
        # wide: one shaded column behind all rows; narrow: a strip behind each row's dot line, so the band does
        # not run under the study names
        edge = {"type": "rule", "color": LIGHT["band_edge"], "strokeWidth": 1, "y": TOP - 4, "y2": {"expr": "height"},
                "opacity": wide_only}
        layers.append({
            "data": {"values": [{"lo": blo, "hi": bhi, "at": at, "text": text}]},
            "layer": [
                {"mark": {"type": "rect", "color": LIGHT["band"], "y": TOP - 4, "y2": {"expr": "height"},
                          "opacity": wide_only},
                 "encoding": {"x": {"field": "lo", **xs}, "x2": {"field": "hi"}}},
                {"mark": edge, "encoding": {"x": {"field": "lo", **xs}}},
                {"mark": edge, "encoding": {"x": {"field": "hi", **xs}}},
                {"mark": {"type": "text", "align": align, "baseline": "alphabetic", "y": TOP - 9,
                          "fontSize": 12, "fontWeight": 600, "color": LIGHT["fg"],
                          "dx": {"left": 1, "right": -1, "center": 0}[align]},
                 "encoding": {"x": {"field": "at", **xs}, "text": {"field": "text"}}},
            ],
        })
        strip = [{"y": d["y"], "yn": d["yn"], "lo": blo, "hi": bhi} for d in ordered]
        layers.append({"data": {"values": strip},
                       # hidden when wide, but kept on the wide rows so it never stretches the wide view
                       "transform": [{"calculate": "narrow ? datum.yn + 4 : datum.y - 10", "as": "top"},
                                     {"calculate": "narrow ? datum.yn + 30 : datum.y + 10", "as": "bottom"}],
                       "mark": {"type": "rect", "color": LIGHT["band"], "opacity": {"expr": "narrow ? 1 : 0"}},
                       "encoding": {"x": {"field": "lo", **xs}, "x2": {"field": "hi"},
                                    "y": {"field": "top", "type": "quantitative", "scale": None, "axis": None},
                                    "y2": {"field": "bottom"}}})
    for kind, ink in (("row", LIGHT["rule"]), ("group", LIGHT["grid"])):
        these = [s for s in seps if s["kind"] == kind]
        if these:
            sep_t, sep_y = at_y(0, 0)
            layers.append({"data": {"values": these}, "transform": sep_t,
                           "mark": {"type": "rule", "x": left, "x2": right, "strokeWidth": 1, "color": ink},
                           "encoding": {"y": sep_y}})
    if headers:
        layers.append({"data": {"values": headers}, "transform": head_t,
                       "mark": {"type": "text", "align": "left", "baseline": "middle", "fontSize": 12.5,
                                "fontWeight": 700, "color": LIGHT["fg"], "x": left},
                       "encoding": {"y": head_y, "text": {"field": "text"}}})

    def on_row(t: list[dict], extra: list[dict] | None = None) -> list[dict]:
        return (extra or []) + t

    data_layers = [
        # the whole row is the hover target
        {"transform": [{"calculate": f"narrow ? datum.yn - {ROW_HN / 2 - 1} : datum.y - {ROW_H / 2 - 1}",
                        "as": "top"},
                       {"calculate": f"narrow ? datum.yn + {ROW_HN / 2 - 1} : datum.y + {ROW_H / 2 - 1}",
                        "as": "bottom"}],
         "mark": {"type": "rect", "opacity": 0, "x": left, "x2": right},
         "encoding": {"y": {"field": "top", "type": "quantitative", "scale": None, "axis": None},
                      "y2": {"field": "bottom"}, "tooltip": tooltip}},
        {"transform": study_t,
         "mark": {"type": "text", "align": "left", "baseline": "middle", "fontSize": 14, "fontWeight": 500,
                  "color": LIGHT["fg"], "x": left,
                  "limit": {"expr": "narrow ? width - 70 : labelW - 12"}},
         "encoding": {"y": study_y, "text": {"field": "study"}, "tooltip": tooltip}},
        {"transform": cond_t,
         "mark": {"type": "text", "align": "left", "baseline": "middle", "fontSize": 12, "color": LIGHT["muted"],
                  "x": left, "limit": {"expr": "narrow ? width : labelW - 12"}},
         "encoding": {"y": cond_y, "text": {"field": "condition"}, "tooltip": tooltip}},
        {"transform": on_row(mark_t, [{"filter": "isValid(datum.lo_draw) && isValid(datum.hi_draw)"}]),
         "mark": {"type": "rule", "strokeWidth": 2.5, "strokeCap": "butt"},
         "encoding": {"y": mark_y, "x": {"field": "lo_draw", **xs}, "x2": {"field": "hi_draw"}, "color": color,
                      "tooltip": tooltip}},
        {"transform": on_row(mark_t, [{"filter": "datum.caps && !datum.clip_lo"}]),
         "mark": {"type": "tick", "orient": "vertical", "size": 12, "thickness": 2.5},
         "encoding": {"y": mark_y, "x": {"field": "lo_draw", **xs}, "color": color}},
        {"transform": on_row(mark_t, [{"filter": "datum.caps && !datum.clip_hi"}]),
         "mark": {"type": "tick", "orient": "vertical", "size": 12, "thickness": 2.5},
         "encoding": {"y": mark_y, "x": {"field": "hi_draw", **xs}, "color": color}},
        {"transform": on_row(mark_t, [{"filter": "datum.clip_lo"}]),
         "mark": {"type": "point", "shape": "triangle-left", "filled": True, "opacity": 1, "size": 110},
         "encoding": {"y": mark_y, "x": {"field": "lo_draw", **xs}, "color": color, "tooltip": tooltip}},
        {"transform": on_row(mark_t, [{"filter": "datum.clip_hi"}]),
         "mark": {"type": "point", "shape": "triangle-right", "filled": True, "opacity": 1, "size": 110},
         "encoding": {"y": mark_y, "x": {"field": "hi_draw", **xs}, "color": color, "tooltip": tooltip}},
        # every dot: a surface-filled ring; then the full or half fill on top
        {"transform": mark_t,
         "mark": {"type": "point", "shape": "circle", "filled": False, "opacity": 1, "size": DOT, "strokeWidth": 2.2,
                  "fill": LIGHT["surface"], "fillOpacity": 1},
         "encoding": {"y": mark_y, "x": {"field": "value", **xs}, "stroke": color, "tooltip": tooltip}},
        {"transform": on_row(mark_t, [{"filter": "datum.fill === 'full'"}]),
         "mark": {"type": "point", "shape": "circle", "filled": True, "opacity": 1, "size": DOT},
         "encoding": {"y": mark_y, "x": {"field": "value", **xs}, "color": color, "tooltip": tooltip}},
        {"transform": on_row(mark_t, [{"filter": "datum.fill === 'half'"}]),
         "mark": {"type": "point", "shape": HALF_PATH, "filled": True, "opacity": 1, "size": HALF_SIZE},
         "encoding": {"y": mark_y, "x": {"field": "value", **xs}, "color": color, "tooltip": tooltip}},
        # the value column at the right (line 1 at the right edge when narrow)
        {"transform": value_t,
         "mark": {"type": "text", "align": "right", "baseline": "middle", "fontSize": 13.5, "fontWeight": 500,
                  "color": LIGHT["fg"], "x": right},
         "encoding": {"y": value_y, "text": {"field": "value_text"}, "tooltip": tooltip}},
    ]
    layers.append({"layer": data_layers})

    legend = [{"title": "연구 설계", "items": [{"label": g, "swatch": "dot", "color": colors[g]} for g in scale["domain"]]},
              {"title": "읽은 범위", "items": access_legend(d["label"] for d in ordered)}]
    extra = []
    if band:
        extra.append({"label": f"{blabel} 범위", "swatch": "band"})
    if any(d["clip_lo"] or d["clip_hi"] for d in ordered):
        extra.append({"label": "축 밖으로 이어지는 범위", "swatch": "arrow"})
    if extra:
        legend.append({"items": extra})

    studies = len({d["record"] for d in ordered})
    sub = [f"{qn}{f' ({unit_shown})' if unit_shown else ''} · {studies}편에서 {len(ordered)}개 값"]
    if band:
        inside = sum(1 for d in ordered if band[0] <= d["value"] <= band[1])
        sub.append(f"{inside}개가 {blabel} 범위 안")
    sub.append(("설계별, " if grouped else "") + ("값 순" if sort == "value" else "연도 순"))
    spec = finish({
        "usermeta": {"header": {"title": title or f"연구마다 {qn} 값은 얼마나 다른가?", "subtitle": " · ".join(sub)},
                     "legend": legend,
                     # the page sets height (and the narrow param) from its own width before each render
                     "rows": {"narrow_below": NARROW, "height": heights["wide"], "narrow_height": heights["narrow"]}},
        "params": [{"name": "narrow", "expr": f"containerSize()[0] < {NARROW}"},
                   {"name": "labelW", "expr": f"narrow ? 0 : {LABEL_W}"},
                   {"name": "valueW", "expr": f"narrow ? 0 : {VALUE_W}"}],
        "width": "container", "height": heights["wide"], "autosize": {"type": "fit-x", "contain": "padding"},
        "padding": {"left": 4, "right": 4, "top": 0, "bottom": 2},
        "data": {"values": ordered},
        "layer": layers,
    })
    notes = []
    if unread:
        notes.append(f"미확인 {unread}건 생략")
    if unparsed:
        notes.append(f"값을 읽지 못한 {len(unparsed)}건 생략 ({', '.join(unparsed[:4])})")
    meta = {"points": len(ordered), "studies": studies, "notes": notes, "unit": unit_shown, "grouped": grouped,
            "source": f"evidence/ {studies}편의 results ({len(ordered)}개 값, quantity ~ /{quantity}/)"}
    return spec, meta
