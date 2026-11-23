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
LEVEL_KO = {"fulltext": "본문 확인", "excerpts": "발췌 확인", "secondary": "인용 맥락만", "abstract": "초록만 확인",
            "metadata": "미확인"}  # same labels as snu-library-scholarly-access
EDGE_TYPES = {"s", "d", "m", "e", "x"}  # e = evaluates: study -> event; x = disputes/contradicts (study <-> study)
EDGE_BASIS = ("cites", "method", "data", "authors", "conceptual")  # why "X built on Y" (edge objects only)
CONTESTED_STATUS = {"open": "미해결", "resolved": "해소", "partly": "부분 해소"}
MODES = ("lineage", "topic")
# Study design (optional node field): topic mode colours boxes by it; lineage mode only when present.
DESIGN_KO = {"model": "모형·이론", "observational": "관찰자료", "experiment": "실험(무작위)",
             "quasi": "준실험(DiD·합성대조)", "review": "리뷰"}
EDGE_KO = {"s": "직접 확장·변형", "d": "개념적 연결", "m": "인용 네트워크 주경로 (SPC)", "e": "사건 평가 (연구 → 사건)",
           "x": "반박·상충 (≠)"}
# Topic mode: question lanes are wider (their header is a question), the events band is narrower.
Q_LANE_W, EV_LANE_W, X0_TOPIC, PILL_H = 156, 112, 64, 24
PILL_W = EV_LANE_W - 14
ANS_LH, ANS_PAD = 16, 11  # answer cell: line height, inner padding
MAX_QUESTIONS = 5


def md(t):
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escape(t or ""))


def edge_parts(e):
    """(source, target, type) of an edge given as ["a", "b", "s"] or {"from", "to", "type", "basis", "evidence"}."""
    if isinstance(e, dict):
        return e.get("from"), e.get("to"), e.get("type")
    return tuple(e) if isinstance(e, (list, tuple)) and len(e) == 3 else (None, None, None)


def edge_list(L):
    """All edges as (source, target, type) tuples, whichever form lineage.json uses."""
    return [edge_parts(e) for e in L.get("edges", [])]


def edge_meta(e):
    """{'basis': ..., 'evidence': ...} recorded on an edge object ({} for the array form)."""
    return {k: e[k] for k in ("basis", "evidence") if isinstance(e, dict) and e.get(k)}


def has_disputes(L):
    return any(t == "x" for _, _, t in edge_list(L)) or bool(L.get("contested"))


def load(p, default=None):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def mode(L):
    return (L.get("meta") or {}).get("mode") or "lineage"


def is_event(n):
    return n.get("kind") == "event"


def is_events_lane(ln):
    return isinstance(ln, dict) and ln.get("kind") == "events"


def question_numbers(L):
    """{lane index: 1-based question number} for the non-event lanes, in lane order."""
    qs = [i for i, ln in enumerate(L["lanes"]) if not is_events_lane(ln)]
    return {i: k for k, i in enumerate(qs, 1)}


# ---------------------------------------------------------------- validation
def validate(L):
    errs = []
    for k in ("meta", "lanes", "nodes", "edges"):
        if k not in L:
            errs.append(f"missing top-level key '{k}'")
    if errs:
        return errs
    m = mode(L)
    if m not in MODES:
        errs.append(f"meta.mode '{m}' must be one of {list(MODES)}")
    topic = m == "topic"
    lanes = L["lanes"]
    nl = len(lanes)
    if nl > 12:
        errs.append(f"{nl} lanes; the page has colors for at most 12 (consolidate the axes)")
    ev_lanes = [i for i, ln in enumerate(lanes) if is_events_lane(ln)]
    if len(ev_lanes) > 1:
        errs.append(f"{len(ev_lanes)} events lanes {ev_lanes}; put all real-world events in one lane with \"kind\": \"events\"")
    for i, ln in enumerate(lanes):
        if is_events_lane(ln):
            continue
        if topic and not ln.get("question"):
            errs.append(f"lane {i}: topic mode needs a 'question' (the reader's question this lane answers)")
        elif not ln.get("label") and not ln.get("question"):
            errs.append(f"lane {i}: missing 'label'")
    ids = set()
    for n in L["nodes"]:
        ev = is_event(n)
        for k in ("id", "lane", "year", "title") + (() if ev else ("sub",)):
            if k not in n:
                errs.append(f"node {n.get('id', '?')}: missing '{k}'")
        if n.get("id") in ids:
            errs.append(f"duplicate node id {n['id']}")
        ids.add(n.get("id"))
        if n.get("kind") not in (None, "study", "event"):
            errs.append(f"node {n.get('id')}: kind '{n.get('kind')}' must be 'event' (in the events lane) or omitted")
        if not (0 <= n.get("lane", -1) < nl):
            errs.append(f"node {n.get('id')}: lane {n.get('lane')} out of range 0..{nl-1}")
        elif ev and not is_events_lane(lanes[n["lane"]]):
            errs.append(f"node {n.get('id')}: event node in lane {n['lane']}, which is not the events lane "
                        "(\"kind\": \"events\")")
        elif not ev and is_events_lane(lanes[n["lane"]]):
            errs.append(f"node {n.get('id')}: study node in the events lane {n['lane']}; only \"kind\": \"event\" "
                        "nodes go there")
        if not ev and not n.get("openalex") and not n.get("url") and not n.get("unlinked"):
            errs.append(f"node {n.get('id')}: needs 'openalex' (preferred) or 'url' so the box can link to the paper "
                        "(or 'unlinked': '<why no record was found>')")
        if n.get("design") is not None and n["design"] not in DESIGN_KO:
            errs.append(f"node {n.get('id')}: design '{n['design']}' must be one of {list(DESIGN_KO)}")
        fields = (("title", PILL_W - 10, 11),) if ev else (("title", BOX_W - 8, 12), ("sub", BOX_W - 6, 10.5))
        for k, limit, size in fields:
            w = text_px(n.get(k, ""), size)
            if w > limit:
                errs.append(f"node {n.get('id')}: {k} '{n.get(k)}' is ~{w:.0f}px wide, box fits {limit}px; shorten it "
                            f"({width_budget('event' if ev else k)})")
    if len(L["nodes"]) > 50:
        errs.append(f"{len(L['nodes'])} nodes; keep the tree at 20-40 (hard limit 50)")
    by_id = {n.get("id"): n for n in L["nodes"]}
    for raw in L["edges"]:
        s, t, st = edge_parts(raw)
        e = [s, t, st] if isinstance(raw, dict) else raw
        if s not in ids or t not in ids or st not in EDGE_TYPES:
            errs.append(f"bad edge {e}: needs [source_id, target_id, one of s/d/m/e/x] "
                        "or {\"from\", \"to\", \"type\", \"basis\", \"evidence\"}")
            continue
        if isinstance(raw, dict):
            if raw.get("basis") is not None and raw["basis"] not in EDGE_BASIS:
                errs.append(f"edge {s}->{t}: basis '{raw['basis']}' must be one of {list(EDGE_BASIS)}")
            if raw.get("evidence") is not None and not isinstance(raw["evidence"], str):
                errs.append(f"edge {s}->{t}: evidence must be a locator string ('Liang 2023 §II.B' or 'liang2023:p3')")
        s_ev, t_ev = is_event(by_id[s]), is_event(by_id[t])
        if st == "e" and (s_ev or not t_ev):
            errs.append(f"bad edge {e}: an 'e' (evaluates) edge runs from a study node to the event node it evaluates")
        elif st != "e" and (s_ev or t_ev):
            errs.append(f"bad edge {e}: event nodes connect only through 'e' edges (study -> event)")
    for k, c in enumerate(L.get("contested") or []):
        if not isinstance(c, dict) or not c.get("claim"):
            errs.append(f"contested[{k}]: needs 'claim'")
            continue
        for side in ("side_a", "side_b"):
            sd = c.get(side)
            if not isinstance(sd, dict) or not sd.get("nodes"):
                errs.append(f"contested[{k}] ({c['claim'][:30]}): '{side}' needs 'nodes' (node ids) and 'says'")
                continue
            bad = [x for x in sd["nodes"] if x not in ids]
            if bad:
                errs.append(f"contested[{k}] ({c['claim'][:30]}): {side} names unknown node(s) {bad}")
        if c.get("status", "open") not in CONTESTED_STATUS:
            errs.append(f"contested[{k}] ({c['claim'][:30]}): status must be one of {list(CONTESTED_STATUS)}")
    for r in L.get("rows", []):
        if r.get("level") not in LEVEL_KO:
            errs.append(f"row '{r.get('work')}': level must be one of {list(LEVEL_KO)}")
        if r.get("lane") is not None and not (0 <= r["lane"] < nl):
            errs.append(f"row '{r.get('work')}': lane {r['lane']} out of range (use null for reviews/perspectives)")
    return errs


TEXT_SIZE = {"title": 12, "sub": 10.5, "event": 11}
TEXT_LIMIT = {"title": BOX_W - 8, "sub": BOX_W - 6, "event": PILL_W - 10}


def width_budget(field):
    """Human-readable box budget, e.g. 'title: about 9 Hangul or 15 Latin characters'."""
    limit, size = TEXT_LIMIT[field], TEXT_SIZE[field]
    name = "event title" if field == "event" else field
    return f"{name}: about {int(limit // size)} Hangul or {int(limit // (size * 0.6))} Latin characters"


def text_px(t, size):
    """Rough rendered width: CJK/Hangul ~1.0em, other characters ~0.6em."""
    return sum(size * (1.0 if ord(ch) > 0x2E80 else 0.6) for ch in t or "")


def wrap(t, width, size):
    """Greedy line wrap at spaces (long words broken by character), using the text_px estimate."""
    lines, cur = [], ""
    for word in (t or "").split():
        cand = f"{cur} {word}" if cur else word
        if text_px(cand, size) <= width:
            cur = cand
            continue
        if cur:
            lines.append(cur)
        while text_px(word, size) > width and len(word) > 1:
            k = len(word)
            while k > 1 and text_px(word[:k], size) > width:
                k -= 1
            lines.append(word[:k])
            word = word[k:]
        cur = word
    if cur:
        lines.append(cur)
    return lines


def warnings(L):
    w = []
    topic = mode(L) == "topic"
    lanes = L["lanes"]
    if len(lanes) > 10:
        w.append(f"{len(lanes)} lanes (> 8 answer lanes + 2 extras): likely mixed criteria; consolidate again, "
                 "or explain in axes_note why the field is this split")
    per_lane = Counter(n["lane"] for n in L["nodes"])
    for i, ln in enumerate(lanes):
        k = per_lane.get(i, 0)
        if is_events_lane(ln):
            continue
        if topic:
            if k < 2:
                w.append(f"question lane {i} ({lane_name(ln)}) has {k} stud{'y' if k == 1 else 'ies'}: one study is a "
                         "thin answer; add evidence or fold the question into another")
            if not ln.get("answer"):
                w.append(f"question lane {i} ({lane_name(ln)}) has no 'answer': give the current answer with its key "
                         "number (shown in the cell at the end of the lane)")
        elif k < 2:
            w.append(f"lane {i} ({lane_name(ln)}) has {k} node(s): merge into the nearest lane unless it is a precursor lane")
    if topic:
        nq = sum(1 for ln in lanes if not is_events_lane(ln))
        if nq > MAX_QUESTIONS:
            w.append(f"{nq} question lanes (> {MAX_QUESTIONS}): a reader holds 3-5 questions; merge or drop the least asked")
        nodesign = [n["id"] for n in L["nodes"] if not is_event(n) and not n.get("design")]
        if nodesign:
            w.append(f"{len(nodesign)} stud{'y' if len(nodesign) == 1 else 'ies'} without 'design' (box falls back to the "
                     f"lane colour): {', '.join(nodesign)}")
    for n in L["nodes"]:
        if not is_event(n) and not n.get("openalex") and not n.get("url"):
            w.append(f"node {n['id']} has no link (unlinked: {n.get('unlinked')}); its box is not clickable")
    if len(L["nodes"]) > 40:
        w.append(f"{len(L['nodes'])} nodes (> 40): consider dropping minor ones")
    years = {n["id"]: n["year"] for n in L["nodes"]}
    for s, t, st in edge_list(L):
        if st in ("e", "x"):  # a study evaluates an earlier event; a dispute has no direction
            continue
        ys, yt = years[s], years[t]
        if ys > yt:
            w.append(f"edge {s}->{t} goes backward in time ({ys}>{yt}); edges run from the earlier work to the one that builds on it")
    crossings = edges_through_boxes(L)
    # A bold main-path arrow through a box reads as "the main path runs through this paper": flag each.
    # Thin s/d lines crossing boxes are normal in a dense tree; report only their count.
    main = defaultdict(list)
    for s, t, st, via in crossings:
        if st == "m":
            main[(s, t)].append(via)
    for (s, t), vias in main.items():
        w.append(f"main-path edge {s}->{t} is drawn through {', '.join(repr(v) for v in vias)}, so it reads as if "
                 "the main path ran through that paper: reorder nodes of the same year (list order sets the "
                 "stacking), or drop the edge and name the segment in evidence.main_path_note")
    thin = {(s, t, st) for s, t, st, _ in crossings if st != "m"}
    if thin:
        kinds = "s/d/e" if any(st == "e" for _, _, st in thin) else "s/d"
        w.append(f"{len(thin)} thin {kinds} edge(s) cross another box (usually harmless; look at the figure once)")
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
class Geo:
    """Column geometry. Lineage mode: the fixed grid (equal lanes, 2-line labels). Topic mode: the events band
    first and narrower, wider question lanes whose header (Q-number + wrapped question) sets the top margin.
    An events lane in lineage mode is also drawn first and narrower."""

    def __init__(self, L):
        lanes = L["lanes"]
        self.topic = mode(L) == "topic"
        events = [i for i, ln in enumerate(lanes) if is_events_lane(ln)]
        self.order = events + [i for i in range(len(lanes)) if i not in events]
        self.x0 = X0_TOPIC if self.topic else X0
        lane_w = Q_LANE_W if self.topic else LANE_W
        self.x, self.w, x = {}, {}, self.x0
        for i in self.order:
            self.w[i] = EV_LANE_W if i in events else lane_w
            self.x[i] = x
            x += self.w[i]
        self.width = x + 6
        self.head, self.top = {}, TOP
        if self.topic:
            for i in self.order:
                self.head[i] = wrap(lane_name(lanes[i]), self.w[i] - 14, 12.5 * 1.04)[:5]
            self.top = 50 + 16 * (max([len(v) for v in self.head.values()] + [1]) - 1) + 20


def answer_lines(L, geo):
    return {i: wrap(ln["answer"], geo.w[i] - 12 - 2 * ANS_PAD, 12 * 1.06)
            for i, ln in enumerate(L["lanes"]) if geo.topic and not is_events_lane(ln) and ln.get("answer")}


def layout(L, geo=None):
    geo = geo or Geo(L)
    by = defaultdict(lambda: defaultdict(list))
    for n in L["nodes"]:
        by[n["year"]][n["lane"]].append(n)
    pos, rows, y, prev = {}, [], geo.top, None
    for yr in sorted(by):
        if prev is not None and yr - prev > BREAK_GAP:
            rows.append(("break", y))
            y += 26
        h = max(len(v) for v in by[yr].values()) * STACK + 8
        rows.append((yr, y, h))
        for lane, items in by[yr].items():
            for k, n in enumerate(items):
                pos[n["id"]] = (geo.x[lane] + geo.w[lane] / 2, y + 6 + k * STACK)
        y += h
        prev = yr
    ans = answer_lines(L, geo)
    if ans:
        h = max(len(v) for v in ans.values()) * ANS_LH + 2 * ANS_PAD + 18
        rows.append(("answer", y, h))
        y += h
    return pos, rows, y + 10


def box_of(n, pos):
    """(x, y, w, h) of the drawn box; event pills are smaller and centred in the node slot."""
    cx, y = pos[n["id"]]
    if is_event(n):
        return cx - PILL_W / 2, y + (BOX_H - PILL_H) / 2, PILL_W, PILL_H
    return cx - BOX_W / 2, y, BOX_W, BOX_H


def edge_curve(pos, s, t, hs=BOX_W / 2, ht=BOX_W / 2, horizontal=False, side=False):
    """Cubic Bézier (start, control 1, control 2, end) of the edge s -> t, as drawn.
    hs/ht: half widths of the two boxes; horizontal: side-to-side (e edges to the events band);
    side: same column with other boxes in between, so bow out along the right of the column."""
    (sx, sy), (tx, ty) = pos[s], pos[t]
    if side:
        x1, y1, y2 = sx + BOX_W / 2, sy + BOX_H / 2, ty + BOX_H / 2
        return (x1, y1), (x1 + 16, y1), (x1 + 16, y2), (x1, y2)
    if ty > sy and not horizontal:
        x1, y1, x2, y2 = sx, sy + BOX_H, tx, ty
        dy = max(24, (y2 - y1) * 0.5)
        return (x1, y1), (x1, y1 + dy), (x2, y2 - dy), (x2, y2)
    if abs(tx - sx) < 1:
        x1 = sx + BOX_W / 2
        y1, y2 = sy + BOX_H / 2, ty + BOX_H / 2
        return (x1, y1), (x1 + 16, y1), (x1 + 16, y2), (x1, y2)
    left = tx < sx
    x1 = sx - hs if left else sx + hs
    x2 = tx + ht if left else tx - ht
    y1, y2 = sy + BOX_H / 2, ty + BOX_H / 2
    xm = (x1 + x2) / 2
    return (x1, y1), (xm, y1), (xm, y2), (x2, y2)


def edge_geometry(L, pos):
    """[(source, target, type, curve)] for every drawable edge."""
    topic = mode(L) == "topic"
    by = {n["id"]: n for n in L["nodes"]}
    out = []
    for s, t, st in edge_list(L):
        if s not in pos or t not in pos:
            continue
        hs, ht = (PILL_W / 2 if is_event(by[x]) else BOX_W / 2 for x in (s, t))
        side = False
        if topic and st != "e" and by[s]["lane"] == by[t]["lane"] and pos[s][1] != pos[t][1]:
            lo, hi = sorted((pos[s][1], pos[t][1]))
            side = any(n["lane"] == by[s]["lane"] and n["id"] not in (s, t) and lo < pos[n["id"]][1] < hi
                       for n in L["nodes"])
        out.append((s, t, st, edge_curve(pos, s, t, hs, ht, horizontal=st == "e", side=side)))
    return out


X_DASH = "7 2 1.5 2"  # dispute line: long-short dash rhythm, unlike d (4 4) and e (1.5 3.5), so not colour alone
DISPUTE_CSS = """
:root{--dispute:#b42318}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--dispute:#ff7b6b}}
:root[data-theme="dark"]{--dispute:#ff7b6b}
svg .e.dis{stroke:var(--dispute);stroke-width:1.6;stroke-dasharray:7 2 1.5 2}
svg .e.xm{fill:none;stroke:none}
svg .xmk{fill:var(--surface);stroke:var(--dispute);stroke-width:1.3}
svg .xmk-t{fill:var(--dispute);stroke:none;font-family:var(--f-body);font-weight:700;text-anchor:middle;dominant-baseline:central}
"""


def bezier(p0, c1, c2, p3, u):
    """Point at parameter u on the cubic Bézier (p0, c1, c2, p3)."""
    a, b, c, e = (1 - u) ** 3, 3 * (1 - u) ** 2 * u, 3 * (1 - u) * u ** 2, u ** 3
    return (round(a * p0[0] + b * c1[0] + c * c2[0] + e * p3[0], 1),
            round(a * p0[1] + b * c1[1] + c * c2[1] + e * p3[1], 1))


def xmark(cx, cy, r):
    """The marker of a dispute edge: a ringed '≠' (a shape, so it does not rely on colour)."""
    return (f'<circle cx="{cx}" cy="{cy}" r="{r}" class="xmk"/>'
            f'<text x="{cx}" y="{cy}" class="xmk-t" style="font-size:{r * 1.6:.0f}px">≠</text>')


def edges_through_boxes(L, samples=40, margin=3):
    """Edges whose drawn curve crosses a third node's box (reads as if it went through that paper)."""
    pos, _, _ = layout(L)
    hits = []
    for s, t, st, (p0, c1, c2, p3) in edge_geometry(L, pos):
        pts = []
        for k in range(1, samples):
            u = k / samples
            a, b, c, e = (1 - u) ** 3, 3 * (1 - u) ** 2 * u, 3 * (1 - u) * u ** 2, u ** 3
            pts.append((a * p0[0] + b * c1[0] + c * c2[0] + e * p3[0],
                        a * p0[1] + b * c1[1] + c * c2[1] + e * p3[1]))
        for n in L["nodes"]:
            if n["id"] in (s, t):
                continue
            bx, by, bw, bh = box_of(n, pos)
            x0, x1, y0, y1 = bx + margin, bx + bw - margin, by + margin, by + bh - margin
            if any(x0 < px < x1 and y0 < py < y1 for px, py in pts):
                hits.append((s, t, st, n["id"]))
    return hits


def svg_legend(L, W, y0):
    """Legend drawn inside the SVG (so the report PNG carries it): study designs, and in topic mode the edge
    types and the answer cell. Returns (svg fragments, height)."""
    topic = mode(L) == "topic"
    used = {n.get("design") for n in L["nodes"]}
    items = [("head", "연구 설계")] + [("design", d) for d in DESIGN_KO if topic or d in used]
    if not topic and not used - {None}:
        items = []  # lineage mode without designs: the legend only explains the dispute line
    if topic:
        types = [t for t in ("s", "d", "m", "e", "x") if any(e[2] == t for e in edge_list(L))]
        if types:
            items += [("head", "연결선")] + [("edge", t) for t in types]
        if any(ln.get("answer") for ln in L["lanes"] if not is_events_lane(ln)):
            items += [("answer", "")]
    elif any(t == "x" for _, _, t in edge_list(L)):
        items += [("head", "연결선"), ("edge", "x")]
    o, x, y = [], 10, y0 + 20
    for kind, key in items:
        label = {"head": key, "design": DESIGN_KO.get(key, ""), "edge": EDGE_KO.get(key, ""),
                 "answer": "지금의 답 (각 질문 열의 끝)"}[kind]
        lw = text_px(label, 11.5 * 0.92)
        iw = lw + (8 if kind == "head" else 30) + 14
        if x + iw > W - 8 and x > 10:
            x, y = 10, y + 22
        if kind == "head":
            o.append(f'<text x="{x}" y="{y}" class="lg lh">{escape(label)}</text>')
            x += lw + 12
            continue
        if kind == "design":
            o.append(f'<rect x="{x}" y="{y-10}" width="22" height="12" rx="3" '
                     f'style="fill:color-mix(in srgb, var(--d-{key}) 12%, var(--surface));stroke:var(--d-{key})" stroke-width="1.3"/>')
        elif kind == "edge":
            st = {"s": "stroke:var(--edge)", "d": "stroke:var(--edge)", "m": "stroke:var(--accent)",
                  "e": "stroke:var(--muted)", "x": "stroke:var(--dispute)"}[key]
            dash = {"d": ' stroke-dasharray="4 4"', "e": ' stroke-dasharray="1.5 3.5"',
                    "x": f' stroke-dasharray="{X_DASH}"'}.get(key, "")
            o.append(f'<line x1="{x}" x2="{x+22}" y1="{y-4}" y2="{y-4}" style="{st}" '
                     f'stroke-width="{2.4 if key == "m" else 1.6 if key == "x" else 1.4}"{dash}/>')
            if key == "x":
                o.append(xmark(x + 11, y - 4, 5))
        else:
            o.append(f'<rect x="{x}" y="{y-11}" width="22" height="14" rx="4" class="ansbox"/>')
        o.append(f'<text x="{x+30}" y="{y}" class="lg">{escape(label)}</text>')
        x += iw
    return o, y - y0 + 14


def svg(L, links):
    lanes, nodes = L["lanes"], L["nodes"]
    geo = Geo(L)
    topic = geo.topic
    pos, rows, H = layout(L, geo)
    W = geo.width
    legend, lh = ([], 0)
    if topic or any(n.get("design") for n in nodes) or any(t == "x" for _, _, t in edge_list(L)):
        legend, lh = svg_legend(L, W, H)
    has_e = any(e[2] == "e" for e in edge_list(L))
    aria = ("질문 지도: 열은 독자의 질문, 맨 왼쪽 띠는 정책·사건, 행은 연도. 상자를 누르면 원문이 열립니다" if topic
            else "계보도: 열은 계열, 행은 연도. 상자를 누르면 원문이 열립니다")
    o = [f'<svg id="tree" viewBox="0 0 {W} {H + lh}" width="{W}" height="{H + lh}" role="group" '
         f'aria-label="{aria}" xmlns="http://www.w3.org/2000/svg">',
         '<defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
         '<path d="M0,0 L10,5 L0,10 z" style="fill:var(--edge)"/></marker>'
         '<marker id="arm" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
         '<path d="M0,0 L10,5 L0,10 z" style="fill:var(--accent)"/></marker>'
         + ('<marker id="are" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
            '<path d="M0,0 L10,5 L0,10 z" style="fill:var(--muted)"/></marker>' if has_e else "")
         + '</defs>']
    qn = question_numbers(L)
    for k, i in enumerate(geo.order):
        ln = lanes[i]
        x, w = geo.x[i], geo.w[i]
        if k % 2 == 0:
            o.append(f'<rect x="{x}" y="0" width="{w}" height="{H}" style="fill:var(--band)"/>')
        cx = x + w / 2
        o.append(f'<rect x="{x+10}" y="12" width="{w-20}" height="4" rx="2" style="fill:var(--c{i})"/>')
        if topic:
            if i in qn:
                o.append(f'<text x="{cx}" y="32" class="qn">Q{qn[i]}</text>')
            o.extend(f'<text x="{cx}" y="{50 + 16 * j}" class="lt">{escape(line)}</text>'
                     for j, line in enumerate(geo.head[i]))
            continue
        label = ln.get("label") or "정책·사건"
        l1, l2 = (label + ["", ""])[:2] if isinstance(label, list) else (label, "")
        o.append(f'<text x="{cx}" y="36" class="lt">{escape(l1)}</text><text x="{cx}" y="52" class="lt">{escape(l2)}</text>')
    ans = answer_lines(L, geo)
    for r in rows:
        if r[0] == "break":
            y = r[1] + 13
            o.append(f'<line x1="4" x2="{W-4}" y1="{y}" y2="{y}" class="brk"/><text x="8" y="{y-4}" class="yr sm">(시간 생략)</text>')
            continue
        yr, y, h = r
        if yr == "answer":
            o.append(f'<line x1="4" x2="{W-4}" y1="{y}" y2="{y}" class="sep"/>'
                     f'<text x="8" y="{y+30}" class="yr">지금의</text><text x="8" y="{y+47}" class="yr">답</text>')
            ch = h - 18
            for i, lines in ans.items():
                ax, aw = geo.x[i] + 6, geo.w[i] - 12
                ty = y + 9 + (ch - len(lines) * ANS_LH) / 2 + 12
                text = "".join(f'<text x="{ax + aw / 2}" y="{ty + j * ANS_LH}" class="at">{escape(t)}</text>'
                               for j, t in enumerate(lines))
                o.append(f'<g class="ans" data-lane="{i}"><rect x="{ax}" y="{y+9}" width="{aw}" height="{ch}" rx="8" '
                         f'class="ansbox"/>{text}</g>')
            continue
        o.append(f'<line x1="4" x2="{W-4}" y1="{y}" y2="{y}" class="sep"/><text x="8" y="{y+28}" class="yr">{yr}</text>')
    for s, t, st, (p0, c1, c2, p3) in edge_geometry(L, pos):
        d = f"M{p0[0]},{p0[1]} C{c1[0]},{c1[1]} {c2[0]},{c2[1]} {p3[0]},{p3[1]}"
        if st == "x":  # dispute: no direction, so no arrowhead; a ringed ≠ sits at the curve's midpoint
            mx, my = bezier(p0, c1, c2, p3, 0.5)
            o.append(f'<path d="{d}" class="e dis" data-s="{s}" data-t="{t}"/>')
            o.append(f'<g class="e xm" data-s="{s}" data-t="{t}">{xmark(mx, my, 7)}</g>')
            continue
        cls = {"s": "e", "d": "e dash", "m": "e main", "e": "e ev"}[st]
        marker = {"m": "arm", "e": "are"}.get(st, "ar")
        o.append(f'<path d="{d}" class="{cls}" data-s="{s}" data-t="{t}" marker-end="url(#{marker})"/>')
    for n in nodes:
        cx, y = pos[n["id"]]
        x = cx - BOX_W / 2
        url, kind, info = links.of(n.get("openalex"), n.get("url"))
        lane = n["lane"]
        if is_event(n):
            bx, by, bw, bh = box_of(n, pos)
            label = f'{n["title"]} ({n["year"]})' + (". 새 탭에서 출처 열기" if url else "")
            inner = (f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" rx="{bh / 2}" '
                     f'style="fill:color-mix(in srgb, var(--c{lane}) 16%, var(--surface));stroke:var(--c{lane})"/>'
                     f'<text x="{cx}" y="{by + 16}" class="et">{escape(n["title"])}</text>')
            cls = "node ev"
        else:
            label = (f'{n["title"]}, {n["sub"]}. {info.get("venue") or ""}. 새 탭에서 원문 열기' if url
                     else f'{n["title"]}, {n["sub"]}. 연결된 원문 없음')
            cls = "node" + (" key" if n.get("key") else "") + (" pre" if kind == "preprint" else "")
            col = f"var(--d-{n['design']})" if n.get("design") in DESIGN_KO else f"var(--c{lane})"
            inner = (f'<rect x="{x}" y="{y}" width="{BOX_W}" height="{BOX_H}" rx="6" '
                     f'style="fill:color-mix(in srgb, {col} {26 if n.get("key") else 12}%, var(--surface));stroke:{col}"/>'
                     f'<text x="{cx}" y="{y+16}" class="nt">{escape(n["title"])}</text>'
                     f'<text x="{cx}" y="{y+30}" class="ns">{escape(n["sub"])}</text>')
        dz = f' data-design="{escape(n["design"])}"' if n.get("design") in DESIGN_KO else ""
        attrs = f'class="{cls}" data-id="{escape(n["id"])}" data-lane="{lane}"{dz} aria-label="{escape(label)}"'
        if url:
            o.append(f'<a href="{escape(url)}" target="_blank" rel="noopener" {attrs}>{inner}</a>')
        else:
            o.append(f'<g tabindex="0" {attrs}>{inner}</g>')
    o.extend(legend)
    o.append("</svg>")
    return "\n".join(o)


def node_data(L, links):
    out = {}
    for n in L["nodes"]:
        url, kind, info = links.of(n.get("openalex"), n.get("url"))
        fa, na = info.get("first_author") or "", info.get("n_authors") or 1
        d = {"t": info.get("title") or n["title"], "lane": n["lane"], "note": n.get("note", ""),
             "kind": kind, "venue": info.get("venue") or "", "year": info.get("year") or n["year"],
             "cites": info.get("cites"), "by": (fa + (" 외" if na > 1 else "")) if fa else n.get("sub", "")}
        if n.get("design") in DESIGN_KO:
            d["dz"] = DESIGN_KO[n["design"]]
        if is_event(n):
            d["ev"] = True
        if not url:
            d["nolink"] = True
        out[n["id"]] = d
    return out


def lane_name(ln):
    """Lane title: the question when the lane has one (topic mode), else the label."""
    if ln.get("question"):
        return ln["question"]
    label = ln.get("label") or ("정책·사건" if is_events_lane(ln) else "")
    return " ".join(label).replace("· ", "·") if isinstance(label, list) else label


# ---------------------------------------------------------------- sections
def facts(L, work, data):
    c = load(data / "corpus.json", {})
    roles = Counter(r for w in c.values() for r in w.get("_role", []))
    refs = load(data / "refs_meta.json", {})
    n_full = sum(1 for r in L.get("rows", []) if r.get("level") == "fulltext")
    n_read = len(L["meta"].get("papers_read", []))
    seed = L["meta"].get("seed_label", "")
    if mode(L) == "topic":
        nev = sum(1 for n in L["nodes"] if is_event(n))
        parts = [f"독자의 질문 <b>{len(question_numbers(L))}</b>", f"연구 <b>{len(L['nodes']) - nev}편</b>",
                 f"정책·사건 <b>{nev}</b>" if nev else "", f"직접 읽은 원문 <b>{n_read}편</b>" if n_read else "",
                 f"본문 근거가 있는 항목 <b>{n_full}</b>" if n_full else ""]
        return "".join(f"<span>{p}</span>" for p in parts if p)
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


LEVEL_ORDER = ("fulltext", "excerpts", "secondary", "abstract", "metadata")  # strongest first


def node_levels(L):
    """{node id: [row levels]}: a row belongs to a node when it names the same OpenAlex ID or url
    (or the node id in an optional row field 'node')."""
    out = defaultdict(list)
    for n in L.get("nodes", []):
        for r in L.get("rows", []):
            if (r.get("node") == n.get("id") or (n.get("openalex") and r.get("openalex") == n["openalex"])
                    or (n.get("url") and r.get("url") == n["url"])):
                out[n["id"]].append(r.get("level"))
    return out


def best_level(levels):
    """Strongest evidence level among a node's rows, or None when the node has no row."""
    ranked = [lv for lv in LEVEL_ORDER if lv in (levels or [])]
    return ranked[0] if ranked else None


def side_levels(L, side, levels=None):
    """[(node id, best level or None)] for one side of a contested claim."""
    levels = node_levels(L) if levels is None else levels
    return [(nid, best_level(levels.get(nid))) for nid in (side or {}).get("nodes", [])]


def side_level_text(L, side, levels=None):
    """'본문 확인' when every node of the side was read in full, else the weakest level per node."""
    pairs = side_levels(L, side, levels)
    if pairs and all(lv == "fulltext" for _, lv in pairs):
        return LEVEL_KO["fulltext"]
    by = {n["id"]: n for n in L["nodes"]}
    return ", ".join(f'{by[nid].get("sub") or nid}: {LEVEL_KO.get(lv, "표 없음")}' for nid, lv in pairs)


def contested_rows(L):
    """Rows of the 쟁점 table: (claim, A, B, measurement note, status, evidence level), as plain text."""
    by = {n["id"]: n for n in L["nodes"]}
    levels = node_levels(L)
    out = []
    for c in L.get("contested") or []:
        def side(sd):
            who = ", ".join(study_ref(by[x]) if x in by and by[x].get("sub") else x for x in sd.get("nodes", []))
            return f'{sd.get("says", "")} ({who})' if sd.get("says") else who
        lv = f'A: {side_level_text(L, c["side_a"], levels)} / B: {side_level_text(L, c["side_b"], levels)}'
        out.append((c["claim"], side(c["side_a"]), side(c["side_b"]), c.get("metric_note", ""),
                    CONTESTED_STATUS.get(c.get("status", "open"), ""), lv))
    return out


def contested_html(L):
    rows = "".join(f'<tr><td class="w">{md(a)}</td><td>{md(b)}</td><td>{md(c)}</td><td>{md(d) or "–"}</td>'
                   f'<td>{escape(e)}</td><td class="ev">{escape(f)}</td></tr>' for a, b, c, d, e, f in contested_rows(L))
    return ('<div class="scroll"><table><thead><tr><th>쟁점</th><th>A</th><th>B</th><th>측정 차이</th><th>상태</th>'
            '<th>근거 수준</th></tr></thead><tbody>' + rows + "</tbody></table></div>")


def study_ref(n):
    """'Hirsch 2000 [5]': the subtitle plus the report's reference number when the node has one."""
    return n["sub"] + (f' [{n["ref"]}]' if n.get("ref") not in (None, "") else "")


def question_table(L, links):
    """Topic mode: one row per reader question: question, current answer, key studies (linked, with design)."""
    by_lane = defaultdict(list)
    for n in L["nodes"]:
        by_lane[n["lane"]].append(n)
    rows = []
    for i, k in question_numbers(L).items():
        ln = L["lanes"][i]
        studies = []
        for n in sorted(by_lane.get(i, []), key=lambda n: n["year"]):
            url = links.of(n.get("openalex"), n.get("url"))[0]
            name = escape(study_ref(n))
            dz = f' <span class="dz">{escape(DESIGN_KO[n["design"]])}</span>' if n.get("design") in DESIGN_KO else ""
            name = f'<a href="{escape(url)}" target="_blank" rel="noopener">{name}</a>' if url else name
            studies.append(f"<li>{name}{dz}</li>")
        rows.append(f'<tr><td class="w"><span class="chip"><i style="background:var(--c{i})"></i>Q{k}</span> '
                    f'{md(lane_name(ln))}</td><td class="answer">{md(ln.get("answer", "")) or "–"}</td>'
                    f'<td><ul class="studies">{"".join(studies)}</ul></td></tr>')
    return ('<div class="scroll"><table><thead><tr><th>질문</th><th>지금의 답</th><th>핵심 연구 (설계)</th></tr></thead>'
            '<tbody>' + "".join(rows) + "</tbody></table></div>")


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
    lane_col = "질문" if mode(L) == "topic" else "계열"
    out = ['<div class="scroll"><table><thead><tr><th>연도</th><th>연구 (원문 링크)</th><th>무엇을 했나</th>'
           f'<th>앞 세대에서 바꾼 것</th><th>{lane_col}</th><th>확인 수준</th></tr></thead><tbody>']
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
    return query_log(data) + outside_searches(data)


def outside_searches(data):
    """Searches run outside OpenAlex (lineage log-search): engine, query, date, hits, kept."""
    log = load(data / "searches.json", [])
    if not log:
        return ""
    rows = "".join(f'<tr><td class="y">{escape(e.get("date", ""))}</td><td class="w">{escape(e.get("engine", ""))}</td>'
                   f'<td><code class="q">{escape(e.get("query", ""))}</code>'
                   + (f'<span class="src">{escape(e["note"])}</span>' if e.get("note") else "")
                   + f'</td><td class="num">{e.get("hits", 0):,}</td>'
                   f'<td>{escape(", ".join(e.get("kept", [])) or "없음")}</td></tr>' for e in log)
    return ('<div class="col"><h3>OpenAlex 밖 검색 기록</h3></div><div class="scroll"><table class="kw"><thead><tr><th>날짜</th>'
            '<th>검색원</th><th>검색식</th><th>결과</th><th>남긴 것</th></tr></thead><tbody>' + rows + "</tbody></table></div>")


def gold_note(log, data):
    """Where the recall gold set came from, as logged by query-test (independent gold.json or the curated lineage)."""
    src = {e.get("gold_source") for e in log if e.get("gold")}
    g = load(data / "gold.json")
    if src == {"independent"} and g:
        src_txt = g.get("note") or g.get("source")
        origin = f", {escape(src_txt)}" if src_txt else ""
        return f"정답 세트는 이 계보와 독립적으로 고정한 목록(gold.json, {len(g.get('ids', []))}편{origin})입니다."
    return ("정답 세트는 계보도·표의 논문이며, 고전 선행 연구처럼 검색이 아니라 인용으로 들어오는 논문도 포함됩니다."
            + (" 계보에서 뽑은 정답 세트라 재현율은 순환적입니다." if "lineage" in src else ""))


def query_log(data):
    from .searchlog import saturation, unsaturated_ko

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
    cum = f'<p class="note">검색 전략 전체(모든 검색식의 합)의 재현율: <b>{len(union)}/{gold}</b>. {gold_note(log, data)}</p>' if gold else ""
    state = saturation(data)
    if state and not state["saturated"]:
        cum += f'<p class="note"><b>{escape(unsaturated_ko(state))}</b></p>'
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
    qn = question_numbers(L) if mode(L) == "topic" else {}
    for i, ln in enumerate(L["lanes"]):
        name = f"Q{qn[i]}. {lane_name(ln)}" if i in qn else lane_name(ln)
        b.append(f'<button type="button" class="lanebtn" data-lane="{i}" aria-pressed="false">'
                 f'<i style="background:var(--c{i})"></i>{escape(name)}</button>')
    return "".join(b)


def legend_x(L):
    """HTML legend item for dispute edges, only when the tree has one."""
    if not any(t == "x" for _, _, t in edge_list(L)):
        return ""
    return (f'<span><svg width="34" height="14" aria-hidden="true"><line x1="1" x2="33" y1="7" y2="7" '
            f'style="stroke:var(--dispute)" stroke-width="1.6" stroke-dasharray="{X_DASH}"/>{xmark(17, 7, 5)}</svg>'
            f'{EDGE_KO["x"]}</span>')


def contested_section(L):
    if not L.get("contested"):
        return ""
    return ('<section><div class="col"><h2>쟁점</h2><p>같은 질문에 서로 다른 답을 낸 연구들입니다. 근거 수준이 "본문 확인"이 '
            f'아닌 쪽은 초록이나 인용 맥락만으로 판단한 것입니다.</p></div>{contested_html(L)}</section>\n')


def legend_line(style):
    dash = ' stroke-dasharray="4 4"' if style == "d" else ""
    col = "var(--accent)" if style == "m" else "var(--edge)"
    return (f'<svg width="34" height="10" aria-hidden="true"><line x1="1" x2="33" y1="5" y2="5" '
            f'style="stroke:{col}" stroke-width="{2.4 if style == "m" else 1.4}"{dash}/></svg>')


ASSETS = Path(__file__).with_name("assets")


def assets(L, links):
    css = (ASSETS / "page.css").read_text(encoding="utf-8")
    if has_disputes(L):
        css += DISPUTE_CSS
    js = (ASSETS / "page.js").read_text(encoding="utf-8")
    js = (js.replace("__NODES__", json.dumps(node_data(L, links), ensure_ascii=False))
            .replace("__EDGES__", json.dumps([[s, t] for s, t, _ in edge_list(L)]))
            .replace("__LANES__", json.dumps([lane_name(l) for l in L["lanes"]], ensure_ascii=False))
            .replace("__KIND__", json.dumps(KIND_KO, ensure_ascii=False))).replace("</", "<\\/")
    return css, js


def page(L, work, data, xdata, links):
    if mode(L) == "topic":
        return topic_page(L, work, data, xdata, links)
    css, js = assets(L, links)
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
  <div class="legend"><span>{legend_line("s")}직접 확장·변형</span><span>{legend_line("d")}개념적 연결</span><span>{legend_line("m")}인용 네트워크 주경로 (SPC)</span>{legend_x(L)}
  <span><svg width="26" height="14" aria-hidden="true"><rect x="1" y="1" width="24" height="12" rx="3" style="fill:none;stroke:var(--muted)" stroke-dasharray="4 2"/></svg>저널판 없음 (프리프린트 {n_pre}편)</span></div>
</section>
<section class="col"><h2>갈라진 지점</h2>{axes(L)}</section>
<section><div class="col"><h2>단계별 흐름</h2></div>{stage_table(L)}</section>
<section><div class="col"><h2>지금의 주류와 최전선</h2></div>{verdict(L)}<div class="col">{("<h3>주요 흐름</h3>" + trends_html(L)) if (L.get("trends") or L.get("one_line")) else ""}</div></section>
{contested_section(L)}<section class="col"><h2>데이터로 본 근거</h2>{evidence(L, data)}</section>
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


def topic_page(L, work, data, xdata, links):
    """Topic mode: lanes are the reader's questions. Sections without content (no citation corpus,
    no rows, no search log) are left out instead of shown empty."""
    css, js = assets(L, links)
    m = L["meta"]
    n_pre = sum(1 for n in L["nodes"] if links.of(n.get("openalex"), n.get("url"))[1] == "preprint")
    limits = "".join(f"<li>{md(x)}</li>" for x in L.get("limits", []))
    pre = (f'<div class="legend"><span><svg width="26" height="14" aria-hidden="true"><rect x="1" y="1" width="24" '
           f'height="12" rx="3" style="fill:none;stroke:var(--muted)" stroke-dasharray="4 2"/></svg>'
           f'저널판 없음 (프리프린트 {n_pre}편)</span></div>') if n_pre else ""
    sec = [f"""<section>
  <div class="col"><h2>질문 지도</h2>
  <p>열은 이 주제를 읽는 사람이 묻는 질문, 맨 왼쪽 좁은 띠는 연구가 평가한 정책·사건, 행은 연도입니다(연도 간격은 등간격이 아님). 상자 색은 연구 설계이고, 각 질문 열 맨 아래의 굵은 칸이 <b>지금의 답</b>입니다. 상자에 마우스를 올리면 연결된 연구와 사건만 남고 요약이 뜹니다. <b>상자를 누르면 원문이 새 탭에서 열립니다.</b></p></div>
  <div class="controls" role="group" aria-label="질문 강조"><span class="lab">질문 강조</span>{lane_buttons(L)}</div>
  <div class="stage" id="stage"><div class="scroll">{svg(L, links)}</div><div class="tip" id="tip" hidden></div></div>
  {pre}
</section>""", f'<section><div class="col"><h2>질문별 지금의 답</h2></div>{question_table(L, links)}</section>']
    if L.get("axes"):
        sec.append(f'<section class="col"><h2>답이 갈리는 지점</h2>{axes(L)}</section>')
    if L.get("contested"):
        sec.append(contested_section(L))
    if L.get("verdict") or L.get("trends") or L.get("one_line"):
        trends = ("<h3>주요 흐름</h3>" + trends_html(L)) if (L.get("trends") or L.get("one_line")) else ""
        sec.append(f'<section><div class="col"><h2>지금의 결론</h2></div>'
                   f'{verdict(L) if L.get("verdict") else ""}<div class="col">{trends}</div></section>')
    if (data / "analysis.json").exists():
        sec.append(f'<section class="col"><h2>데이터로 본 근거</h2>{evidence(L, data)}</section>')
    if L.get("rows"):
        sec.append('<section><div class="col"><h2>근거 표</h2><p>연구 이름을 누르면 원문이 열립니다. "본문 확인"은 원문의 해당 절이나 '
                   f'페이지를 직접 읽은 항목입니다.</p></div>{table(L, links)}</section>')
    if L.get("vocabulary") or (data / "queries.json").exists() or (data / "searches.json").exists():
        sec.append(f'<section><div class="col"><h2>검색 범위</h2>{vocabulary(L)}</div>{search_log(data)}</section>')
    sec.append(f"""<section class="col">
  <h2>이 분석의 한계</h2><ul>{limits}</ul>
  <h3>다시 그리기</h3>
  <pre class="cmd">scholarly-access-agent lineage check .
scholarly-access-agent lineage page .
scholarly-access-agent lineage report-section . --chapter &lt;n&gt;</pre>
</section>""")
    body = "\n".join(sec)
    return f"""<meta charset="utf-8">
<title>{escape(m["page_title"])}</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans+KR:wght@400;500;600;700&display=swap">
<style>{css}</style>
<div class="wrap">
<header class="col">
  <div class="eyebrow">주제 지도 · {escape(m.get("date", ""))} 기준</div>
  <h1>{md(m["headline"])}</h1>
  <p class="lede">{md(m.get("lede", ""))}</p>
  <div class="facts">{facts(L, work, data)}</div>
</header>
{body}
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

