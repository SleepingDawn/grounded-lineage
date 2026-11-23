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

VEGA = "https://cdn.jsdelivr.net/npm/vega@5.30.0/build/vega.min.js"
VEGA_LITE = "https://cdn.jsdelivr.net/npm/vega-lite@5.21.0/build/vega-lite.min.js"
VEGA_EMBED = "https://cdn.jsdelivr.net/npm/vega-embed@6.26.0/build/vega-embed.min.js"
SCHEMA = "https://vega.github.io/schema/vega-lite/v5.json"

# Light-theme tokens. The page swaps these exact strings for the dark ones when the theme is dark, so the
# .vl.json next to each page stays a plain, valid light-theme spec.
LIGHT = {"fg": "#1f2328", "muted": "#59636e", "grid": "#d8dee4", "domain": "#8c959f"}
DARK = {"fg": "#e6edf3", "muted": "#9198a1", "grid": "#30363d", "domain": "#6e7681"}
FONT = "Pretendard, 'Apple SD Gothic Neo', 'Malgun Gothic', 'Noto Sans KR', system-ui, sans-serif"

# Okabe-Ito, shared with the lineage flow map
DESIGNS = [("model", "모형", "#0072B2"), ("observational", "관찰", "#009E73"), ("experiment", "실험", "#D55E00"),
           ("quasi", "준실험", "#E69F00"), ("review", "리뷰", "#CC79A7")]
UNKNOWN_DESIGN = ("unknown", "미분류", "#999999")

# read depth -> fill opacity (filled / half / hollow); 미확인 is left out of the charts and counted in a note
ACCESS_STYLE = [(LABEL_BODY, 1.0), (LABEL_EXCERPTS, 0.45), (LABEL_SECONDARY, 0.0), (LABEL_ABSTRACT, 0.0)]


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


def access_scale(present: Iterable[str]) -> dict:
    present = set(present)
    rows = [a for a in ACCESS_STYLE if a[0] in present]
    return {"type": "ordinal", "domain": [r[0] for r in rows], "range": [r[1] for r in rows]}


def access_channel(present: Iterable[str]) -> dict:
    """fillOpacity encoding: filled = 본문 확인, half = 발췌 확인, hollow = 인용 맥락만 / 초록만 확인.

    Vega-Lite draws no legend for fillOpacity, so the page adds its own key (access_key_html) under the chart
    and the spec carries the mapping in usermeta.access_key."""
    scale = access_scale(present)
    return {"field": "label", "type": "ordinal", "sort": scale["domain"], "scale": scale, "legend": None}


def access_key(present: Iterable[str]) -> list[dict]:
    present = set(present)
    return [{"label": a, "fill_opacity": o} for a, o in ACCESS_STYLE if a in present]


def access_key_html(items: list[dict], title: str = "읽은 범위") -> str:
    if not items:
        return ""
    parts = []
    for it in items:
        parts.append('<span class="key"><svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">'
                     f'<circle cx="6" cy="6" r="4.6" fill="currentColor" fill-opacity="{it["fill_opacity"]}" '
                     f'stroke="currentColor" stroke-width="1.5"/></svg>{html.escape(it["label"])}</span>')
    return f'<div class="keys"><b>{html.escape(title)}</b>' + "".join(parts) + "</div>"


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


def wrap_label(text: str, width: float = 9.0) -> str:
    """Greedy word wrap counting Hangul as 1 and other characters as 0.6; lines joined with newlines."""
    def w(s: str) -> float:
        return sum(1.0 if HANGUL.match(c) else 0.6 for c in s)

    lines: list[str] = []
    for word in text.split():
        if lines and w(lines[-1] + " " + word) <= width:
            lines[-1] += " " + word
        else:
            lines.append(word)
    return "\n".join(lines) or text


def base_config() -> dict:
    fg, muted, grid, domain = LIGHT["fg"], LIGHT["muted"], LIGHT["grid"], LIGHT["domain"]
    return {
        "background": None,
        "font": FONT,
        "view": {"stroke": None},
        "axis": {"labelColor": muted, "titleColor": fg, "gridColor": grid, "domainColor": domain,
                 "tickColor": domain, "labelFontSize": 11, "titleFontSize": 12, "titleFontWeight": 600},
        "legend": {"labelColor": fg, "titleColor": fg, "labelFontSize": 11, "titleFontSize": 11,
                   "orient": "bottom", "direction": "vertical", "labelLimit": 220},
        "title": {"color": fg, "subtitleColor": muted, "fontSize": 13, "anchor": "start"},
        "text": {"color": fg},
        "header": {"labelColor": fg, "titleColor": fg},
    }


def finish(spec: dict) -> dict:
    out = {"$schema": SCHEMA}
    out.update(spec)
    out["background"] = None
    out.setdefault("config", base_config())
    return out


PAGE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root { --fg: __FG__; --muted: __MUTED__; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --fg: __DFG__; --muted: __DMUTED__; } }
:root[data-theme="dark"] { --fg: __DFG__; --muted: __DMUTED__; }
html, body { margin: 0; padding: 0; background: transparent; color: var(--fg); overflow-x: hidden;
  font-family: __FONT__; }
figure { margin: 0; padding: 4px 2px 2px; max-width: 100%; box-sizing: border-box; }
#vis { width: 100%; min-width: 0; }
#vis.vega-embed, #vis .vega-embed { width: 100%; display: block; }
#vis .vega-embed summary { display: none; }
.keys { font-size: 11px; color: var(--fg); margin: 2px 4px 0; display: flex; flex-wrap: wrap; gap: 4px 12px;
  align-items: center; }
.keys b { font-weight: 600; }
.key { display: inline-flex; align-items: center; gap: 4px; }
figcaption { font-size: 12px; line-height: 1.45; color: var(--muted); margin: 6px 4px 0; overflow-wrap: anywhere; }
.err { color: #D55E00; font-size: 13px; }
</style>
<script src="__VEGA__"></script>
<script src="__VEGA_LITE__"></script>
<script src="__VEGA_EMBED__"></script>
</head>
<body>
<figure id="fig">
<div id="vis"></div>
__KEYS__<figcaption>__CAPTION__</figcaption>
</figure>
<script>
(function () {
  "use strict";
  var SPEC = __SPEC__;
  var LIGHT = __LIGHT__, DARK = __DARK__;
  var el = document.getElementById("vis"), fig = document.getElementById("fig");
  var view = null, lastHeight = -1, lastWidth = -1, timer = null, forced = null;

  function parentTheme() {
    try {
      if (window.parent && window.parent !== window) {
        return window.parent.document.documentElement.getAttribute("data-theme");
      }
    } catch (e) { /* cross-origin parent */ }
    return null;
  }
  function theme() {
    var t = forced || parentTheme() || document.documentElement.getAttribute("data-theme");
    if (t === "dark" || t === "light") return t;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
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
    return spec;
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
    document.documentElement.style.setProperty("--fg", t === "dark" ? DARK.fg : LIGHT.fg);
    document.documentElement.style.setProperty("--muted", t === "dark" ? DARK.muted : LIGHT.muted);
    lastWidth = el.clientWidth;
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
    if (d.type === "snu-theme" && (d.theme === "dark" || d.theme === "light" || d.theme === null)) {
      forced = d.theme; render();
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
    keys = access_key_html(((spec.get("usermeta") or {}).get("access_key")) or [])
    spec_js = json.dumps(spec, ensure_ascii=False).replace("</", "<\\/")
    repl = {
        "__TITLE__": html.escape(title), "__CAPTION__": html.escape(caption), "__KEYS__": keys,
        "__FG__": LIGHT["fg"], "__MUTED__": LIGHT["muted"], "__DFG__": DARK["fg"], "__DMUTED__": DARK["muted"],
        "__FONT__": FONT, "__VEGA__": VEGA, "__VEGA_LITE__": VEGA_LITE, "__VEGA_EMBED__": VEGA_EMBED,
        "__LIGHT__": json.dumps(LIGHT), "__DARK__": json.dumps(DARK), "__SPEC__": spec_js,
    }
    out = PAGE
    for k in ("__TITLE__", "__KEYS__", "__CAPTION__", "__FG__", "__MUTED__", "__DFG__", "__DMUTED__", "__FONT__", "__VEGA__",
              "__VEGA_LITE__", "__VEGA_EMBED__", "__LIGHT__", "__DARK__"):
        out = out.replace(k, repl[k])
    return out.replace("__SPEC__", repl["__SPEC__"])  # last: the spec may contain any of the tokens above


def write_chart(spec: dict, out: Path, title: str, caption: str) -> tuple[Path, Path]:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page_html(spec, title, caption), encoding="utf-8")
    vl = out.with_name(out.stem + ".vl.json")
    vl.write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")
    return out, vl


def jsonable(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return json.loads(json.dumps(rows, ensure_ascii=False, default=str))
