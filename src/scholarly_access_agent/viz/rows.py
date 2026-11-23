"""Row charts: one row per value (forest, dot, bar) or per group (strip), with a label column at the left and a
value column at the right. Shared by `viz effects` and `viz figure`.

Rows are dicts made by effects._collect or figure.resolve_rows: study, condition, record, id, year, value, lo, hi,
printed, unit, page, section, label (read depth), fill (full/half/hollow), version, design, range_printed, and
optionally group, line1 / line2 (the two label lines), computed (bool) and how (tooltip text for computed rows).

Layout: y is drawn without a scale (the value is the pixel position), so rows keep their heights at every width.
Wide: label column, the mark on the same line, the value column at the right. Narrow (container < NARROW px): label
line 1 with the value at the right, label line 2, the mark full-width on line 3. Both layouts are in the spec; the
page picks one from its width (usermeta.rows) before each render.
"""
from __future__ import annotations

import math

from .common import (
    DESIGNS,
    LIGHT,
    UNKNOWN_DESIGN,
    VizError,
    access_legend,
    finish,
)

ROW_H, ROW_HN = 42, 62
HEAD_H = 30          # a group header
TOP = 26             # strip above the first row: column heads and the reference-band label
LABEL_W, VALUE_W = 220, 76
NARROW = 560
DOT = 160            # point area (px^2), r ~ 7
HALF_PATH = "M0,-1A1,1,0,0,0,0,1Z"       # left half-disc in Vega's unit box
HALF_SIZE = round(DOT * 4 / math.pi)     # a custom path spans sqrt(size)/2 per unit: match the circle's radius
CLIP_REACH = 0.5     # a whisker may run this fraction of the points' span past them before it is cut with an arrow
BAR_H = 16
MARKS = ("forest", "dot", "bar", "strip")
FILL_OPACITY = {"full": 1, "half": 0.45, "hollow": 0}   # bars: the read depth as fill strength


def decimals_for(span: float) -> int:
    """Decimals that resolve about a hundredth of the axis span: span 1.2 -> 2, span 12 -> 1, span 120 -> 0."""
    if span <= 0:
        return 2
    return max(0, min(3, 1 - math.floor(math.log10(span)) + 1))


def axis_domain(rows: list[dict], band: tuple[float, float] | None, zero: bool = False) -> tuple[list[float], float, float]:
    """(domain, allowed lo, allowed hi). Every point and the band are inside (and 0 for bars); a whisker is inside
    unless it runs more than CLIP_REACH x the core span past it, in which case it is cut at the allowed edge and
    drawn with an arrow."""
    core = [d["value"] for d in rows] + (list(band) if band else []) + ([0.0] if zero else [])
    lo, hi = min(core), max(core)
    span = hi - lo or abs(hi) * 0.2 or 1.0
    allow_lo, allow_hi = lo - CLIP_REACH * span, hi + CLIP_REACH * span
    ends_lo = [max(d["lo"], allow_lo) for d in rows if d.get("lo") is not None]
    ends_hi = [min(d["hi"], allow_hi) for d in rows if d.get("hi") is not None]
    ext_lo, ext_hi = min([lo] + ends_lo), max([hi] + ends_hi)
    pad = (ext_hi - ext_lo or span) * 0.06
    lo_d, hi_d = ext_lo - pad, ext_hi + pad
    if zero and ext_lo >= 0:
        lo_d = 0.0
    if zero and ext_hi <= 0:
        hi_d = 0.0
    return [lo_d, hi_d], allow_lo, allow_hi


def _groups(rows: list[dict], group_by: str | None) -> list[str]:
    if group_by == "design":
        order = [d[1] for d in DESIGNS + [UNKNOWN_DESIGN]]
        return [g for g in order if any(d["design"] == g for d in rows)]
    if group_by:
        return list(dict.fromkeys(str(d.get(group_by) or "기타") for d in rows))
    return [""]


def _key(group_by: str | None):
    return (lambda d: d["design"]) if group_by == "design" else \
        (lambda d: str(d.get(group_by) or "기타")) if group_by else (lambda d: "")


def layout(rows: list[dict], sort: str, group_by: str | None = "design", strip: bool = False):
    """Order rows into groups (design: fixed design order; another field: first appearance) and sort inside a
    group (year, value or as given). Gives every row a pixel centre for both layouts, `y` (wide) and `yn` (narrow).

    Returns (ordered rows, label rows, group headers, separators, {"wide": h, "narrow": h}, grouped)."""
    keyf = {"value": lambda d: (d["value"], d["year"]), "year": lambda d: (d["year"], d["value"])}.get(sort)
    gkey = _key(group_by)
    present = _groups(rows, group_by)
    grouped = len(present) > 1 and not strip
    ordered, labels, headers, seps = [], [], [], []
    y = yn = TOP
    for gi, g in enumerate(present):
        members = [d for d in rows if gkey(d) == g]
        if keyf:
            members.sort(key=keyf)
        if strip:
            if gi:
                seps.append({"y": y, "yn": yn, "kind": "row"})
            cy, cyn = y + ROW_H / 2, yn + ROW_HN / 2
            for i, d in enumerate(members):  # small alternating offsets so equal values stay visible
                off = 0 if len(members) == 1 else (-6 if i % 2 == 0 else 6) * (1 if i % 4 < 2 else 0.4)
                d["y"], d["yn"] = cy + off, cyn + off
                ordered.append(d)
            labels.append({"y": cy, "yn": cyn, "line1": g or "값", "line2": f"{len(members)}개 값", "group": g,
                           "_members": members})
            y, yn = y + ROW_H, yn + ROW_HN
            continue
        if grouped:
            if headers:
                seps.append({"y": y, "yn": yn, "kind": "group"})
            headers.append({"group": g, "y": y + HEAD_H / 2 + 3, "yn": yn + HEAD_H / 2 + 3,
                            "text": f"{g} · {len(members)}개 값", "n": len(members)})
            y, yn = y + HEAD_H, yn + HEAD_H
        for i, d in enumerate(members):
            if i:
                seps.append({"y": y, "yn": yn, "kind": "row"})
            d["y"], d["yn"] = y + ROW_H / 2, yn + ROW_HN / 2
            ordered.append(d)
            labels.append(d)
            y, yn = y + ROW_H, yn + ROW_HN
    return ordered, labels, headers, seps, {"wide": int(y) + 2, "narrow": int(yn) + 2}, grouped


def at_y(wide: float, narrow: float, field: str = "y", name: str = "py") -> tuple[list[dict], dict]:
    """(transform, y encoding) placing a mark `wide` px from the row centre in the wide layout and `narrow` px from
    it in the narrow one."""
    calc = f"narrow ? datum.{field}n + ({narrow}) : datum.{field} + ({wide})"
    return [{"calculate": calc, "as": name}], {"field": name, "type": "quantitative", "scale": None, "axis": None}


def category_colors(values: list[str]) -> dict[str, str]:
    """Fixed-order categorical colours: design labels keep their design colour, anything else takes the
    Okabe-Ito slots in order of appearance; past the five slots it folds to the neutral grey."""
    design = {label: c for _, label, c in DESIGNS + [UNKNOWN_DESIGN]}
    if all(v in design for v in values):
        return {v: design[v] for v in values}
    slots = [c for _, _, c in DESIGNS]
    return {v: slots[i] if i < len(slots) else UNKNOWN_DESIGN[2] for i, v in enumerate(values)}


def tooltip_fields(rows: list[dict]) -> list[dict]:
    tip = [{"field": "study", "title": "연구"}, {"field": "condition", "title": "조건"},
           {"field": "shown", "title": "값"}, {"field": "printed", "title": "기록된 값"},
           {"field": "page", "title": "PDF 쪽"}, {"field": "section", "title": "위치"},
           {"field": "label", "title": "읽은 범위"}, {"field": "version", "title": "판"},
           {"field": "design", "title": "설계"}, {"field": "source", "title": "근거"}]
    if any(d.get("computed") for d in rows):
        tip.insert(3, {"field": "how", "title": "계산"})
    return tip


def row_chart(rows: list[dict], *, unit: str, x_title: str, title: str, subtitle: str, mark: str = "forest",
              band: tuple[float, float] | None = None, band_label: str | None = None, sort: str = "year",
              group_by: str | None = "design", color: str = "design", color_title: str | None = None,
              zero: bool = False) -> tuple[dict, dict]:
    if mark not in MARKS:
        raise VizError(f"unknown row-chart mark {mark!r}")
    if not rows:
        raise VizError("no rows to draw")
    band = tuple(sorted(band)) if band else None
    blabel = (band_label or "기준").strip()
    strip, bar = mark == "strip", mark == "bar"
    zero = zero or bar
    domain, allow_lo, allow_hi = axis_domain(rows, band, zero=zero)
    span = domain[1] - domain[0]
    dec = decimals_for(span)
    ordered, labels, headers, seps, heights, grouped = layout(rows, sort, group_by, strip)
    pct = unit.strip() == "%"

    def fmt(x: float) -> str:
        return f"{x:.{dec}f}" + ("%" if pct else "")

    for d in ordered:
        d["lo_draw"] = None if d.get("lo") is None else max(d["lo"], allow_lo)
        d["hi_draw"] = None if d.get("hi") is None else min(d["hi"], allow_hi)
        d["clip_lo"] = d.get("lo") is not None and d["lo"] < allow_lo
        d["clip_hi"] = d.get("hi") is not None and d["hi"] > allow_hi
        # a whisker shorter than about the dot itself gets no caps (they would only blot the dot)
        d["caps"] = (d["lo_draw"] is not None and d["hi_draw"] is not None
                     and (d["hi_draw"] - d["lo_draw"]) / span > 0.03 and mark != "dot")
        if d.get("range_printed") and d.get("lo") is not None and d.get("hi") is not None:
            d["value_text"] = f"{fmt(d['lo'])[:-1] if pct else fmt(d['lo'])}–{fmt(d['hi'])}"
        else:
            d["value_text"] = ("≈" if d.get("computed") else "") + fmt(d["value"])
        rng = "" if d.get("lo") is None or d.get("hi") is None else f" [{fmt(d['lo'])}, {fmt(d['hi'])}]"
        d["shown"] = f"{fmt(d['value'])}{rng}{'' if pct else ' ' + unit}".strip()
        d.setdefault("line1", d["study"])
        d.setdefault("line2", d["condition"])
        d.setdefault("source", f"evidence/{d['record']}.json#{d['id']}")
        d["bar_opacity"] = FILL_OPACITY[d["fill"]]
    for lab in labels:
        if "_members" in lab:
            vals = [m["value"] for m in lab.pop("_members")]
            lab["value_text"] = fmt(vals[0]) if len(vals) == 1 else f"{fmt(min(vals))[:-1] if pct else fmt(min(vals))}–{fmt(max(vals))}"

    # ---- colour
    legend: list[dict] = []
    if color in ("access", "none"):
        const = LIGHT["fg"] if color == "access" else LIGHT["d_model"]
        color_enc: dict = {"value": const}
    else:
        field = "design" if color == "design" else color
        values = list(dict.fromkeys(str(d.get(field) or "기타") for d in ordered))
        if field == "design":
            order = [x[1] for x in DESIGNS + [UNKNOWN_DESIGN]]
            values = [v for v in order if v in values]
        for d in ordered:
            d["_color"] = str(d.get(field) or "기타")
        colors = category_colors(values)
        color_enc = {"field": "_color", "type": "nominal", "legend": None,
                     "scale": {"domain": values, "range": [colors[v] for v in values]}}
        legend.append({"title": color_title or ("연구 설계" if field == "design" else None),
                       "items": [{"label": v, "swatch": "dot", "color": colors[v]} for v in values]})
    legend.append({"title": "읽은 범위", "items": access_legend(d["label"] for d in ordered)})

    # ---- encodings
    xs = {"type": "quantitative", "scale": {"domain": domain, "nice": False, "zero": False}}
    x_axis = {"title": x_title, "orient": "bottom", "grid": True, "gridColor": LIGHT["rule"], "domain": False,
              "ticks": False, "labelPadding": 6, "titlePadding": 8, "labelFlush": True,
              "tickCount": {"expr": "max(3, floor(width / 90))"},
              "format": f".{min(dec, 2)}~f"}
    tooltip = tooltip_fields(ordered)
    left, right = {"expr": "-labelW"}, {"expr": "width + valueW"}
    wide_only = {"expr": "narrow ? 0 : 1"}
    mark_t, mark_y = at_y(0, 17)
    study_t, study_y = at_y(-8, -18)
    cond_t, cond_y = at_y(9, 0)
    value_t, value_y = at_y(0, -18)
    head_t, head_y = at_y(0, 0)

    layers: list[dict] = [
        # an invisible point at each domain end carries the x axis; the column heads sit in the top strip
        {"data": {"values": [{"x": domain[0]}, {"x": domain[1]}]},
         "mark": {"type": "point", "opacity": 0, "y": 0},
         "encoding": {"x": {"field": "x", **xs, "axis": x_axis}}},
        {"data": {"values": [{"t": "구분" if strip else "연구 · 조건"}]},
         "mark": {"type": "text", "align": "left", "baseline": "alphabetic", "x": left, "y": TOP - 9,
                  "fontWeight": 500, "fontSize": 12, "color": LIGHT["muted"], "opacity": wide_only},
         "encoding": {"text": {"field": "t"}}},
        {"data": {"values": [{"t": "범위" if strip else "값"}]},
         "mark": {"type": "text", "align": "right", "baseline": "alphabetic", "x": right, "y": TOP - 9,
                  "fontWeight": 500, "fontSize": 12, "color": LIGHT["muted"], "opacity": wide_only},
         "encoding": {"text": {"field": "t"}}},
    ]
    if zero:  # the no-effect / baseline line
        layers.append({"data": {"values": [{"x": 0}]},
                       "mark": {"type": "rule", "color": LIGHT["grid"], "strokeWidth": 1, "y": TOP - 4,
                                "y2": {"expr": "height"}},
                       "encoding": {"x": {"field": "x", **xs}}})
    if band:
        blo, bhi = band
        text = f"{blabel} {fmt(blo)}–{fmt(bhi)}{'' if pct else ' ' + unit}".strip()
        where = ((blo + bhi) / 2 - domain[0]) / span
        align, at = ("left", blo) if where < 0.3 else ("right", bhi) if where > 0.7 else ("center", (blo + bhi) / 2)
        # wide: one shaded column behind all rows; narrow: a strip behind each mark line, so the band does not
        # run under the labels
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
        strip_rows = [{"y": lab["y"], "yn": lab["yn"], "lo": blo, "hi": bhi} for lab in labels]
        layers.append({"data": {"values": strip_rows},
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

    # ---- label column, value column, hover rows
    label_tip = [] if strip else [{"tooltip": tooltip}]
    label_layers = [
        {"transform": study_t,
         "mark": {"type": "text", "align": "left", "baseline": "middle", "fontSize": 14, "fontWeight": 500,
                  "color": LIGHT["fg"], "x": left, "limit": {"expr": "narrow ? width - 70 : labelW - 12"}},
         "encoding": {"y": study_y, "text": {"field": "line1"}, **(label_tip[0] if label_tip else {})}},
        {"transform": cond_t,
         "mark": {"type": "text", "align": "left", "baseline": "middle", "fontSize": 12, "color": LIGHT["muted"],
                  "x": left, "limit": {"expr": "narrow ? width : labelW - 12"}},
         "encoding": {"y": cond_y, "text": {"field": "line2"}, **(label_tip[0] if label_tip else {})}},
        {"transform": value_t,
         "mark": {"type": "text", "align": "right", "baseline": "middle", "fontSize": 13.5, "fontWeight": 500,
                  "color": LIGHT["fg"], "x": right},
         "encoding": {"y": value_y, "text": {"field": "value_text"}, **(label_tip[0] if label_tip else {})}},
    ]
    if not strip:
        label_layers.insert(0, {
            "transform": [{"calculate": f"narrow ? datum.yn - {ROW_HN / 2 - 1} : datum.y - {ROW_H / 2 - 1}", "as": "top"},
                          {"calculate": f"narrow ? datum.yn + {ROW_HN / 2 - 1} : datum.y + {ROW_H / 2 - 1}",
                           "as": "bottom"}],
            "mark": {"type": "rect", "opacity": 0, "x": left, "x2": right},
            "encoding": {"y": {"field": "top", "type": "quantitative", "scale": None, "axis": None},
                         "y2": {"field": "bottom"}, "tooltip": tooltip}})
    layers.append({"data": {"values": labels}, "layer": label_layers})

    def on(extra: list[dict]) -> list[dict]:
        return extra + mark_t

    marks: list[dict] = []
    if bar:
        bar_t = [{"calculate": f"narrow ? datum.yn + 17 - {BAR_H / 2} : datum.y - {BAR_H / 2}", "as": "top"},
                 {"calculate": f"narrow ? datum.yn + 17 + {BAR_H / 2} : datum.y + {BAR_H / 2}", "as": "bottom"},
                 {"calculate": "0", "as": "zero"}]
        marks.append({"transform": bar_t,
                      "mark": {"type": "rect", "cornerRadius": 3, "strokeWidth": 1.6},
                      "encoding": {"x": {"field": "zero", **xs}, "x2": {"field": "value"},
                                   "y": {"field": "top", "type": "quantitative", "scale": None, "axis": None},
                                   "y2": {"field": "bottom"}, "color": color_enc, "stroke": color_enc,
                                   "fillOpacity": {"field": "bar_opacity", "type": "quantitative", "scale": None},
                                   "tooltip": tooltip}})
    whisker_ink = {"value": LIGHT["fg"]} if bar else color_enc
    if not strip:
        marks += [
            {"transform": on([{"filter": "isValid(datum.lo_draw) && isValid(datum.hi_draw)"}]),
             "mark": {"type": "rule", "strokeWidth": 1.5 if mark in ("dot", "bar") else 2.5, "strokeCap": "butt"},
             "encoding": {"y": mark_y, "x": {"field": "lo_draw", **xs}, "x2": {"field": "hi_draw"},
                          "color": whisker_ink, "tooltip": tooltip}},
            {"transform": on([{"filter": "datum.caps && !datum.clip_lo"}]),
             "mark": {"type": "tick", "orient": "vertical", "size": 12 if not bar else 9, "thickness": 2},
             "encoding": {"y": mark_y, "x": {"field": "lo_draw", **xs}, "color": whisker_ink}},
            {"transform": on([{"filter": "datum.caps && !datum.clip_hi"}]),
             "mark": {"type": "tick", "orient": "vertical", "size": 12 if not bar else 9, "thickness": 2},
             "encoding": {"y": mark_y, "x": {"field": "hi_draw", **xs}, "color": whisker_ink}},
            {"transform": on([{"filter": "datum.clip_lo"}]),
             "mark": {"type": "point", "shape": "triangle-left", "filled": True, "opacity": 1, "size": 110},
             "encoding": {"y": mark_y, "x": {"field": "lo_draw", **xs}, "color": whisker_ink, "tooltip": tooltip}},
            {"transform": on([{"filter": "datum.clip_hi"}]),
             "mark": {"type": "point", "shape": "triangle-right", "filled": True, "opacity": 1, "size": 110},
             "encoding": {"y": mark_y, "x": {"field": "hi_draw", **xs}, "color": whisker_ink, "tooltip": tooltip}},
        ]
    if not bar:
        # every dot: a surface-filled ring; then the full or half fill on top
        marks += [
            {"transform": mark_t,
             "mark": {"type": "point", "shape": "circle", "filled": False, "opacity": 1, "size": DOT,
                      "strokeWidth": 2.2, "fill": LIGHT["surface"], "fillOpacity": 1},
             "encoding": {"y": mark_y, "x": {"field": "value", **xs}, "stroke": color_enc, "tooltip": tooltip}},
            {"transform": on([{"filter": "datum.fill === 'full'"}]),
             "mark": {"type": "point", "shape": "circle", "filled": True, "opacity": 1, "size": DOT},
             "encoding": {"y": mark_y, "x": {"field": "value", **xs}, "color": color_enc, "tooltip": tooltip}},
            {"transform": on([{"filter": "datum.fill === 'half'"}]),
             "mark": {"type": "point", "shape": HALF_PATH, "filled": True, "opacity": 1, "size": HALF_SIZE},
             "encoding": {"y": mark_y, "x": {"field": "value", **xs}, "color": color_enc, "tooltip": tooltip}},
        ]
    layers.append({"layer": marks})

    extra = []
    if band:
        extra.append({"label": f"{blabel} 범위", "swatch": "band"})
    if any(d["clip_lo"] or d["clip_hi"] for d in ordered):
        extra.append({"label": "축 밖으로 이어지는 범위", "swatch": "arrow"})
    if any(d.get("computed") for d in ordered):
        extra.append({"label": "기록된 값에서 계산", "swatch": "approx"})
    if extra:
        legend.append({"items": extra})

    clean = [{k: v for k, v in d.items() if not k.startswith("_") or k == "_color"} for d in ordered]
    spec = finish({
        "usermeta": {"header": {"title": title, "subtitle": subtitle}, "legend": legend,
                     # the page sets height (and the narrow param) from its own width before each render
                     "rows": {"narrow_below": NARROW, "height": heights["wide"], "narrow_height": heights["narrow"]}},
        "params": [{"name": "narrow", "expr": f"containerSize()[0] < {NARROW}"},
                   {"name": "labelW", "expr": f"narrow ? 0 : {LABEL_W}"},
                   {"name": "valueW", "expr": f"narrow ? 0 : {VALUE_W}"}],
        "width": "container", "height": heights["wide"], "autosize": {"type": "fit-x", "contain": "padding"},
        "padding": {"left": 4, "right": 4, "top": 0, "bottom": 2},
        "data": {"values": clean},
        "layer": layers,
    })
    info = {"grouped": grouped, "studies": len({d["record"] for d in ordered}), "points": len(ordered),
            "inside_band": sum(1 for d in ordered if band and band[0] <= d["value"] <= band[1]) if band else None}
    return spec, info
