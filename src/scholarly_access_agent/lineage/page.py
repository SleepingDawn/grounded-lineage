"""Render an interactive lineage page from a curated lineage.json plus the analysis outputs.

Usage:
  lineage page WORK_DIR [--out page.html]
WORK_DIR must contain lineage.json (agent-curated) and data/ (`lineage collect` + `lineage analyze` output).
Optional: data/links.json (lineage links), data/keywords.json (lineage keywords),
          data_x/ (expanded corpus from lineage collect --base data ...).
Checks the lineage.json against the schema and exits with a list of problems if it is invalid.

Text fields accept **bold** only; everything else is escaped.
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from html import escape
from pathlib import Path

LANE_W, X0, BOX_W, BOX_H, STACK, TOP = 132, 58, 120, 38, 46, 74
BREAK_GAP = 8  # insert a "(시간 생략)" break when consecutive node years differ by more than this
KIND_KO = {"journal": "저널", "proceedings": "학회 논문집", "preprint": "프리프린트", "unknown": "OpenAlex"}
LEVEL_KO = {"fulltext": "본문 확인", "abstract": "초록만 확인", "metadata": "미확인"}  # same labels as snu-library-scholarly-access
EDGE_TYPES = {"s", "d", "m"}


def md(t):
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escape(t or ""))


def load(p, default=None):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


# ---------------------------------------------------------------- validation
def validate(L):
    errs = []
    for k in ("meta", "lanes", "nodes", "edges"):
        if k not in L:
            errs.append(f"missing top-level key '{k}'")
    if errs:
        return errs
    nl = len(L["lanes"])
    if nl > 12:
        errs.append(f"{nl} lanes; the page has colors for at most 12 (consolidate the axes)")
    ids = set()
    for n in L["nodes"]:
        for k in ("id", "lane", "year", "title", "sub"):
            if k not in n:
                errs.append(f"node {n.get('id', '?')}: missing '{k}'")
        if n.get("id") in ids:
            errs.append(f"duplicate node id {n['id']}")
        ids.add(n.get("id"))
        if not (0 <= n.get("lane", -1) < nl):
            errs.append(f"node {n.get('id')}: lane {n.get('lane')} out of range 0..{nl-1}")
        if not n.get("openalex") and not n.get("url"):
            errs.append(f"node {n.get('id')}: needs 'openalex' (preferred) or 'url' so the box can link to the paper")
        for k, limit in (("title", BOX_W - 8), ("sub", BOX_W - 6)):
            w = text_px(n.get(k, ""), 12 if k == "title" else 10.5)
            if w > limit:
                errs.append(f"node {n.get('id')}: {k} '{n.get(k)}' is ~{w:.0f}px wide, box fits {limit}px; shorten it")
    if len(L["nodes"]) > 50:
        errs.append(f"{len(L['nodes'])} nodes; keep the tree at 20-40 (hard limit 50)")
    for e in L["edges"]:
        if len(e) != 3 or e[0] not in ids or e[1] not in ids or e[2] not in EDGE_TYPES:
            errs.append(f"bad edge {e}: needs [source_id, target_id, one of s/d/m]")
    for r in L.get("rows", []):
        if r.get("level") not in LEVEL_KO:
            errs.append(f"row '{r.get('work')}': level must be one of {list(LEVEL_KO)}")
        if r.get("lane") is not None and not (0 <= r["lane"] < nl):
            errs.append(f"row '{r.get('work')}': lane {r['lane']} out of range (use null for reviews/perspectives)")
    return errs


def text_px(t, size):
    """Rough rendered width: CJK/Hangul ~1.0em, other characters ~0.6em."""
    return sum(size * (1.0 if ord(ch) > 0x2E80 else 0.6) for ch in t or "")


def warnings(L):
    w = []
    if len(L["lanes"]) > 10:
        w.append(f"{len(L['lanes'])} lanes (> 8 answer lanes + 2 extras): likely mixed criteria; consolidate again, "
                 "or explain in axes_note why the field is this split")
    per_lane = Counter(n["lane"] for n in L["nodes"])
    for i, ln in enumerate(L["lanes"]):
        if per_lane.get(i, 0) < 2:
            w.append(f"lane {i} ({lane_name(ln)}) has {per_lane.get(i, 0)} node(s): merge into the nearest lane unless it is a precursor lane")
    if len(L["nodes"]) > 40:
        w.append(f"{len(L['nodes'])} nodes (> 40): consider dropping minor ones")
    by_year = defaultdict(set)
    for n in L["nodes"]:
        by_year[n["year"]].add(n["id"])
    for s, t, _ in L["edges"]:
        ys = next(n["year"] for n in L["nodes"] if n["id"] == s)
        yt = next(n["year"] for n in L["nodes"] if n["id"] == t)
        if ys > yt:
            w.append(f"edge {s}->{t} goes backward in time ({ys}>{yt}); edges run from the earlier work to the one that builds on it")
    return w


# ---------------------------------------------------------------- links
class Links:
    def __init__(self, links, overrides):
        self.links = dict(links or {})
        for k, v in (overrides or {}).items():
            self.links[k] = {**self.links.get(k, {}), **v}

    def of(self, oa=None, url=None):
        if oa:
            info = self.links.get(oa) or {}
            return info.get("url") or f"https://openalex.org/{oa}", info.get("kind", "unknown"), info
        return url, "unknown", {}


# ---------------------------------------------------------------- diagram
def layout(nodes):
    by = defaultdict(lambda: defaultdict(list))
    for n in nodes:
        by[n["year"]][n["lane"]].append(n)
    pos, rows, y, prev = {}, [], TOP, None
    for yr in sorted(by):
        if prev is not None and yr - prev > BREAK_GAP:
            rows.append(("break", y))
            y += 26
        h = max(len(v) for v in by[yr].values()) * STACK + 8
        rows.append((yr, y, h))
        for lane, items in by[yr].items():
            for k, n in enumerate(items):
                pos[n["id"]] = (X0 + LANE_W * lane + LANE_W / 2, y + 6 + k * STACK)
        y += h
        prev = yr
    return pos, rows, y + 10


def svg(L, links):
    lanes, nodes, edges = L["lanes"], L["nodes"], L["edges"]
    pos, rows, H = layout(nodes)
    W = X0 + LANE_W * len(lanes) + 6
    o = [f'<svg id="tree" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="group" '
         f'aria-label="계보도: 열은 계열, 행은 연도. 상자를 누르면 원문이 열립니다" xmlns="http://www.w3.org/2000/svg">',
         '<defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
         '<path d="M0,0 L10,5 L0,10 z" style="fill:var(--edge)"/></marker>'
         '<marker id="arm" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
         '<path d="M0,0 L10,5 L0,10 z" style="fill:var(--accent)"/></marker></defs>']
    for i, ln in enumerate(lanes):
        x = X0 + LANE_W * i
        if i % 2 == 0:
            o.append(f'<rect x="{x}" y="0" width="{LANE_W}" height="{H}" style="fill:var(--band)"/>')
        cx = x + LANE_W / 2
        o.append(f'<rect x="{x+10}" y="12" width="{LANE_W-20}" height="4" rx="2" style="fill:var(--c{i})"/>')
        l1, l2 = (ln["label"] + ["", ""])[:2] if isinstance(ln["label"], list) else (ln["label"], "")
        o.append(f'<text x="{cx}" y="36" class="lt">{escape(l1)}</text><text x="{cx}" y="52" class="lt">{escape(l2)}</text>')
    for r in rows:
        if r[0] == "break":
            y = r[1] + 13
            o.append(f'<line x1="4" x2="{W-4}" y1="{y}" y2="{y}" class="brk"/><text x="8" y="{y-4}" class="yr sm">(시간 생략)</text>')
            continue
        yr, y, h = r
        o.append(f'<line x1="4" x2="{W-4}" y1="{y}" y2="{y}" class="sep"/><text x="8" y="{y+28}" class="yr">{yr}</text>')
    for s, t, st in edges:
        (sx, sy), (tx, ty) = pos[s], pos[t]
        if ty > sy:
            x1, y1, x2, y2 = sx, sy + BOX_H, tx, ty
            dy = max(24, (y2 - y1) * 0.5)
            d = f"M{x1},{y1} C{x1},{y1+dy} {x2},{y2-dy} {x2},{y2}"
        elif abs(tx - sx) < 1:
            x1 = sx + BOX_W / 2
            y1, y2 = sy + BOX_H / 2, ty + BOX_H / 2
            d = f"M{x1},{y1} C{x1+16},{y1} {x1+16},{y2} {x1},{y2}"
        else:
            left = tx < sx
            x1 = sx - BOX_W / 2 if left else sx + BOX_W / 2
            x2 = tx + BOX_W / 2 if left else tx - BOX_W / 2
            y1, y2 = sy + BOX_H / 2, ty + BOX_H / 2
            d = f"M{x1},{y1} C{(x1+x2)/2},{y1} {(x1+x2)/2},{y2} {x2},{y2}"
        cls = {"s": "e", "d": "e dash", "m": "e main"}[st]
        o.append(f'<path d="{d}" class="{cls}" data-s="{s}" data-t="{t}" marker-end="url(#{"arm" if st == "m" else "ar"})"/>')
    for n in nodes:
        cx, y = pos[n["id"]]
        x = cx - BOX_W / 2
        url, kind, info = links.of(n.get("openalex"), n.get("url"))
        label = f'{n["title"]}, {n["sub"]}. {info.get("venue") or ""}. 새 탭에서 원문 열기'
        cls = "node" + (" key" if n.get("key") else "") + (" pre" if kind == "preprint" else "")
        lane = n["lane"]
        o.append(f'<a href="{escape(url)}" target="_blank" rel="noopener" class="{cls}" data-id="{escape(n["id"])}" '
                 f'data-lane="{lane}" aria-label="{escape(label)}">'
                 f'<rect x="{x}" y="{y}" width="{BOX_W}" height="{BOX_H}" rx="6" '
                 f'style="fill:color-mix(in srgb, var(--c{lane}) {26 if n.get("key") else 12}%, var(--surface));stroke:var(--c{lane})"/>'
                 f'<text x="{cx}" y="{y+16}" class="nt">{escape(n["title"])}</text>'
                 f'<text x="{cx}" y="{y+30}" class="ns">{escape(n["sub"])}</text></a>')
    o.append("</svg>")
    return "\n".join(o)


def node_data(L, links):
    out = {}
    for n in L["nodes"]:
        url, kind, info = links.of(n.get("openalex"), n.get("url"))
        fa, na = info.get("first_author") or "", info.get("n_authors") or 1
        out[n["id"]] = {"t": info.get("title") or n["title"], "lane": n["lane"], "note": n.get("note", ""),
                        "kind": kind, "venue": info.get("venue") or "", "year": info.get("year") or n["year"],
                        "cites": info.get("cites"), "by": (fa + (" 외" if na > 1 else "")) if fa else n["sub"]}
    return out


def lane_name(ln):
    return " ".join(ln["label"]).replace("· ", "·") if isinstance(ln["label"], list) else ln["label"]


# ---------------------------------------------------------------- sections
def facts(L, work, data):
    c = load(data / "corpus.json", {})
    roles = Counter(r for w in c.values() for r in w.get("_role", []))
    refs = load(data / "refs_meta.json", {})
    n_full = sum(1 for r in L.get("rows", []) if r.get("level") == "fulltext")
    n_read = len(L["meta"].get("papers_read", []))
    seed = L["meta"].get("seed_label", "")
    parts = [f"씨앗 <b>{escape(seed)}</b>" if seed else "",
             f"참고문헌 <b>{roles.get('backward', 0)}</b>", f"인용 논문 <b>{roles.get('forward', 0)}</b>",
             f"분야 참고문헌 <b>약 {len(refs):,}</b>" if refs else "",
             f"직접 읽은 원문 <b>{n_read}편</b>", f"본문 근거가 있는 항목 <b>{n_full}</b>"]
    return "".join(f"<span>{p}</span>" for p in parts if p)


def axes(L):
    out = []
    for a in L.get("axes", []):
        out.append(f"<h3>{md(a['question'])}</h3>")
        if a.get("items"):
            out.append("<ul>" + "".join(f"<li><b>{escape(i['label'])}</b>: {md(i['text'])}</li>" for i in a["items"]) + "</ul>")
        if a.get("text"):
            out.append(f"<p>{md(a['text'])}</p>")
    if L.get("axes_note"):
        out.append(f'<p class="note">{md(L["axes_note"])}</p>')
    return "\n".join(out)


def verdict(L):
    cards = []
    for v in L.get("verdict", []):
        pts = "".join(f"<li>{md(p)}</li>" for p in v.get("points", []))
        cards.append(f'<div><div class="tag">{escape(v["tag"])}</div><h3>{md(v["title"])}</h3><ul>{pts}</ul></div>')
    return f'<div class="verdict now">{"".join(cards)}</div>'


def stage_table(L):
    """Lane-by-lane stage table (the text flow), same content as the report chapter's table."""
    by_lane = defaultdict(list)
    for n in L["nodes"]:
        by_lane[n["lane"]].append(n)
    rows = []
    for i, ln in enumerate(L["lanes"]):
        nodes = sorted(by_lane.get(i, []), key=lambda n: n["year"])
        if not nodes:
            continue
        y0, y1 = nodes[0]["year"], nodes[-1]["year"]
        reps = "; ".join(f'{n["title"]} ({n["sub"]})' for n in nodes[:5]) + (" 외" if len(nodes) > 5 else "")
        rows.append(f'<tr><td class="w"><span class="chip"><i style="background:var(--c{i})"></i>{escape(lane_name(ln))}</span></td>'
                    f'<td class="y">{y0 if y0 == y1 else f"{y0}–{y1}"}</td><td>{md(ln.get("how", "")) or "–"}</td>'
                    f'<td>{escape(reps)}</td><td>{md(ln.get("limit", "")) or "–"}</td></tr>')
    return ('<div class="scroll"><table><thead><tr><th>계열</th><th>시기</th><th>방식</th><th>대표 연구</th>'
            '<th>핵심 한계</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>")


def trends_html(L):
    items = []
    for t in L.get("trends", []):
        pts = "".join(f"<li>{md(p)}</li>" for p in t.get("points", []))
        items.append(f"<li><b>{md(t['title'])}</b><ul>{pts}</ul></li>")
    out = f"<ol>{''.join(items)}</ol>" if items else ""
    if L.get("one_line"):
        out += f'<p class="oneline">{md(L["one_line"])}</p>'
    return out


def parse_desc(s):
    p = [x.strip() for x in s.split("|")]
    return {"label": p[0], "title": p[2] if len(p) > 2 else "", "id": p[-1]}


def evidence(L, data):
    an = load(data / "analysis.json")
    if not an:
        return "<p class='note'>analysis.json이 없습니다. analyze.py를 먼저 실행하세요.</p>"
    ev = L.get("evidence", {})
    out = []
    tail = ev.get("main_path_tail", 8)
    mp = [parse_desc(s) for s in an["main_path"]][-tail:]
    out.append("<h3>주경로 분석 (SPC): 마지막 구간</h3>")
    out.append('<p class="path">' + ' <span class="arr">→</span> '.join(
        f'<a href="https://openalex.org/{escape(m["id"])}" target="_blank" rel="noopener">{escape(m["label"])}</a> '
        f'{escape(m["title"][:60])}' for m in mp) + "</p>")
    if ev.get("main_path_note"):
        out.append(f'<p class="note">{md(ev["main_path_note"])}</p>')
    out.append("<h3>RPYS: 참고문헌 연도 분포의 봉우리</h3><ul>")
    keep = ev.get("rpys_years")  # agent-chosen meaningful peaks; generic-method peaks left out
    peaks = sorted(p for p in an["rpys_peaks"] if p[0] in keep) if keep else an["rpys_peaks"][:8]
    for y, n, dev, tops in peaks:
        refs = "; ".join(f'{escape(t["label"])}: {escape(t["title"][:60])}' for t in map(parse_desc, tops[:3]))
        out.append(f'<li><span class="num">{y}</span> {refs}</li>')
    out.append("</ul>")
    if ev.get("rpys_note"):
        out.append(f'<p class="note">{md(ev["rpys_note"])}</p>')
    labels = ev.get("cluster_labels", {})
    out.append("<h3>인용 군집 (서지 결합 + Louvain)</h3><ul>")
    for c in an["clusters"]:
        lab = labels.get(str(c["cluster"])) or ", ".join(c["words"][:4])
        ex = "; ".join(m[2][:50] for m in c["top_members"][:2])
        out.append(f'<li><b>{escape(lab)}</b> ({c["size"]}편, {escape(c["years"])}): {escape(ex)}</li>')
    out.append("</ul>")
    fy = an.get("forward_by_year", {})
    if fy:
        out.append('<p class="note">씨앗 인용 논문 연도별: ' + ", ".join(f"{k}년 {v}편" for k, v in sorted(fy.items())) + "</p>")
    return "\n".join(out)


def table(L, links):
    out = ['<div class="scroll"><table><thead><tr><th>연도</th><th>연구 (원문 링크)</th><th>무엇을 했나</th>'
           '<th>앞 세대에서 바꾼 것</th><th>계열</th><th>확인 수준</th></tr></thead><tbody>']
    for r in L.get("rows", []):
        url, kind, info = links.of(r.get("openalex"), r.get("url"))
        lane = r.get("lane")
        src = KIND_KO[kind] + (" · " + info["venue"] if info.get("venue") else "")
        chip = (f'<i style="background:var(--c{lane})"></i>{escape(lane_name(L["lanes"][lane]))}' if lane is not None
                else '<i style="background:var(--muted)"></i>리뷰·관점')
        out.append(f'<tr><td class="y">{escape(str(r["year"]))}</td><td class="w"><a href="{escape(url)}" target="_blank" '
                   f'rel="noopener">{escape(r["work"])}</a><span class="src">{escape(src)}</span></td>'
                   f'<td>{md(r["what"])}</td><td>{md(r["change"])}</td><td><span class="chip">{chip}</span></td>'
                   f'<td class="ev"><b>{LEVEL_KO[r["level"]]}</b> '
                   f'{escape(r.get("evidence", ""))}</td></tr>')
    out.append("</tbody></table></div>")
    return "\n".join(out)


def keyword_table(data):
    kws = load(data / "keywords.json", [])
    if not kws:
        return "<p class='note'>lineage keywords를 아직 실행하지 않았습니다.</p>"
    rows = []
    for k in kws:
        if k["top50"] == 0:
            continue
        fit = k.get("top50_on_topic", k["top50"]) / k["top50"]
        ex = k["examples_new"][0] if k["examples_new"] else None
        ex_html = (f'<a href="https://openalex.org/{ex["id"]}" target="_blank" rel="noopener">{escape(ex["title"][:80])}</a>'
                   f' <span class="src">{ex["year"]} · 인용 {ex["cites"]}</span>') if ex else ""
        rows.append(f'<tr><td class="w">{escape(k["keyword"])}</td><td class="num">{k["docs_in_corpus"]}</td>'
                    f'<td class="num">{k["openalex_hits"]:,}</td>'
                    f'<td>{meter(fit)}<span class="num">{k.get("top50_on_topic", "–")}/{k["top50"]}</span></td>'
                    f'<td class="num">{k["top50_new"]}</td><td>{ex_html}</td></tr>')
    return ('<div class="scroll"><table class="kw"><thead><tr><th>후보 키워드</th><th>코퍼스 안 문서</th><th>OpenAlex 일치</th>'
            '<th>분야 적합 (인용 기준)</th><th>새 분야 논문</th><th>새 논문 예시 (인용 최다)</th></tr></thead><tbody>'
            + "\n".join(rows) + "</tbody></table></div>")


def meter(x):
    return f'<span class="meter"><i style="width:{max(0, min(1, x))*100:.0f}%"></i></span>'


def vocabulary(L):
    v = L.get("vocabulary") or []
    if not v:
        return ""
    rows = []
    for c in v:
        terms = ", ".join(escape(t) for t in c.get("terms", []))
        noise = ", ".join(escape(t) for t in c.get("noise", []))
        rows.append(f'<tr><td class="w">{escape(c["concept"])}</td><td>{terms}</td><td>{noise or "–"}</td>'
                    f'<td class="ev">{md(c.get("source", ""))}</td></tr>')
    return ('<h3>검색 어휘 (개념 블록)</h3><div class="scroll"><table class="kw"><thead><tr><th>개념</th><th>같은 뜻의 용어 (OR)</th>'
            '<th>제외어 (NOT)</th><th>어디서 찾았나</th></tr></thead><tbody>' + "\n".join(rows) + "</tbody></table></div>")


def search_log(data):
    log = load(data / "queries.json", [])
    if not log:
        return ""
    rows = []
    for e in log:
        rec = f'{e["gold_found"]}/{e["gold"]}' if e.get("gold") else "–"
        sat = ' <span class="src">포화</span>' if e.get("saturated") else ""
        rows.append(f'<tr><td class="y">{escape(e["date"])}</td><td><b>{escape(e.get("label") or "")}</b>'
                    f'<code class="q">{escape(e["query"])}</code></td><td class="num">{e["hits"]:,}</td>'
                    f'<td>{meter(e["precision"])}<span class="num">{e["precision"]:.0%}</span></td>'
                    f'<td class="num">{rec}</td><td class="num">{e["new_on_topic"]}{sat}</td></tr>')
    gold = max((e.get("gold") or 0) for e in log)
    union = set()
    for e in log:
        union |= set(e.get("gold_found_ids", []))
    cum = f'<p class="note">검색 전략 전체(모든 검색식의 합)의 재현율: <b>{len(union)}/{gold}</b>. 정답 세트는 계보도·표의 논문이며, 고전 선행 연구처럼 검색이 아니라 인용으로 들어오는 논문도 포함됩니다.</p>' if gold else ""
    return ('<h3>검색 기록</h3><div class="scroll"><table class="kw"><thead><tr><th>날짜</th><th>검색식</th><th>일치</th>'
            '<th>정밀도 (분야 적합)</th><th>재현율 (정답 세트)</th><th>새 분야 논문</th></tr></thead><tbody>'
            + "\n".join(rows) + "</tbody></table></div>" + cum)


def expansion_summary(L, data, xdata):
    cx = load(xdata / "corpus.json") if xdata else None
    if not cx:
        why = L["meta"].get("expansion_note") or "이번에는 범위를 넓히지 않았습니다."
        return f"<p class='note'>{md(why)}</p>"
    base = load(data / "corpus.json", {})
    known = set(base) | set(load(data / "refs_meta.json", {}))
    focus = re.compile(L["meta"].get("focus_regex") or ".", re.I)
    new = sorted((w for k, w in cx.items() if k not in known and focus.search(w.get("title") or "")),
                 key=lambda w: -(w.get("cited_by_count") or 0))
    items = []
    for w in new[:12]:
        url = w.get("doi") or w["id"]
        tag = ", ".join(sorted({("키워드: " + r.split(":", 1)[1]) if r.startswith("keyword:") else "조상의 후속 연구"
                                for r in w["_role"] if r.startswith("keyword:") or r == "ancestor-forward"}))
        items.append(f'<li><a href="{escape(url)}" target="_blank" rel="noopener">{escape(w["title"])}</a>'
                     f' <span class="src">{w.get("publication_year")} · 인용 {w.get("cited_by_count")} · {escape(tag)}</span></li>')
    n_add = sum(1 for k in cx if k not in base)
    n_new = sum(1 for k in cx if k not in known)
    in_tree = {n.get("openalex") for n in L["nodes"]}
    shown = sum(1 for w in new if w["id"].rsplit("/", 1)[-1] in in_tree)
    return (f'<div class="facts"><span>기존 코퍼스 <b>{len(base)}</b></span><span>확장 후 <b>{len(cx)}</b></span>'
            f'<span>추가된 논문 <b>{n_add}</b></span><span>기존 코퍼스가 인용조차 안 한 논문 <b>{n_new}</b></span>'
            f'<span>그중 주제 관련 제목 <b>{len(new)}</b></span><span>계보도에 반영 <b>{shown}</b></span></div>'
            f'<h3>확장으로 처음 잡힌 주제 관련 논문 (인용 상위 12)</h3><ol class="newlist">{"".join(items)}</ol>')


def lane_buttons(L):
    b = ['<button type="button" class="lanebtn" data-lane="all" aria-pressed="true">전체</button>']
    for i, ln in enumerate(L["lanes"]):
        b.append(f'<button type="button" class="lanebtn" data-lane="{i}" aria-pressed="false">'
                 f'<i style="background:var(--c{i})"></i>{escape(lane_name(ln))}</button>')
    return "".join(b)


def legend_line(style):
    dash = ' stroke-dasharray="4 4"' if style == "d" else ""
    col = "var(--accent)" if style == "m" else "var(--edge)"
    return (f'<svg width="34" height="10" aria-hidden="true"><line x1="1" x2="33" y1="5" y2="5" '
            f'style="stroke:{col}" stroke-width="{2.4 if style == "m" else 1.4}"{dash}/></svg>')


ASSETS = Path(__file__).with_name("assets")


def page(L, work, data, xdata, links):
    css = (ASSETS / "page.css").read_text(encoding="utf-8")
    js = (ASSETS / "page.js").read_text(encoding="utf-8")
    js = (js.replace("__NODES__", json.dumps(node_data(L, links), ensure_ascii=False))
            .replace("__EDGES__", json.dumps([[s, t] for s, t, _ in L["edges"]]))
            .replace("__LANES__", json.dumps([lane_name(l) for l in L["lanes"]], ensure_ascii=False))
            .replace("__KIND__", json.dumps(KIND_KO, ensure_ascii=False))).replace("</", "<\\/")
    m = L["meta"]
    n_pre = sum(1 for n in L["nodes"] if links.of(n.get("openalex"), n.get("url"))[1] == "preprint")
    seeds = " ".join(m.get("seed_ids", [])) or "W..."
    limits = "".join(f"<li>{md(x)}</li>" for x in L.get("limits", []))
    return f"""<meta charset="utf-8">
<title>{escape(m["page_title"])}</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans+KR:wght@400;500;600;700&display=swap">
<style>{css}</style>
<div class="wrap">
<header class="col">
  <div class="eyebrow">선행연구 계보 · {escape(m.get("date", ""))} 기준</div>
  <h1>{md(m["headline"])}</h1>
  <p class="lede">{md(m.get("lede", ""))}</p>
  <div class="facts">{facts(L, work, data)}</div>
</header>
<section>
  <div class="col"><h2>계보도</h2>
  <p>열은 계열, 행은 연도입니다(연도 간격은 등간격이 아님). 상자에 마우스를 올리면 그 논문의 조상과 후손 줄기만 남고 요약이 뜹니다. <b>상자를 누르면 원문이 새 탭에서 열립니다.</b> 저널판이 있으면 저널판으로, 없으면 프리프린트로 연결됩니다.</p></div>
  <div class="controls" role="group" aria-label="계열 강조"><span class="lab">계열 강조</span>{lane_buttons(L)}</div>
  <div class="stage" id="stage"><div class="scroll">{svg(L, links)}</div><div class="tip" id="tip" hidden></div></div>
  <div class="legend"><span>{legend_line("s")}직접 확장·변형</span><span>{legend_line("d")}개념적 연결</span><span>{legend_line("m")}인용 네트워크 주경로 (SPC)</span>
  <span><svg width="26" height="14" aria-hidden="true"><rect x="1" y="1" width="24" height="12" rx="3" style="fill:none;stroke:var(--muted)" stroke-dasharray="4 2"/></svg>저널판 없음 (프리프린트 {n_pre}편)</span></div>
</section>
<section class="col"><h2>갈라진 지점</h2>{axes(L)}</section>
<section><div class="col"><h2>단계별 흐름</h2></div>{stage_table(L)}</section>
<section><div class="col"><h2>지금의 주류와 최전선</h2></div>{verdict(L)}<div class="col">{("<h3>주요 흐름</h3>" + trends_html(L)) if (L.get("trends") or L.get("one_line")) else ""}</div></section>
<section class="col"><h2>데이터로 본 근거</h2>{evidence(L, data)}</section>
<section><div class="col"><h2>계보 표</h2><p>연구 이름을 누르면 원문이 열립니다. "본문 확인"은 원문의 해당 절이나 페이지를 직접 읽은 항목입니다.</p></div>{table(L, links)}</section>
<section>
  <div class="col"><h2>깊이 넓히기</h2>
  <p>코퍼스는 씨앗 논문의 인용 이웃이라 씨앗을 인용하지 않은 계열과, 같은 개념을 다른 이름으로 부르는 연구가 빠집니다. 리뷰에서 모은 동의어로 검색식을 짜고, 정밀도·재현율·새 논문 수로 검증한 뒤 범위를 넓힙니다. "분야 적합"은 결과가 이 분야의 핵심 논문을 인용하는지로 판정하므로 용어 선택과 무관합니다.</p></div>
  <div class="col">{vocabulary(L)}</div>
  {search_log(data)}
  <div class="col"><h3>태그에서 뽑은 후보 키워드</h3></div>
  {keyword_table(data)}
  <div class="col"><h3>확장 결과</h3>{expansion_summary(L, data, xdata)}</div>
</section>
<section class="col">
  <h2>이 분석의 한계</h2><ul>{limits}</ul>
  <h3>다시 돌리기</h3>
  <pre class="cmd">scholarly-access-agent lineage collect data {escape(seeds)}
scholarly-access-agent lineage analyze data
scholarly-access-agent lineage keywords data '&lt;context&gt;' 15 5 '&lt;focus regex&gt;'
scholarly-access-agent lineage query-test data '&lt;concept-block query&gt;' --gold-from-lineage lineage.json --label '&lt;name&gt;'
scholarly-access-agent lineage collect data_x {escape(seeds)} --base data --query '&lt;tested query&gt;' --ancestors 6 --focus '&lt;regex&gt;'
scholarly-access-agent lineage analyze data_x 2
scholarly-access-agent lineage links data/links.json --from-lineage lineage.json
scholarly-access-agent lineage page .</pre>
</section>
</div>
<script>{js}</script>
"""


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("work_dir")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    work = Path(a.work_dir)
    L = load(work / "lineage.json")
    if L is None:
        sys.exit(f"{work/'lineage.json'} not found")
    errs = validate(L)
    if errs:
        sys.exit("lineage.json problems:\n  - " + "\n  - ".join(errs))
    for w in warnings(L):
        print("warning:", w)
    data = work / L["meta"].get("data_dir", "data")
    xd = L["meta"].get("expanded_dir")
    xdata = work / xd if xd else None
    links = Links(load(data / "links.json", {}), L.get("link_overrides"))
    missing = [n["openalex"] for n in L["nodes"] if n.get("openalex") and n["openalex"] not in links.links]
    if missing:
        print("warning: no resolved link for", " ".join(missing), "-> run `lineage links`; falling back to OpenAlex pages")
    out = Path(a.out) if a.out else work / (L["meta"].get("slug", "lineage") + ".html")
    out.write_text(page(L, work, data, xdata, links), encoding="utf-8")
    print("wrote", out)

