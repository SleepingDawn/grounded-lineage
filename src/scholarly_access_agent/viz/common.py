"""Shared pieces for the viz charts: palette, access styling, record loading, the standalone HTML writer."""
from __future__ import annotations

import datetime
import html
import json
import re
from pathlib import Path
from typing import Any, Iterable

from scholarly_access_agent.evidence import (
    EXCERPT_MODES,
    LABEL_ABSTRACT,
    LABEL_BODY,
    LABEL_EXCERPTS,
    LABEL_NONE,
    LABEL_SECONDARY,
    derive_label,
    resolve_folders,
)

from . import tokens

VEGA = "https://cdn.jsdelivr.net/npm/vega@5.30.0/build/vega.min.js"
VEGA_LITE = "https://cdn.jsdelivr.net/npm/vega-lite@5.21.0/build/vega-lite.min.js"
VEGA_EMBED = "https://cdn.jsdelivr.net/npm/vega-embed@6.26.0/build/vega-embed.min.js"
SCHEMA = "https://vega.github.io/schema/vega-lite/v5.json"

# Colours and fonts come from data/design_tokens.json (shared with the report and the lineage map). Specs are
# written with the light values; the page swaps each light string for its dark one when the theme is dark, so the
# .vl.json next to each page stays a plain, valid light-theme spec. Keys: fg / muted (ink), grid (axis and group
# rules), rule (row separators), surface (behind the chart), band / band_edge (reference column), d_<design>.
LIGHT, DARK = tokens.viz_swap()
FONT = tokens.font_stack("body")
SIZE = tokens.tokens()["size"]

# Okabe-Ito study-design colours (light values; dark mode lightens only the blue): (key, Korean label, colour)
_DESIGN_ALL = [(k, label, LIGHT[f"d_{k}"]) for k, label in tokens.design_labels()]
DESIGNS = [d for d in _DESIGN_ALL if d[0] != "unknown"]
UNKNOWN_DESIGN = next(d for d in _DESIGN_ALL if d[0] == "unknown")

# read depth -> mark fill (full / half / hollow); 미확인 ("none") is left out of the charts and counted in a note
ACCESS_FILL = [(label, style) for label, style in tokens.read_depth().items() if style != "none"]
assert {LABEL_BODY, LABEL_EXCERPTS, LABEL_SECONDARY, LABEL_ABSTRACT} == {a for a, _ in ACCESS_FILL}


class VizError(Exception):
    """A chart cannot be drawn from the data as given (message is shown to the user)."""


def today() -> str:
    return datetime.date.today().isoformat()


def design_of(record: dict) -> str:
    """Korean design label from record `design`, else evidence_role; unknown -> 미분류."""
    d = str(record.get("design") or "").strip().lower()
    if d:
        for keys, name in ((("review", "meta-analys", "리뷰", "메타"), "review"), (("quasi", "준실험"), "quasi"),
                           (("experiment", "rct", "trial", "measure", "실험"), "experiment"),
                           (("observ", "cohort", "survey", "case", "cross-sec", "panel", "관찰"), "observational"),
                           (("model", "simul", "theor", "comput", "모형", "모델"), "model")):
            if any(k in d for k in keys):
                return dict((k, v) for k, v, _ in DESIGNS)[name]
    role = str(record.get("evidence_role") or "").strip().lower()
    mapped = {"model": "model", "review": "review", "empirical": "observational"}.get(role)
    if mapped:
        return dict((k, v) for k, v, _ in DESIGNS)[mapped]
    if str(record.get("venue_type") or "").lower() == "review":
        return "리뷰"
    return UNKNOWN_DESIGN[1]


def design_scale(present: Iterable[str]) -> dict:
    present = set(present)
    rows = [d for d in DESIGNS + [UNKNOWN_DESIGN] if d[1] in present]
    return {"domain": [r[1] for r in rows], "range": [r[2] for r in rows]}


def fill_of(label: str) -> str:
    return dict(ACCESS_FILL).get(label, "hollow")


def access_legend(present: Iterable[str]) -> list[dict]:
    """Legend items for the read depths present, filled -> hollow; the two hollow labels share one item."""
    present = set(present)
    items: list[dict] = []
    for fill in ("full", "half", "hollow"):
        names = [a for a, f in ACCESS_FILL if f == fill and a in present]
        if names:
            items.append({"label": " · ".join(names), "swatch": fill})
    return items


SWATCH = {
    "dot": '<circle cx="7" cy="7" r="5.5" fill="{c}"/>',
    "full": '<circle cx="7" cy="7" r="5.2" fill="currentColor" stroke="currentColor" stroke-width="1.6"/>',
    "half": '<circle cx="7" cy="7" r="5.2" fill="none" stroke="currentColor" stroke-width="1.6"/>'
            '<path d="M7,1.8A5.2,5.2 0 0 0 7,12.2Z" fill="currentColor"/>',
    "hollow": '<circle cx="7" cy="7" r="5.2" fill="none" stroke="currentColor" stroke-width="1.6"/>',
    "band": '<rect x="0.5" y="0.5" width="13" height="13" rx="2" fill="var(--c-band)" stroke="var(--c-band_edge)"/>',
    "arrow": '<path d="M3,3L11,7L3,11Z" fill="currentColor"/>',
    "approx": '<text x="7" y="11.5" text-anchor="middle" font-size="13" font-weight="600" fill="currentColor">≈</text>',
    "line": '<line x1="1" x2="13" y1="7" y2="7" stroke="{c}" stroke-width="2.4" stroke-linecap="round"/>',
    "square": '<rect x="1" y="1" width="12" height="12" rx="2.5" fill="{c}"/>',
}


THEMED = {tokens.value(path, "light").lower(): f"var({name})" for name, path in tokens.viz_vars().items()
          if path.startswith(("color.", "design."))}


def legend_html(groups: list[dict]) -> str:
    """One row of legend chips above the plot: [{title?, items: [{label, swatch, color?}]}]."""
    out = []
    for g in groups or []:
        chips = []
        for it in g.get("items") or []:
            c = str(it.get("color") or "currentColor")
            c = THEMED.get(c.lower(), c)  # a token colour follows the theme
            shape = SWATCH.get(it.get("swatch"), SWATCH["dot"]).replace("{c}", html.escape(c))
            chips.append(f'<span class="chip"><svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">'
                         f'{shape}</svg>{html.escape(str(it["label"]))}</span>')
        if chips:
            head = f'<span class="lg-t">{html.escape(g["title"])}</span>' if g.get("title") else ""
            out.append(f'<span class="lg">{head}{"".join(chips)}</span>')
    return f'<div class="legend" role="list">{"".join(out)}</div>' if out else ""


def header_html(head: dict | None) -> str:
    if not head or not head.get("title"):
        return ""
    sub = f'<p class="fsub">{html.escape(head["subtitle"])}</p>' if head.get("subtitle") else ""
    return f'<header class="fhead"><p class="ftitle">{html.escape(head["title"])}</p>{sub}</header>'


def result_label(record_label: str, result: dict) -> str:
    """A number read only through a term search or caption is an excerpt even in a fulltext record."""
    if record_label == LABEL_BODY and result.get("read_mode") in EXCERPT_MODES:
        return LABEL_EXCERPTS
    return record_label


def load_records(topic: Path) -> list[tuple[str, dict]]:
    _, evidence, _ = resolve_folders(topic)
    out = []
    if evidence is None:
        return out
    for f in sorted(evidence.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            out.append((f.stem, data))
    return out


HANGUL = re.compile(r"[가-힣]")


def first_author(record: dict, stem: str = "") -> str:
    authors = record.get("authors")
    if isinstance(authors, list):
        first = str(authors[0]) if authors else ""
    else:
        first = re.split(r";| and |,(?=\s*[A-Z][a-z]+ )", str(authors or ""))[0]
    first = first.strip()
    if first:
        if HANGUL.search(first):
            return first.split("(")[0].strip().split()[0]
        if "," in first:  # "Surname, Given"
            return first.split(",")[0].strip()
        return first.split("(")[0].strip().split()[-1]
    m = re.match(r"[A-Za-z\-]+", stem)
    return m.group(0).capitalize() if m else (stem or "?")


def year_of(record: dict, stem: str = "") -> str:
    y = record.get("year")
    if y:
        return str(y)
    m = re.search(r"(19|20)\d{2}", stem)
    return m.group(0) if m else "n.d."


def study_label(record: dict, stem: str = "") -> str:
    return f"{first_author(record, stem)} {year_of(record, stem)}"


def base_config() -> dict:
    """Vega-Lite config from the design tokens: every chart's ink, rules and fonts."""
    fg, muted, grid = LIGHT["fg"], LIGHT["muted"], LIGHT["grid"]
    small, label = SIZE["chart_small"], SIZE["chart_label"]
    return {
        "background": None,
        "font": FONT,
        "view": {"stroke": None},
        "axis": {"labelColor": muted, "titleColor": muted, "gridColor": LIGHT["rule"], "domainColor": grid,
                 "tickColor": grid, "labelFontSize": small, "titleFontSize": small + 0.5, "titleFontWeight": 500,
                 "labelFont": FONT, "titleFont": FONT},
        "legend": {"labelColor": fg, "titleColor": muted, "labelFontSize": small, "titleFontSize": small,
                   "orient": "top", "direction": "horizontal", "labelLimit": 220, "labelFont": FONT,
                   "titleFont": FONT},
        "title": {"color": fg, "subtitleColor": muted, "fontSize": SIZE["chart_title"],
                  "subtitleFontSize": SIZE["chart_subtitle"], "anchor": "start", "font": FONT},
        "text": {"color": fg, "fontSize": label, "font": FONT},
        "header": {"labelColor": fg, "titleColor": fg, "labelFont": FONT, "titleFont": FONT},
        "range": {"category": [d[2] for d in DESIGNS]},
    }


def finish(spec: dict) -> dict:
    out = {"$schema": SCHEMA}
    out.update(spec)
    out["background"] = None
    out.setdefault("config", base_config())
    return out


PAGE = r"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
__TOKENS__
html, body { margin: 0; padding: 0; background: transparent; color: var(--fg); overflow-x: hidden;
  font-family: __FONT__; }
figure { margin: 0; padding: 4px 2px 2px; max-width: 100%; box-sizing: border-box; }
#vis { width: 100%; min-width: 0; }
#vis.vega-embed, #vis .vega-embed { width: 100%; display: block; }
#vis .vega-embed summary { display: none; }
.fhead { margin: 0 4px 10px; }
.ftitle { margin: 0; font-size: __TSIZE__; line-height: 1.35; font-weight: 650; color: var(--fg); letter-spacing: -0.01em; }
.fsub { margin: 3px 0 0; font-size: __SSIZE__; line-height: 1.45; color: var(--muted); }
.legend { display: flex; flex-wrap: wrap; gap: 6px 20px; margin: 0 4px 6px; font-size: 12.5px; color: var(--fg); }
.lg { display: inline-flex; flex-wrap: wrap; align-items: center; gap: 4px 12px; }
.lg-t { color: var(--muted); font-weight: 600; }
.chip { display: inline-flex; align-items: center; gap: 5px; white-space: nowrap; }
.chip svg { flex: none; }
figcaption { font-size: 12px; line-height: 1.45; color: var(--muted); margin: 6px 4px 0; overflow-wrap: anywhere; }
.err { color: var(--c-d-experiment); font-size: 13px; }
</style>
<script src="__VEGA__"></script>
<script src="__VEGA_LITE__"></script>
<script src="__VEGA_EMBED__"></script>
</head>
<body>
<figure id="fig">
__HEAD__
__LEGEND__
<div id="vis"></div>
<figcaption>__CAPTION__</figcaption>
</figure>
<script>
(function () {
  "use strict";
  var SPEC = __SPEC__;
  var LIGHT = __LIGHT__, DARK = __DARK__;
  var el = document.getElementById("vis"), fig = document.getElementById("fig");
  var view = null, lastHeight = -1, lastWidth = -1, lastNarrow = null, timer = null, forced = null;

  function parentTheme() {
    try {
      if (window.parent && window.parent !== window) {
        return window.parent.document.documentElement.getAttribute("data-theme");
      }
    } catch (e) { /* cross-origin parent */ }
    return null;
  }
  function theme() {  // a theme sent by the report frame wins, then a same-origin parent, then the OS
    var t = forced || parentTheme() || document.documentElement.getAttribute("data-theme");
    if (t === "dark" || t === "light") return t;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  function luminance(c) {  // "#rrggbb" or "rgb(r, g, b)" -> 0..1, else null
    var m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(c), r;
    if (m) r = [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)];
    else if ((m = /rgba?\(([\d.]+)[, ]+([\d.]+)[, ]+([\d.]+)/.exec(c))) r = [+m[1], +m[2], +m[3]];
    else return null;
    return (0.2126 * r[0] + 0.7152 * r[1] + 0.0722 * r[2]) / 255;
  }
  function swap(node, map) {
    if (typeof node === "string") return Object.prototype.hasOwnProperty.call(map, node) ? map[node] : node;
    if (Array.isArray(node)) return node.map(function (x) { return swap(x, map); });
    if (node && typeof node === "object") {
      var out = {};
      for (var k in node) out[k] = swap(node[k], map);
      return out;
    }
    return node;
  }
  function themed(dark) {
    var spec = JSON.parse(JSON.stringify(SPEC));
    if (dark) {
      var map = {};
      for (var k in LIGHT) map[LIGHT[k]] = DARK[k];
      spec = swap(spec, map);
    }
    var meta = spec.usermeta || {};
    if (meta.responsive === "concat" && spec.vconcat) {
      var w = Math.max(220, el.clientWidth - (meta.axisAllowance || 70));
      spec.vconcat.forEach(function (v) { v.width = w; });
    }
    if (meta.rows) {  // two row layouts (wide / narrow): pick one from this page's width
      var n = isNarrow();
      spec.height = n ? meta.rows.narrow_height : meta.rows.height;
      spec.params = (spec.params || []).map(function (p) { return p.name === "narrow" ? { name: "narrow", value: n } : p; });
    }
    return spec;
  }
  function isNarrow() {
    var rows = (SPEC.usermeta || {}).rows;
    return !!rows && el.clientWidth < rows.narrow_below;
  }
  function postHeight(force) {
    var h = Math.ceil(fig.getBoundingClientRect().height) + 4;
    if (force || h !== lastHeight) {
      lastHeight = h;
      try { window.parent.postMessage({ type: "snu-embed-height", height: h }, "*"); } catch (e) {}
    }
  }
  function render() {
    var t = theme();
    document.documentElement.setAttribute("data-chart-theme", t);
    document.documentElement.setAttribute("data-theme", t);  // the token CSS follows
    lastWidth = el.clientWidth;
    lastNarrow = isNarrow();
    if (view) { view.finalize(); view = null; }
    return vegaEmbed(el, themed(t === "dark"), {
      actions: false, renderer: "svg", tooltip: { theme: t === "dark" ? "dark" : "light" }
    }).then(function (res) {
      view = res.view;
      postHeight(true);
      setTimeout(function () { postHeight(true); }, 300);
    }).catch(function (err) {
      el.innerHTML = '<p class="err">그림을 그리지 못했습니다: ' + String(err && err.message || err) + "</p>";
      console.error(err);
      postHeight(true);
    });
  }
  window.addEventListener("resize", function () {
    clearTimeout(timer);
    timer = setTimeout(function () {
      if ((SPEC.usermeta || {}).responsive === "concat" && el.clientWidth !== lastWidth) render();
      else if (isNarrow() !== lastNarrow) render();
      else postHeight(false);
    }, 150);
  });
  if (window.ResizeObserver) new ResizeObserver(function () { postHeight(false); }).observe(fig);
  if (window.matchMedia) {
    var mq = window.matchMedia("(prefers-color-scheme: dark)");
    if (mq.addEventListener) mq.addEventListener("change", render);
  }
  window.addEventListener("message", function (ev) {
    var d = ev.data || {};
    // the report (runtime/quarto_report.py) sends snu-embed-theme; older callers snu-theme
    // The report's own surface colour decides when it is sent: Quarto marks every page quarto-light, so the
    // theme name alone can say "light" on a dark report.
    var t = d.theme, s = ((d.vars || {})["--snu-surface"] || "").trim(), l = luminance(s);
    if (d.type === "snu-embed-theme" && l !== null) t = l < 0.45 ? "dark" : "light";
    if ((d.type === "snu-embed-theme" || d.type === "snu-theme") && (t === "dark" || t === "light" || t === null)) {
      if (t !== forced) { forced = t; render(); }
    }
  });
  try {
    if (window.parent && window.parent !== window && window.MutationObserver) {
      new MutationObserver(render).observe(window.parent.document.documentElement,
        { attributes: true, attributeFilter: ["data-theme"] });
    }
  } catch (e) { /* cross-origin parent */ }
  window.addEventListener("load", function () { postHeight(true); });
  render();
})();
</script>
</body>
</html>
"""


def page_html(spec: dict, title: str, caption: str) -> str:
    meta = spec.get("usermeta") or {}

    spec_js = json.dumps(spec, ensure_ascii=False).replace("</", "<\\/")
    repl = {
        "__TITLE__": html.escape(title), "__CAPTION__": html.escape(caption), "__HEAD__": header_html(meta.get("header")),
        "__LEGEND__": legend_html(meta.get("legend") or []), "__TOKENS__": tokens.css_vars(tokens.viz_vars()),
        "__TSIZE__": f"{SIZE['chart_title']}px", "__SSIZE__": f"{SIZE['chart_subtitle']}px",
        "__FONT__": FONT, "__VEGA__": VEGA, "__VEGA_LITE__": VEGA_LITE, "__VEGA_EMBED__": VEGA_EMBED,
        "__LIGHT__": json.dumps(LIGHT), "__DARK__": json.dumps(DARK), "__SPEC__": spec_js,
    }
    # one pass, so text inside a replacement (a title, the spec) is never itself treated as a token
    return re.sub(r"__[A-Z]+(?:_[A-Z]+)*__", lambda m: repl.get(m.group(0), m.group(0)), PAGE)


def write_chart(spec: dict, out: Path, title: str, caption: str) -> tuple[Path, Path]:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page_html(spec, title, caption), encoding="utf-8")
    vl = out.with_name(out.stem + ".vl.json")
    vl.write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")
    return out, vl


def jsonable(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return json.loads(json.dumps(rows, ensure_ascii=False, default=str))
