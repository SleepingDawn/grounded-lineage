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

from .page import (DESIGN_KO, DISPUTE_CSS, Links, contested_rows, edge_list, has_disputes, is_event, lane_name, load,
                   mode, parse_desc, question_numbers, study_ref, svg, validate, warnings)
from .searchlog import saturation, searches, unsaturated_ko

STATUS = {"fulltext": "본문 확인", "excerpts": "발췌 확인", "secondary": "인용 맥락만", "abstract": "초록만 확인",
          "metadata": "미확인"}
X_CAPTION = ", ≠ 표시가 있는 붉은 쇄선은 서로 상충하는 연구"
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


def questions_table(L) -> list[str]:
    """Topic mode: question | current answer | key studies (subtitle, reference number, design)."""
    by_lane: dict[int, list] = {}
    for n in L["nodes"]:
        by_lane.setdefault(n["lane"], []).append(n)
    out = ["| 질문 | 지금의 답 | 핵심 연구 |", "|---|---|---|"]
    for i, k in question_numbers(L).items():
        ln = L["lanes"][i]
        studies = "; ".join(study_ref(n) + (f": {DESIGN_KO[n['design']]}" if n.get("design") in DESIGN_KO else "")
                            for n in sorted(by_lane.get(i, []), key=lambda n: n["year"]))
        out.append(f"| Q{k}. {cell(lane_name(ln))} | {cell(ln.get('answer'))} | {cell(studies)} |")
    return out


def events_md(L) -> list[str]:
    """Topic mode: the events band in one line, each event with the studies that evaluate it."""
    by_id = {n["id"]: n for n in L["nodes"]}
    evaluated: dict[str, list] = {}
    for s, t, st in edge_list(L):
        if st == "e":
            evaluated.setdefault(t, []).append(study_ref(by_id[s]))
    items = []
    for n in sorted((n for n in L["nodes"] if is_event(n)), key=lambda n: n["year"]):
        who = evaluated.get(n["id"])
        items.append(f"{n['title']} ({n['year']}" + (f"; 평가: {', '.join(who)})" if who else ")"))
    return ["**정책·사건**: " + "; ".join(items), ""] if items else []


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


def contested_md(L) -> list[str]:
    """쟁점 table: claim | A | B | measurement difference | status | evidence level of each side."""
    out = ["| 쟁점 | A | B | 측정 차이 | 상태 | 근거 수준 |", "|---|---|---|---|---|---|"]
    out += ["| " + " | ".join(cell(x) for x in r) + " |" for r in contested_rows(L)]
    return out + [""]


def logged_counts(L, work: Path) -> list[dict]:
    """adoption.json / mentions.json entries from the data and expanded dirs (what verdict text cites as adoption#n)."""
    meta = L.get("meta") or {}
    dirs = [meta.get("data_dir") or "data"] + ([meta["expanded_dir"]] if meta.get("expanded_dir") else [])
    out = []
    for d in dict.fromkeys(dirs):
        for name in ("adoption.json", "mentions.json"):
            for e in load(work / d / name, []) or []:
                out.append({**e, "_dir": d})
    return out


def method_md(L, work: Path, data: Path) -> list[str]:
    """Search method facts that the reader needs to weigh 'mainstream' and 'not found' claims; [] when none."""
    out = []
    state = saturation(data)
    if state and not state["saturated"]:
        out += [unsaturated_ko(state), ""]
    elif state and (searches(data) or logged_counts(L, work)):
        out += [f"검색 포화: 신규 비율 10% 미만에 이른 질의 {', '.join(state['saturated'])}.", ""]
    qlog = load(data / "queries.json", []) or []
    srcs = {e.get("gold_source") for e in qlog if e.get("gold")}
    if out and srcs - {None}:
        g = load(data / "gold.json") or {}
        if srcs == {"independent"}:
            out += [f"재현율의 정답 세트는 계보와 독립적으로 고정한 목록입니다 ({len(g.get('ids', []))}편"
                    + (f", {g.get('note') or g['source']}" if g.get("note") or g.get("source") else "") + ").", ""]
        elif "lineage" in srcs:
            out += ["재현율의 정답 세트 일부는 계보도의 논문에서 뽑아 순환적입니다.", ""]
    log = searches(data)
    if log:
        out += ["**OpenAlex 밖 검색**", "", "| 날짜 | 검색원 | 검색식 | 결과 | 남긴 것 |", "|---|---|---|---|---|"]
        out += [f"| {cell(e.get('date'))} | {cell(e.get('engine'))} | {cell(e.get('query'))}"
                + (f" ({cell(e['note'])})" if e.get("note") else "")
                + f" | {cell(e.get('hits'))} | {cell(', '.join(e.get('kept', [])) or '없음')} |" for e in log]
        out.append("")
    counts = logged_counts(L, work)
    if counts:
        out += ["**수치 기록** (verdict가 인용하는 id)", ""]
        for e in counts:
            if e.get("id", "").startswith("adoption"):
                out.append(f"- {e['id']} ({e['_dir']}, {e.get('date', '')}): 범위 `{e.get('scope')}`, 방법 "
                           f"`{e.get('method')}`, 분모 = {'+'.join(e.get('roles', []))} 논문 → "
                           f"{e.get('numerator')}/{e.get('denominator')}"
                           + (f", 자기 인용 {e['self_citing']}/{e['numerator']}" if e.get("self_citing") is not None else ""))
            else:
                out.append(f"- {e.get('id')} ({e['_dir']}, {e.get('date', '')}): `{e.get('regex')}` → "
                           f"{e.get('matches')}/{e.get('denominator')} ({'+'.join(e.get('roles', []))})")
        out.append("")
    return out


def rows_md(L, links: Links) -> list[str]:
    topic = mode(L) == "topic"
    qn = question_numbers(L) if topic else {}
    out = [f"| 연도 | 연구 | 무엇을 했나 | 앞 세대에서 바꾼 것 | {'질문' if topic else '계열'} | 근거 상태 |",
           "|---|---|---|---|---|---|"]
    for r in L.get("rows", []):
        _, kind, _ = links.of(r.get("openalex"), r.get("url"))
        lane = r.get("lane")
        lane_txt = ((f"Q{qn[lane]}" if lane in qn else lane_name(L["lanes"][lane])) if lane is not None
                    else "리뷰·관점")
        status = STATUS[r["level"]]
        detail = r.get("evidence") or ""
        ver = r.get("version") or VERSION.get(kind, "")
        tail = ", ".join(x for x in (detail, ver) if x)
        out.append(f"| {cell(r['year'])} | {cell(r['work'])} | {cell(r['what'])} | {cell(r['change'])} | "
                   f"{cell(lane_txt)} | {cell(status + (f' ({tail})' if tail else ''))} |")
    return out + [""]


def topic_section(L, data: Path, links: Links, chapter: int, figure: str | None, html_name: str) -> str:
    """Topic mode chapter: the question map, then one row per reader question; empty parts are left out."""
    c = chapter
    xcap = X_CAPTION if any(t == "x" for _, _, t in edge_list(L)) else ""
    out = [f"## {c}. 질문별 연구 지도", ""]
    if L.get("meta", {}).get("lede"):
        out += [L["meta"]["lede"], ""]
    if figure:
        out += [f"![질문 지도. 열은 독자의 질문, 맨 왼쪽 띠는 연구가 평가한 정책·사건, 행은 연도(등간격 아님). "
                f"상자 색은 연구 설계, 각 열 끝의 굵은 칸은 지금의 답. 실선은 직접 계승, 점선은 개념적 연결, "
                f"잔 점선은 연구가 평가한 사건{xcap}. 상자를 누르면 원문이 열립니다 (단독 페이지: {html_name})]"
                f"({figure} \"interactive={html_name}\")", ""]
    parts = [("질문별 지금의 답", questions_table(L) + [""] + events_md(L))]
    if L.get("axes"):
        parts.append(("답이 갈리는 지점", axes_md(L)))
    if L.get("contested"):
        parts.append(("쟁점", contested_md(L)))
    if L.get("trends") or L.get("verdict"):
        parts.append(("주요 흐름", trends_md(L)))
    if L.get("one_line"):
        parts.append(("한 줄 요약", [L["one_line"], ""]))
    if (data / "analysis.json").exists():
        parts.append(("데이터로 본 근거", evidence_md(L, data)))
    method = method_md(L, data.parent, data)
    if method:
        parts.append(("검색 방법과 범위", method))
    if L.get("rows"):
        parts.append(("근거 표와 근거 상태", rows_md(L, links)))
    if L.get("limits"):
        parts.append(("이 분석의 한계", [f"- {x}" for x in L["limits"]] + [""]))
    for k, (title, body) in enumerate(parts, 1):
        out += [f"### {c}.{k} {title}", ""] + body
    return "\n".join(out)


def section(L, data: Path, links: Links, chapter: int, figure: str | None, html_name: str) -> str:
    if mode(L) == "topic":
        return topic_section(L, data, links, chapter, figure, html_name)
    c = chapter
    xcap = X_CAPTION if any(t == "x" for _, _, t in edge_list(L)) else ""
    out = [f"## {c}. 계보와 흐름", ""]
    if L.get("meta", {}).get("lede"):
        out += [L["meta"]["lede"], ""]
    if figure:
        # The HTML report inlines the clickable page in place of the PNG ("interactive=" title).
        out += [f"![계보도. 열은 계열, 행은 연도(등간격 아님). 실선은 직접 계승, 점선은 개념적 연결, "
                f"굵은 선은 인용 네트워크 주경로{xcap}. 상자를 누르면 원문이 열립니다 (단독 페이지: {html_name})]"
                f"({figure} \"interactive={html_name}\")", ""]
    parts = [("갈라진 지점", axes_md(L)), ("단계별 흐름", lanes_table(L) + [""]), ("주요 흐름", trends_md(L))]
    if L.get("one_line"):
        parts.append(("한 줄 요약", [L["one_line"], ""]))
    if L.get("contested"):
        parts.append(("쟁점", contested_md(L)))
    parts.append(("데이터로 본 근거", evidence_md(L, data)))
    method = method_md(L, data.parent, data)
    if method:
        parts.append(("검색 방법과 범위", method))
    parts.append(("계보 표와 근거 상태", rows_md(L, links)))
    if L.get("limits"):
        parts.append(("이 계보의 한계", [f"- {x}" for x in L["limits"]] + [""]))
    for k, (title, body) in enumerate(parts, 1):
        out += [f"### {c}.{k} {title}", ""] + body
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
    if has_disputes(L):
        css += DISPUTE_CSS
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
