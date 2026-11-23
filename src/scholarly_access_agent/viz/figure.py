"""figure: a chart the report agent asks for, drawn only from numbers stored in evidence records.

  scholarly-access-agent viz figure TOPIC --spec figs/q1.fig.json [-o figs/q1.html]

The agent decides, per report question, whether a figure helps and which form; this tool guarantees where every
number comes from and how it looks. A spec (figs/<name>.fig.json):

  {"question": "Q1 정기권·무제한권은 이용을 얼마나 늘리나?",          -> subtitle
   "takeaway": "단기 효과는 +2.7~12%, 설계가 강할수록 작다",         -> title
   "form": "forest|dot|bar|line|stacked|scatter|strip",
   "x": {"title": "이용 변화", "unit": "%"}, "y": {"title": "...", "unit": "..."},
   "color": "design|access|none|<row field>", "sort": "given|value|year", "group_by": "group|design|none",
   "rows": [{"key": "bull2021", "result": "trips", "label": "Bull 2021 · 산티아고 RCT", "group": "실험"},
            {"computed": true, "op": "mean", "label": "Ziedan 2024 · 중간값",
             "inputs": [{"key": "ziedan2024", "result": "bus", "field": "lo"},
                        {"key": "ziedan2024", "result": "bus", "field": "hi"}]}],
   "band": {"lo": 1.3, "hi": 1.4, "label": "실험"}, "zero": true, "note": "..."}
  (zero: the value axis includes 0 and draws the no-effect line; bars always do)

Rules (each is an error):
- every row names an evidence record (`key` = evidence/<key>.json) and a stored result (`result` = its id;
  "id.lo" or `field` picks lo/hi); a row may not carry its own value, lo or hi
- except `computed: true` rows: their `inputs` must resolve the same way; with `op` (mean, min, max, sum, diff,
  ratio, pct_change) the tool computes the value and checks a given one; without `op` a given value is kept and
  its inputs are shown beside it
- units: each value axis takes `x.unit` (or `y.unit`); a result in another unit is refused; without a declared
  unit all rows must share one
Read depth (the evidence record's derived label) becomes the mark fill and is in the tooltip with the page;
미확인 results are left out and counted in the caption.

Forms: forest (dot + range), dot, bar (horizontal), strip (one line per group) share the row-chart renderer of
`viz effects`; line (x = record year, or `x_result`), stacked (rows with `bar` and `stack`), scatter (`x_result`
and `y_result` from one record per row). `"vegalite": {...}` draws a custom Vega-Lite spec whose data is only the
resolved rows (the tool injects them as data.values and applies the design-token config; `data`, `datasets` and
`url` keys inside are refused).
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from scholarly_access_agent.evidence import LABEL_ABSTRACT, LABEL_BODY, LABEL_EXCERPTS, LABEL_NONE, LABEL_SECONDARY, \
    derive_label

from .common import (
    DESIGNS,
    LIGHT,
    UNKNOWN_DESIGN,
    VizError,
    access_legend,
    base_config,
    design_of,
    fill_of,
    finish,
    load_records,
    result_label,
    study_label,
    year_of,
)
from .effects import RANGE_RE, norm_unit, parse_value
from .rows import DOT, HALF_PATH, HALF_SIZE, category_colors, row_chart, tooltip_fields

FORMS = ("forest", "dot", "bar", "line", "stacked", "scatter", "strip")
ROW_FORMS = ("forest", "dot", "bar", "strip")
OPS = {
    "mean": lambda v: sum(v) / len(v), "min": min, "max": max, "sum": sum,
    "diff": lambda v: v[0] - v[1], "ratio": lambda v: v[0] / v[1],
    "pct_change": lambda v: (v[1] - v[0]) / v[0] * 100,
}
DEPTH_RANK = {LABEL_BODY: 3, LABEL_EXCERPTS: 2, LABEL_SECONDARY: 1, LABEL_ABSTRACT: 1, LABEL_NONE: 0}
LITERALS = ("value", "lo", "hi")
SPEC_SUFFIX = ".fig.json"


class Problems(list):
    def add(self, rule: str, message: str, row: int | None = None, level: str = "error") -> None:
        self.append({"level": level, "rule": rule, "message": message, "row": row})

    @property
    def errors(self) -> list[dict]:
        return [p for p in self if p["level"] == "error"]


def _num(x: Any) -> float | None:
    if isinstance(x, bool) or x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    try:
        return float(str(x).replace(",", ""))
    except ValueError:
        return None


def value_axes(form: str) -> dict[str, str]:
    """Which spec axis holds the unit of each row value field."""
    if form == "line":
        return {"result": "y", "x_result": "x"}
    if form == "scatter":
        return {"x_result": "x", "y_result": "y"}
    return {"result": "x"}


class Resolver:
    def __init__(self, records: dict[str, dict]):
        self.records = records

    def result(self, key: Any, ref: Any, field: Any, problems: Problems, i: int | None):
        """(record, result, value, lo, hi, picked field) for key + result id ("id" or "id.lo"), or None."""
        if not isinstance(key, str) or not key:
            problems.add("missing_key", "row has no evidence key", i)
            return None
        rec = self.records.get(key)
        if rec is None:
            problems.add("unknown_key", f"no evidence/{key}.json", i)
            return None
        if not isinstance(ref, str) or not ref:
            problems.add("missing_result", f"{key}: row names no result id", i)
            return None
        rid, pick = ref, field
        res = next((r for r in rec.get("results") or [] if isinstance(r, dict) and str(r.get("id")) == rid), None)
        if res is None and "." in ref:
            rid, pick = ref.rsplit(".", 1)
            res = next((r for r in rec.get("results") or [] if isinstance(r, dict) and str(r.get("id")) == rid), None)
        if res is None:
            ids = ", ".join(str(r.get("id")) for r in rec.get("results") or [] if isinstance(r, dict)) or "none"
            problems.add("unknown_result", f"{key} has no result id {rid} (has: {ids})", i)
            return None
        parsed = parse_value(res)
        if parsed is None:
            problems.add("unparsable_value", f"{key}#{rid}: value {res.get('value')!r} is not a number or range", i)
            return None
        value, lo, hi = parsed
        pick = pick or "value"
        if pick not in LITERALS:
            problems.add("unknown_field", f"{key}#{rid}: field {pick!r} (use value, lo or hi)", i)
            return None
        if pick != "value":
            chosen = lo if pick == "lo" else hi
            if chosen is None:
                problems.add("unknown_field", f"{key}#{rid} has no {pick}", i)
                return None
            value, lo, hi = chosen, None, None
        return rec, res, value, lo, hi, pick


def _base_row(key: str, rec: dict, res: dict) -> dict:
    page = res.get("pdf_page")
    yr = year_of(rec, key)
    label = result_label(derive_label(rec)["label"], res)
    return {"study": study_label(rec, key), "record": key, "id": str(res.get("id") or ""),
            "year": int(yr) if yr.isdigit() else 9999, "quantity": str(res.get("quantity") or ""),
            "printed": str(res.get("value")), "unit": str(res.get("unit") or ""),
            "condition": str(res.get("condition") or "").strip() or "-",
            "page": "-" if page in (None, "") else str(page), "section": str(res.get("section") or "-"),
            "label": label, "fill": fill_of(label), "version": str(rec.get("version") or "-"),
            "design": design_of(rec), "range_printed": bool(RANGE_RE.match(str(res.get("value") or "").replace(",", ""))),
            "source": f"evidence/{key}.json#{res.get('id')}"}


def _labels(row: dict, out: dict) -> None:
    text = str(row.get("label") or "").strip()
    if text:
        first, _, second = text.partition(" · ")
        out["line1"] = first
        out["line2"] = second or out.get("condition", "-")
    out.setdefault("line1", out["study"])
    out.setdefault("line2", out.get("condition", "-"))
    for k in ("group", "bar", "stack", "series"):
        if row.get(k) not in (None, ""):
            out[k] = str(row[k])


def resolve_rows(spec: dict, records: dict[str, dict]) -> tuple[list[dict], Problems, dict]:
    """Rows with their numbers taken from evidence records. Returns (rows, problems, info); info has the unit of
    each axis and the number of 미확인 results left out."""
    problems = Problems()
    form = spec.get("form") or ("custom" if "vegalite" in spec else "")
    if form not in FORMS and form != "custom":
        problems.add("unknown_form", f"form {form!r}: use one of {', '.join(FORMS)} (or a vegalite block)")
    raw_rows = spec.get("rows")
    if not isinstance(raw_rows, list) or not raw_rows:
        problems.add("no_rows", "spec has no rows")
        return [], problems, {"units": {}, "unread": 0}
    axes = value_axes(form)
    declared = {ax: str((spec.get(ax) or {}).get("unit") or "") for ax in ("x", "y")}
    seen_units: dict[str, list[tuple[str, int]]] = {"x": [], "y": []}
    resolver = Resolver(records)
    out, unread = [], 0

    def check_unit(axis: str, unit: str, i: int, where: str) -> bool:
        want = declared[axis]
        if want and norm_unit(unit) != norm_unit(want):
            problems.add("unit_mismatch", f"{where}: unit {unit or '(none)'!r} but {axis}.unit is {want!r}", i)
            return False
        seen_units[axis].append((unit, i))
        return True

    for i, row in enumerate(raw_rows):
        if not isinstance(row, dict):
            problems.add("bad_row", "row is not an object", i)
            continue
        if row.get("computed"):
            inputs = row.get("inputs")
            if not isinstance(inputs, list) or not inputs:
                problems.add("computed_without_inputs", "computed row needs `inputs` that name stored results", i)
                continue
            got = [resolver.result(inp.get("key") if isinstance(inp, dict) else None,
                                   inp.get("result") if isinstance(inp, dict) else None,
                                   inp.get("field") if isinstance(inp, dict) else None, problems, i)
                   for inp in inputs]
            if any(g is None for g in got):
                continue
            units = {norm_unit(g[1].get("unit") or "") for g in got}
            if len(units) > 1:
                problems.add("unit_mismatch", "computed row mixes units: "
                             + ", ".join(sorted({str(g[1].get('unit')) for g in got})), i)
                continue
            vals = [g[2] for g in got]
            op = row.get("op")
            given = _num(row.get("value"))
            if op is not None and op not in OPS:
                problems.add("unknown_op", f"op {op!r}: use one of {', '.join(OPS)}", i)
                continue
            if op is not None:
                try:
                    value = round(OPS[op](vals), 10)
                except (ZeroDivisionError, IndexError):
                    problems.add("bad_op", f"{op} cannot be computed from {vals}", i)
                    continue
                if given is not None and abs(given - value) > max(1e-9, 1e-3 * abs(value)):
                    problems.add("computed_mismatch", f"value {given} but {op} of the inputs is {value:g}", i)
                    continue
            elif given is None:
                problems.add("computed_without_value", "computed row needs `op` or a `value`", i)
                continue
            else:
                value = given
            first = got[0]
            base = _base_row(inputs[0]["key"], first[0], first[1])
            depth = min((result_label(derive_label(g[0])["label"], g[1]) for g in got), key=lambda lab: DEPTH_RANK[lab])
            refs = [f"{inp['key']}#{g[1].get('id')}{'' if g[5] == 'value' else '.' + g[5]}" for inp, g in zip(inputs, got)]
            how = (f"{op}(" if op else "") + ", ".join(f"{r} = {v:g}" for r, v in zip(refs, vals)) + (")" if op else "")
            base.update({"id": "computed", "value": value, "lo": _num(row.get("lo")), "hi": _num(row.get("hi")),
                         "printed": f"{value:g}", "label": depth, "fill": fill_of(depth), "computed": True,
                         "how": how, "range_printed": False, "source": "; ".join(f"evidence/{r}" for r in refs)})
            if depth == LABEL_NONE:
                unread += 1
                continue
            axis = axes.get("result", "x")
            if not check_unit(axis, str(first[1].get("unit") or ""), i, f"{inputs[0]['key']} (computed)"):
                continue
            _labels(row, base)
            out.append(base)
            continue
        literal = [k for k in LITERALS if k in row]
        if literal:
            problems.add("literal_number", f"row gives {', '.join(literal)} itself; cite a stored result "
                         "(or mark it computed with inputs)", i)
            continue
        key = row.get("key")
        fields = [f for f in axes if f in row] or (["result"] if "result" in axes else [])
        if form in ("scatter",) and not all(f in row for f in ("x_result", "y_result")):
            problems.add("missing_result", "scatter rows need x_result and y_result", i)
            continue
        got = {}
        for f in fields:
            g = resolver.result(key, row.get(f), row.get("field") if f == "result" else None, problems, i)
            if g is None:
                break
            got[f] = g
        if len(got) != len(fields) or not got:
            continue
        main = got.get("result") or got.get("y_result")
        base = _base_row(key, main[0], main[1])
        if base["label"] == LABEL_NONE:
            unread += 1
            continue
        ok = True
        for f, g in got.items():
            ok &= check_unit(axes[f], str(g[1].get("unit") or ""), i, f"{key}#{g[1].get('id')}")
        if not ok:
            continue
        base.update({"value": main[2], "lo": main[3], "hi": main[4]})
        if main[5] != "value":
            base["range_printed"] = False
        if "x_result" in got:
            base["x"] = got["x_result"][2]
            base["x_source"] = f"evidence/{key}.json#{got['x_result'][1].get('id')}"
        if form == "scatter":
            base["y"] = got["y_result"][2]
        _labels(row, base)
        out.append(base)
    units = {}
    for axis, seen in seen_units.items():
        names = {norm_unit(u): u for u, _ in seen}
        if len(names) > 1 and not declared[axis]:
            problems.add("mixed_units", f"{axis} values come in several units ({', '.join(names.values())}); "
                         f"declare {axis}.unit")
        units[axis] = declared[axis] or (next(iter(names.values())) if names else "")
    return out, problems, {"units": units, "unread": unread}


# ---------------------------------------------------------------- forms other than the row charts

def _dots(x: dict, y: dict, color_enc: dict, tooltip: list[dict]) -> list[dict]:
    """Ring + full / half fill: the read-depth point used in every chart."""
    return [
        {"mark": {"type": "point", "shape": "circle", "filled": False, "opacity": 1, "size": DOT, "strokeWidth": 2.2,
                  "fill": LIGHT["surface"], "fillOpacity": 1},
         "encoding": {"x": x, "y": y, "stroke": color_enc, "tooltip": tooltip}},
        {"transform": [{"filter": "datum.fill === 'full'"}],
         "mark": {"type": "point", "shape": "circle", "filled": True, "opacity": 1, "size": DOT},
         "encoding": {"x": x, "y": y, "color": color_enc, "tooltip": tooltip}},
        {"transform": [{"filter": "datum.fill === 'half'"}],
         "mark": {"type": "point", "shape": HALF_PATH, "filled": True, "opacity": 1, "size": HALF_SIZE},
         "encoding": {"x": x, "y": y, "color": color_enc, "tooltip": tooltip}},
    ]


def _color(rows: list[dict], field: str, default: str) -> tuple[dict, list[dict]]:
    """(color encoding, legend items) for a categorical field; access/none give one colour and no items."""
    field = field or default
    if field in ("access", "none"):
        return {"value": LIGHT["fg"] if field == "access" else LIGHT["d_model"]}, []
    values = list(dict.fromkeys(str(d.get(field) or "기타") for d in rows))
    if field == "design":
        order = [x[1] for x in DESIGNS + [UNKNOWN_DESIGN]]
        values = [v for v in order if v in values]
    for d in rows:
        d["_c"] = str(d.get(field) or "기타")
    colors = category_colors(values)
    enc = {"field": "_c", "type": "nominal", "legend": None,
           "scale": {"domain": values, "range": [colors[v] for v in values]}}
    return enc, [{"label": v, "swatch": "dot", "color": colors[v]} for v in values]


def _axis_title(spec: dict, axis: str, unit: str, fallback: str) -> str:
    t = str((spec.get(axis) or {}).get("title") or fallback)
    return f"{t} ({unit})" if unit and f"({unit})" not in t else t


def line_chart(spec: dict, rows: list[dict], units: dict) -> dict:
    by_year = all("x" not in d for d in rows)
    for d in rows:
        d["xv"] = d["year"] if by_year else d["x"]
        d.setdefault("series", d.get("group") or d.get("line1") or d["study"])
    color_field = spec.get("color") or "series"
    color_enc, items = _color(rows, color_field, "series")
    xq = {"field": "xv", "type": "quantitative",
          "title": "연도" if by_year else _axis_title(spec, "x", units["x"], "x"),
          "scale": {"zero": False, "nice": not by_year, "padding": 16},
          "axis": {"format": "d" if by_year else "~g", "tickCount": {"expr": "max(3, floor(width / 90))"},
                   "grid": False, "labelFlush": True}}
    yq = {"field": "value", "type": "quantitative", "title": _axis_title(spec, "y", units["y"], "값"),
          "scale": {"zero": bool(spec.get("zero", False)), "nice": True, "padding": 12},
          "axis": {"grid": True, "tickCount": 5, "domain": False, "ticks": False, "titlePadding": 10}}
    tip = tooltip_fields(rows) + [{"field": "xv", "title": "x"}]
    series_key = "_c" if color_enc.get("field") else "series"
    layers = [{"mark": {"type": "line", "strokeWidth": 2, "interpolate": "linear"},
               "encoding": {"x": xq, "y": yq, "color": color_enc, "detail": {"field": series_key},
                            "order": {"field": "xv"}}}]
    layers += _dots(xq, yq, color_enc, tip)
    # direct label at each series' last point
    layers.append({"transform": [{"joinaggregate": [{"op": "max", "field": "xv", "as": "_last"}],
                                  "groupby": [series_key]},
                                 {"filter": "datum.xv === datum._last"}],
                   "mark": {"type": "text", "align": "left", "dx": 10, "fontSize": 12.5, "color": LIGHT["fg"]},
                   "encoding": {"x": xq, "y": yq, "text": {"field": series_key}}})
    return {"usermeta": {"legend": ([{"title": None, "items": [dict(i, swatch="line") for i in items]}] if items else [])
                         + [{"title": "읽은 범위", "items": access_legend(d["label"] for d in rows)}]},
            "width": "container", "height": 300, "autosize": {"type": "fit-x", "contain": "padding"},
            "padding": {"left": 4, "right": 90, "top": 8, "bottom": 4},
            "data": {"values": rows}, "layer": layers}


def stacked_chart(spec: dict, rows: list[dict], units: dict) -> dict:
    for d in rows:
        d.setdefault("bar", d.get("line1") or d["study"])
        d.setdefault("stack", d.get("group") or d.get("line2") or "값")
    bars = list(dict.fromkeys(d["bar"] for d in rows))
    color_enc, items = _color(rows, spec.get("color") or "stack", "stack")
    tip = tooltip_fields(rows) + [{"field": "stack", "title": "구성"}]
    return {"usermeta": {"legend": [{"title": None, "items": [dict(i, swatch="square") for i in items]},
                                    {"title": "읽은 범위", "items": access_legend(d["label"] for d in rows)}]},
            "width": "container", "height": max(80, 36 * len(bars)), "autosize": {"type": "fit-x", "contain": "padding"},
            "data": {"values": rows},
            "mark": {"type": "bar", "size": 20, "stroke": LIGHT["surface"], "strokeWidth": 2},
            "encoding": {"y": {"field": "bar", "type": "nominal", "sort": bars, "title": None,
                               "axis": {"labelFontSize": 13, "labelColor": LIGHT["fg"], "labelLimit": 220,
                                        "domain": False, "ticks": False, "labelPadding": 8}},
                         "x": {"field": "value", "type": "quantitative", "stack": "zero",
                               "title": _axis_title(spec, "x", units["x"], "값"),
                               "axis": {"grid": True, "domain": False, "ticks": False,
                                        "tickCount": {"expr": "max(3, floor(width / 90))"}}},
                         "color": color_enc, "order": {"field": "_order"},
                         "fillOpacity": {"field": "_op", "type": "quantitative", "scale": None},
                         "tooltip": tip},
            "transform": [{"calculate": "datum.fill === 'full' ? 1 : datum.fill === 'half' ? 0.6 : 0.3", "as": "_op"},
                          {"window": [{"op": "row_number", "as": "_order"}]}]}


def scatter_chart(spec: dict, rows: list[dict], units: dict) -> dict:
    color_enc, items = _color(rows, spec.get("color") or "design", "design")
    for d in rows:
        d["xv"] = d["x"]
        d["yv"] = d["y"]
    xq = {"field": "xv", "type": "quantitative", "title": _axis_title(spec, "x", units["x"], "x"),
          "scale": {"zero": False, "nice": True, "padding": 16},
          "axis": {"grid": True, "domain": False, "ticks": False, "tickCount": {"expr": "max(3, floor(width / 90))"}}}
    yq = {"field": "yv", "type": "quantitative", "title": _axis_title(spec, "y", units["y"], "y"),
          "scale": {"zero": False, "nice": True, "padding": 16},
          "axis": {"grid": True, "domain": False, "ticks": False, "titlePadding": 10}}
    tip = tooltip_fields(rows) + [{"field": "xv", "title": "x"}, {"field": "x_source", "title": "x 근거"}]
    layers = _dots(xq, yq, color_enc, tip)
    layers.append({"mark": {"type": "text", "align": "left", "dx": 10, "fontSize": 12.5, "color": LIGHT["fg"]},
                   "encoding": {"x": xq, "y": yq, "text": {"field": "line1"}}})
    return {"usermeta": {"legend": ([{"title": "연구 설계" if (spec.get("color") or "design") == "design" else None,
                                      "items": items}] if items else [])
                         + [{"title": "읽은 범위", "items": access_legend(d["label"] for d in rows)}]},
            "width": "container", "height": 340, "autosize": {"type": "fit-x", "contain": "padding"},
            "padding": {"left": 4, "right": 70, "top": 8, "bottom": 4},
            "data": {"values": rows}, "layer": layers}


def _forbidden(node: Any, path: str = "vegalite") -> list[str]:
    """Keys a custom spec may not carry: its data must be the resolved rows."""
    out = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k in ("data", "datasets", "url"):
                out.append(f"{path}.{k}")
            out += _forbidden(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out += _forbidden(v, f"{path}[{i}]")
    return out


def custom_chart(spec: dict, rows: list[dict]) -> dict:
    vl = copy.deepcopy(spec["vegalite"])
    if not isinstance(vl, dict):
        raise VizError("vegalite must be an object")
    bad = _forbidden(vl)
    if bad:
        raise VizError(f"custom vegalite spec may not bring its own data ({', '.join(bad)}); "
                       "its data is the resolved rows")
    vl.pop("$schema", None)
    vl.setdefault("width", "container")
    if vl["width"] == "container":
        vl.setdefault("autosize", {"type": "fit-x", "contain": "padding"})
    cfg = base_config()
    user_cfg = vl.pop("config", {}) or {}
    for k, v in user_cfg.items():
        cfg[k] = {**cfg.get(k, {}), **v} if isinstance(v, dict) and isinstance(cfg.get(k), dict) else v
    vl["config"] = cfg
    vl["data"] = {"values": rows}
    meta = vl.setdefault("usermeta", {})
    meta.setdefault("legend", [{"title": "읽은 범위", "items": access_legend(d["label"] for d in rows)}])
    return vl


# ---------------------------------------------------------------- build

def load_spec(path: Path) -> dict:
    try:
        spec = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VizError(f"cannot read figure spec {path}: {exc}") from exc
    if not isinstance(spec, dict):
        raise VizError(f"figure spec {path} is not a JSON object")
    return spec


def records_of(topic: Path) -> dict[str, dict]:
    return dict(load_records(topic))


def takeaway_findings(spec: dict, rows: list[dict], records: dict[str, dict]) -> list[dict]:
    """Numbers in the takeaway (the figure title) that no row supports, or that only preliminary rows
    (예비 근거: conference abstracts, preprints, items not read in full) support."""
    from scholarly_access_agent.evidence import is_preliminary
    from scholarly_access_agent.trace import number_tokens, values_match

    out = []
    for written, value in number_tokens(str(spec.get("takeaway") or "")):
        backing = []
        for d in rows:
            nums = [d.get(k) for k in ("value", "lo", "hi", "x", "y")]
            if any(isinstance(n, (int, float)) and values_match(written, value, float(n)) for n in nums):
                backing.append(d)
        if not backing:
            out.append({"level": "warning", "rule": "takeaway_number_not_in_rows",
                        "message": f"takeaway number {written} matches no row of the figure"})
            continue
        recs = [records.get(d.get("record")) for d in backing if d.get("record") in records]
        if recs and all(is_preliminary(r) for r in recs):
            out.append({"level": "warning", "rule": "takeaway_rests_on_preliminary",
                        "message": f"takeaway number {written} comes only from preliminary evidence "
                                   f"({', '.join(sorted({d.get('record') for d in backing}))})"})
    return out


def build(topic: Path, spec: dict, spec_name: str = "") -> tuple[dict, dict]:
    for k in ("question", "takeaway"):
        if not str(spec.get(k) or "").strip():
            raise VizError(f"figure spec needs `{k}` (the takeaway is the title, the question the subtitle)")
    records = records_of(topic)
    rows, problems, info = resolve_rows(spec, records)
    if problems.errors:
        lines = [f"- row {p['row'] + 1 if p['row'] is not None else '-'}: {p['rule']}: {p['message']}"
                 for p in problems.errors]
        raise VizError("figure rows do not resolve to evidence:\n" + "\n".join(lines))
    if not rows:
        raise VizError("no drawable rows (all 미확인?)")
    units = info["units"]
    form = spec.get("form") or "custom"
    title, subtitle = str(spec["takeaway"]).strip(), str(spec["question"]).strip()
    if "vegalite" in spec:
        vl = custom_chart(spec, rows)
        vl["usermeta"]["header"] = {"title": title, "subtitle": subtitle}
        out = finish(vl)
    elif form in ROW_FORMS:
        band = spec.get("band") or None
        b = (float(band["lo"]), float(band["hi"])) if band else None
        group_by = spec.get("group_by")
        if group_by is None:
            group_by = "group" if any(d.get("group") for d in rows) else ("design" if form != "strip" else "design")
        group_by = None if group_by == "none" else group_by
        out, _ = row_chart(rows, unit=units["x"], x_title=_axis_title(spec, "x", units["x"], "값"), title=title,
                           subtitle=subtitle, mark=form, band=b, band_label=(band or {}).get("label"),
                           sort=spec.get("sort") or "given", group_by=group_by,
                           color=spec.get("color") or "design", zero=bool(spec.get("zero")))
    else:
        body = {"line": line_chart, "stacked": stacked_chart, "scatter": scatter_chart}[form](spec, rows, units)
        body["usermeta"]["header"] = {"title": title, "subtitle": subtitle}
        for d in body["data"]["values"]:
            for k in [k for k in d if k.startswith("_") and k not in ("_c",)]:
                d.pop(k)
        out = finish(body)
    out["usermeta"]["figure"] = {"form": form, "spec": spec_name, "rows": len(rows)}
    studies = len({d["record"] for d in rows})
    notes = []
    if info["unread"]:
        notes.append(f"미확인 {info['unread']}건 생략")
    if spec.get("note"):
        notes.append(str(spec["note"]))
    meta = {"warnings": takeaway_findings(spec, rows, records),
            "points": len(rows), "studies": studies, "notes": notes, "title": title,
            "source": f"evidence/ {studies}편의 results ({len(rows)}개 값{', ' + spec_name if spec_name else ''})"}
    return out, meta


# ---------------------------------------------------------------- report trace

IMAGE = re.compile(r"!\[[^\]]*\]\(\s*<?([^)\s>]+\.html?)>?(?:\s+\"[^\"]*\")?\s*\)", re.I)


def spec_for(html_path: Path) -> Path:
    return html_path.with_name(html_path.name.rsplit(".", 1)[0] + SPEC_SUFFIX)


def check_report(text: str, folder: Path, records: dict[str, dict]) -> list[dict]:
    """Findings for every `![..](figs/x.html)` whose sibling figs/x.fig.json exists: rows that do not resolve to
    evidence (unknown key or result, literal numbers, unit mismatches, computed values that do not add up)."""
    findings, fence = [], False
    for no, line in enumerate(text.splitlines(), 1):
        if re.match(r"^\s*(```|~~~)", line):
            fence = not fence
            continue
        if fence:
            continue
        for m in IMAGE.finditer(line):
            src = m.group(1)
            if re.match(r"^[a-z]+:", src, re.I):
                continue
            spec_path = spec_for((folder / src))
            if not spec_path.is_file():
                continue
            name = spec_path.relative_to(folder).as_posix() if spec_path.is_relative_to(folder) else spec_path.name
            try:
                spec = load_spec(spec_path)
            except VizError as exc:
                findings.append({"level": "error", "line": no, "rule": "figure_spec_invalid", "message": str(exc),
                                 "sentence": name})
                continue
            resolved, problems, _ = resolve_rows(spec, records)
            for p in takeaway_findings(spec, resolved, records):
                findings.append({"level": p["level"], "line": no, "rule": f"figure_{p['rule']}",
                                 "message": f"{name}: {p['message']}", "sentence": name})
            for p in problems:
                row = f"row {p['row'] + 1}: " if p["row"] is not None else ""
                findings.append({"level": p["level"], "line": no, "rule": f"figure_{p['rule']}",
                                 "message": f"{name}: {row}{p['message']}", "sentence": name})
    return findings
