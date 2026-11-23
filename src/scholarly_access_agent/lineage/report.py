"""Write the lineage chapter of a Markdown report (for `render-report`) from lineage.json.

Usage:
  lineage report-section WORK_DIR [--report-dir REPORT_DIR] [--chapter 8] [--no-figure]
REPORT_DIR defaults to WORK_DIR: the topic folder holds README.md (the report) and figs/.

Writes, inside REPORT_DIR:
  lineage_section.md   the chapter: diagram, branch axes, stage table, main trends,
                       one-line summary, data evidence, lineage table with evidence status
  figs/lineage.png     the diagram, rendered headless with Playwright (skipped with --no-figure)
Paste or include the chapter into the report Markdown, then render the PDF as usual.
The chapter follows report-pdf.md: pipe tables, local PNG, no raw HTML.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .page import Links, lane_name, load, parse_desc, svg, validate, warnings

STATUS = {"fulltext": "본문 확인", "abstract": "초록만 확인", "metadata": "미확인"}
VERSION = {"journal": "저널", "proceedings": "학회", "preprint": "프리프린트", "unknown": ""}


def cell(t) -> str:
    """Make text safe inside a pipe-table cell."""
    return str(t if t is not None else "").replace("|", "/").replace("\n", " ").strip() or "–"


def lanes_table(L) -> list[str]:
    by_lane: dict[int, list] = {}
    for n in L["nodes"]:
        by_lane.setdefault(n["lane"], []).append(n)
    out = ["| 계열 | 시기 | 방식 | 대표 연구 | 핵심 한계 |", "|---|---|---|---|---|"]
    for i, ln in enumerate(L["lanes"]):
        nodes = sorted(by_lane.get(i, []), key=lambda n: n["year"])
        if not nodes:
            continue
        y0, y1 = nodes[0]["year"], nodes[-1]["year"]
        period = f"{y0}" if y0 == y1 else f"{y0}–{y1}"
        reps = "; ".join(f'{n["title"]} ({n["sub"]})' for n in nodes[:5]) + (" 외" if len(nodes) > 5 else "")
        out.append(f"| {cell(lane_name(ln))} | {period} | {cell(ln.get('how'))} | {cell(reps)} | {cell(ln.get('limit'))} |")
    return out


def axes_md(L) -> list[str]:
    out = []
    for a in L.get("axes", []):
        out.append(f"**{a['question']}**")
        out.append("")
        for i in a.get("items", []):
            out.append(f"- **{i['label']}**: {i['text']}")
        if a.get("text"):
            out += ["", a["text"]]
        out.append("")
    if L.get("axes_note"):
        out += [f"> {L['axes_note']}", ""]
    return out


def trends_md(L) -> list[str]:
    out = []
    for k, t in enumerate(L.get("trends", []), 1):
        out.append(f"{k}. **{t['title']}**")
        out += [f"   - {p}" for p in t.get("points", [])]
    if out:
        out.append("")
    if L.get("verdict"):
        out += ["**현재 판정**", ""]
    for v in L.get("verdict", []):
        out.append(f"- **{v['tag']}**: {v['title']}")
        out += [f"  - {p}" for p in v.get("points", [])]
    return out + [""]


def evidence_md(L, data: Path) -> list[str]:
    an = load(data / "analysis.json")
    if not an:
        return ["analysis.json이 없어 데이터 근거를 생략했습니다.", ""]
    ev = L.get("evidence", {})
    mp = [parse_desc(s) for s in an["main_path"]][-ev.get("main_path_tail", 8):]
    out = ["- **주경로 (SPC) 끝부분**: " + " → ".join(m["label"] for m in mp)]
    if ev.get("main_path_note"):
        out.append(f"  - {ev['main_path_note']}")
    keep = ev.get("rpys_years")
    peaks = sorted(p for p in an["rpys_peaks"] if p[0] in keep) if keep else an["rpys_peaks"][:6]
    if peaks:
        out.append("- **RPYS 봉우리**: " + "; ".join(
            f"{y} ({parse_desc(tops[0])['label']})" for y, _, _, tops in peaks if tops))
    if ev.get("rpys_note"):
        out.append(f"  - {ev['rpys_note']}")
    labels = ev.get("cluster_labels", {})
    for c in an["clusters"]:
        lab = labels.get(str(c["cluster"])) or ", ".join(c["words"][:4])
        out.append(f"- **군집 · {lab}**: {c['size']}편 ({c['years']})")
    fy = an.get("forward_by_year", {})
    if fy:
        out.append("- **씨앗 인용 논문 연도별**: " + ", ".join(f"{k}년 {v}편" for k, v in sorted(fy.items())))
    return out + [""]


def rows_md(L, links: Links) -> list[str]:
    out = ["| 연도 | 연구 | 무엇을 했나 | 앞 세대에서 바꾼 것 | 계열 | 근거 상태 |", "|---|---|---|---|---|---|"]
    for r in L.get("rows", []):
        _, kind, _ = links.of(r.get("openalex"), r.get("url"))
        lane = r.get("lane")
        lane_txt = lane_name(L["lanes"][lane]) if lane is not None else "리뷰·관점"
        status = STATUS[r["level"]]
        detail = r.get("evidence") or ""
        ver = r.get("version") or VERSION.get(kind, "")
        tail = ", ".join(x for x in (detail, ver) if x)
        out.append(f"| {cell(r['year'])} | {cell(r['work'])} | {cell(r['what'])} | {cell(r['change'])} | "
                   f"{cell(lane_txt)} | {cell(status + (f' ({tail})' if tail else ''))} |")
    return out + [""]


def section(L, data: Path, links: Links, chapter: int, figure: str | None, html_name: str) -> str:
    c = chapter
    out = [f"## {c}. 계보와 흐름", ""]
    if L.get("meta", {}).get("lede"):
        out += [L["meta"]["lede"], ""]
    if figure:
        # The HTML report inlines the clickable page in place of the PNG ("interactive=" title).
        out += [f"![계보도. 열은 계열, 행은 연도(등간격 아님). 실선은 직접 계승, 점선은 개념적 연결, "
                f"굵은 선은 인용 네트워크 주경로. 상자를 누르면 원문이 열립니다 (단독 페이지: {html_name})]"
                f"({figure} \"interactive={html_name}\")", ""]
    out += [f"### {c}.1 갈라진 지점", ""] + axes_md(L)
    out += [f"### {c}.2 단계별 흐름", ""] + lanes_table(L) + [""]
    out += [f"### {c}.3 주요 흐름", ""] + trends_md(L)
    if L.get("one_line"):
        out += [f"### {c}.4 한 줄 요약", "", L["one_line"], ""]
        n = 5
    else:
        n = 4
    out += [f"### {c}.{n} 데이터로 본 근거", ""] + evidence_md(L, data)
    out += [f"### {c}.{n + 1} 계보 표와 근거 상태", ""] + rows_md(L, links)
    if L.get("limits"):
        out += [f"### {c}.{n + 2} 이 계보의 한계", ""] + [f"- {x}" for x in L["limits"]] + [""]
    return "\n".join(out)


FIGURE_CSS = """
:root{color-scheme:light;--f-body:"Malgun Gothic","Apple SD Gothic Neo","Noto Sans KR",sans-serif;
--f-mono:Consolas,"DejaVu Sans Mono",monospace}
html,body{margin:0;padding:0;background:#ffffff}
"""


def render_figure(L, links: Links, out_png: Path, scale: float = 2.0) -> Path:
    """Screenshot the lineage SVG with headless Chromium (light theme, local fonts)."""
    from playwright.sync_api import sync_playwright

    css = (Path(__file__).with_name("assets") / "page.css").read_text(encoding="utf-8")
    html = (f"<!doctype html><html><head><meta charset='utf-8'><style>{css}{FIGURE_CSS}</style></head>"
            f"<body><div id='fig'>{svg(L, links)}</div></body></html>")
    out_png.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page(device_scale_factor=scale, color_scheme="light")
            page.set_content(html, wait_until="load")
            page.locator("svg#tree").screenshot(path=str(out_png))
        finally:
            browser.close()
    return out_png


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="lineage report-section")
    ap.add_argument("work_dir")
    ap.add_argument("--report-dir", help="default: the work folder itself (topic folder layout)")
    ap.add_argument("--chapter", type=int, default=8)
    ap.add_argument("--no-figure", action="store_true")
    a = ap.parse_args(argv)
    work = Path(a.work_dir)
    rdir = Path(a.report_dir) if a.report_dir else work
    L = load(work / "lineage.json")
    if L is None:
        print(f"{work / 'lineage.json'} not found", file=sys.stderr)
        return 1
    errs = validate(L)
    if errs:
        print("lineage.json problems:\n  - " + "\n  - ".join(errs), file=sys.stderr)
        return 1
    for w in warnings(L):  # the figure is the same drawing as the page: same layout warnings
        print("warning:", w, file=sys.stderr)
    data = work / L["meta"].get("data_dir", "data")
    links = Links(load(data / "links.json", {}), L.get("link_overrides"))
    rdir.mkdir(parents=True, exist_ok=True)
    figure = None
    if not a.no_figure:
        try:
            render_figure(L, links, rdir / "figs" / "lineage.png")
            figure = "figs/lineage.png"
        except Exception as exc:  # Playwright or Chromium missing: keep the text chapter
            print(f"warning: figure not rendered ({type(exc).__name__}); chapter written without it", file=sys.stderr)
    html_name = L["meta"].get("slug", "lineage") + ".html"
    md = section(L, data, links, a.chapter, figure, html_name)
    (rdir / "lineage_section.md").write_text(md, encoding="utf-8")
    print(json.dumps({"ok": True, "section": str(rdir / "lineage_section.md"), "figure": figure}, ensure_ascii=False))
    return 0
