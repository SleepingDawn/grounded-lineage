"""matrix: gap-matrix heatmap from ideas/matrix.json, or the first table of ideas/matrix.md (then written to
matrix.json so later runs read structured data)."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .common import LIGHT, VizError, finish, load_records, study_label, wrap_label

# state -> (glyph, fill, ink, legend label). Glyph + colour, so the state reads without colour vision.
STATES = {
    "covered": ("●", "#0072B2", "light", "● covered · 충분"),
    "contested": ("◐", "#D55E00", "light", "◐ contested · 상충"),
    "thin": ("◔", "#F0E442", "dark", "◔ thin · 빈약"),
    "empty-searched": ("○", "#999999", "dark", "○ empty-searched · 찾았으나 없음"),
    "empty-unsearched": ("?", LIGHT["grid"], "fg", "? empty-unsearched · 미검색"),
}
STATE_RE = re.compile(r"empty-unsearched|empty-searched|contested|covered|thin", re.IGNORECASE)
REF_RE = re.compile(r"\[([^\[\]]+?)\](?!\()")
CARD_RE = re.compile(r"\bC\d+\b")
TOKEN_RE = re.compile(r"[A-Za-z0-9가-힣]+")


def _cells(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", s)]


def _clean(text: str) -> str:
    return re.sub(r"\*\*|__|`", "", text).strip()


def state_of(text: str) -> str | None:
    m = STATE_RE.search(_clean(text))
    return m.group(0).lower() if m else None


def refs_of(text: str) -> list[str]:
    out = []
    for m in REF_RE.finditer(text):
        for part in re.split(r"[,;]\s*", m.group(1)):
            part = part.strip()
            if part and part not in out:
                out.append(part)
    return out


def parse_matrix_md(text: str) -> dict:
    """First Markdown table: first column = row labels, header = column labels, cell = state keyword + [refs]."""
    lines = text.splitlines()
    title = ""
    start = None
    for i, line in enumerate(lines):
        if line.lstrip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{3,}", lines[i + 1]):
            start = i
            break
        if line.startswith("#"):
            title = line.lstrip("#").strip()
    if start is None:
        raise VizError("no Markdown table found in matrix.md")
    header = [_clean(c) for c in _cells(lines[start])]
    corner, columns = header[0], header[1:]
    row_axis, col_axis = "행", "열"
    if "\\" in corner or "/" in corner:
        a, b = re.split(r"\s*[\\/]\s*", corner, maxsplit=1)
        row_axis, col_axis = a.strip() or row_axis, b.strip() or col_axis
    rows, cells = [], []
    for line in lines[start + 2:]:
        if not line.lstrip().startswith("|"):
            break
        parts = _cells(line)
        if not parts or not _clean(parts[0]):
            continue
        row = _clean(parts[0])
        rows.append(row)
        for col, raw in zip(columns, parts[1:] + [""] * (len(columns) - len(parts) + 1)):
            cells.append({"row": row, "column": col, "state": state_of(raw) or "empty-unsearched",
                          "state_given": state_of(raw) is not None, "refs": refs_of(raw),
                          "cards": CARD_RE.findall(_clean(raw)), "text": _clean(raw)})
    return {"title": title, "row_axis": row_axis, "column_axis": col_axis, "rows": rows, "columns": columns,
            "cells": cells}


def _tokens(label: str) -> set[str]:
    return {t.lower() for t in TOKEN_RE.findall(label) if len(t) >= 2}


def _score(label: str, text: str) -> int:
    low = text.lower()
    return sum(1 for t in _tokens(label) if t in low)


def parse_cards(text: str) -> list[dict]:
    """[{id, title, gap, state}] from cards.md headings '## C1 — title' and their '**Gap:**' line."""
    cards, cur = [], None
    for line in text.splitlines():
        m = re.match(r"^#{2,3}\s*(C\d+)\b\s*[—–:-]?\s*(.*)$", line.strip())
        if m:
            cur = {"id": m.group(1), "title": m.group(2).strip(), "gap": "", "state": None}
            cards.append(cur)
            continue
        if cur is not None and re.search(r"\bGap\b", line) and not cur["gap"]:
            gap = re.sub(r"^.*?Gap:?\**:?\s*", "", line.strip())
            cur["gap"] = gap
            cur["state"] = state_of(gap)
    return cards


def place_cards(matrix: dict, cards: list[dict]) -> list[str]:
    """Put each card on the cell(s) its Gap line names ("row × column", either order); returns unplaced ids."""
    unplaced = []
    by_key = {(c["row"], c["column"]): c for c in matrix["cells"]}
    for card in cards:
        gap = re.sub(r"\(.*?\)|`[^`]*`|\[[^\]]*\]", " ", card["gap"]).split(",")[0].split("+")[0]
        parts = re.split(r"\s*[×x✕]\s*", gap, maxsplit=1)
        if len(parts) != 2 or any(card["id"] in c["cards"] for c in matrix["cells"]):
            if not any(card["id"] in c["cards"] for c in matrix["cells"]):
                unplaced.append(card["id"])
            continue
        best, picks = 0, []
        for a, b in ((parts[0], parts[1]), (parts[1], parts[0])):
            rs = {r: _score(r, a) for r in matrix["rows"]}
            cs = {c: _score(c, b) for c in matrix["columns"]}
            rmax, cmax = max(rs.values(), default=0), max(cs.values(), default=0)
            if rmax and cmax and rmax + cmax > best:
                best = rmax + cmax
                picks = [(r, c) for r in rs if rs[r] == rmax for c in cs if cs[c] == cmax]
        if card.get("state"):
            same = [p for p in picks if by_key.get(p, {}).get("state") == card["state"]]
            picks = same or picks
        if not picks or len(picks) > 2:
            unplaced.append(card["id"])
            continue
        for p in picks:
            if p in by_key and card["id"] not in by_key[p]["cards"]:
                by_key[p]["cards"].append(card["id"])
    return unplaced


def load_matrix(topic: Path, write_json: bool = True) -> tuple[dict, str, list[str]]:
    """(matrix, source description, notes). Writes ideas/matrix.json when it was parsed from matrix.md."""
    ideas = topic / "ideas"
    j, md = ideas / "matrix.json", ideas / "matrix.md"
    notes: list[str] = []
    if j.exists():
        try:
            data = json.loads(j.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise VizError(f"ideas/matrix.json is not valid JSON: {exc}") from exc
        if not isinstance(data, dict) or not data.get("cells"):
            raise VizError("ideas/matrix.json has no cells")
        data.setdefault("rows", list(dict.fromkeys(c["row"] for c in data["cells"])))
        data.setdefault("columns", list(dict.fromkeys(c["column"] for c in data["cells"])))
        return data, "ideas/matrix.json", notes
    if not md.exists():
        raise VizError(f"neither ideas/matrix.json nor ideas/matrix.md under {topic}")
    data = parse_matrix_md(md.read_text(encoding="utf-8"))
    cards_md = ideas / "cards.md"
    if cards_md.exists():
        unplaced = place_cards(data, parse_cards(cards_md.read_text(encoding="utf-8")))
        data["unplaced_cards"] = unplaced
        if unplaced:
            notes.append(f"표 밖 공백 카드 {', '.join(unplaced)}")
    data["source"] = "ideas/matrix.md (first table)"
    if write_json:
        j.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        notes.append("ideas/matrix.json 작성")
    return data, "ideas/matrix.md", notes


def _short(label: str) -> str:
    s = re.sub(r"\s*\([^()]*\)\s*$", "", label).strip()
    return s or label


def build(topic: Path, write_json: bool = True) -> tuple[dict, dict]:
    matrix, source, notes = load_matrix(topic, write_json)
    titles = {stem: f"{study_label(r, stem)} — {str(r.get('title') or '')[:70]}" for stem, r in load_records(topic)}
    rows_w = {r: wrap_label(_short(r), 9) for r in matrix["rows"]}
    cols_w = {c: wrap_label(_short(c), 6) for c in matrix["columns"]}
    values = []
    for c in matrix["cells"]:
        state = c.get("state") if c.get("state") in STATES else "empty-unsearched"
        glyph, _, ink, label = STATES[state]
        cards = " ".join(c.get("cards") or [])
        papers = "; ".join(titles.get(r, r) for r in c.get("refs") or []) or "-"
        values.append({"row": rows_w.get(c["row"], c["row"]), "col": cols_w.get(c["column"], c["column"]),
                       "row_full": c["row"], "col_full": c["column"], "state": label, "ink": ink,
                       "mark": f"{glyph} {cards}".strip(), "cards": cards or "-", "papers": papers,
                       "note": (c.get("text") or "-")[:300]})
    if not values:
        raise VizError("matrix has no cells")
    x = {"field": "col", "type": "nominal", "sort": [cols_w[c] for c in matrix["columns"]],
         "title": None,
         "scale": {"paddingInner": 0.06},
         "axis": {"orient": "bottom", "labelAngle": 0, "labelExpr": "split(datum.value, '\\n')", "labelLimit": 200,
                  "domain": False, "ticks": False, "labelPadding": 4}}
    y = {"field": "row", "type": "nominal", "sort": [rows_w[r] for r in matrix["rows"]],
         "title": None,
         "scale": {"paddingInner": 0.06},
         "axis": {"labelExpr": "split(datum.value, '\\n')", "labelLimit": 120, "domain": False, "ticks": False,
                  "labelAlign": "right"}}
    tooltip = [{"field": "row_full", "title": matrix.get("row_axis") or "행"},
               {"field": "col_full", "title": matrix.get("column_axis") or "열"},
               {"field": "state", "title": "상태"}, {"field": "cards", "title": "카드"},
               {"field": "papers", "title": "논문"}, {"field": "note", "title": "칸 내용"}]
    spec = finish({
        "width": "container", "height": 58 * len(matrix["rows"]), "autosize": {"type": "fit-x", "contain": "padding"},
        "title": {"text": f"{matrix.get('row_axis') or '행'} ↓  ×  {matrix.get('column_axis') or '열'} →",
                  "fontSize": 12, "anchor": "middle", "offset": 6},
        "data": {"values": values},
        "encoding": {"x": x, "y": y},
        "resolve": {"scale": {"color": "independent"}, "legend": {"color": "independent"}},
        "layer": [
            {"mark": {"type": "rect", "cornerRadius": 3},
             "encoding": {"color": {"field": "state", "type": "nominal", "title": "칸 상태",
                                    "scale": {"domain": [s[3] for s in STATES.values()],
                                              "range": [s[1] for s in STATES.values()]},
                                    "legend": {"columns": 1, "symbolType": "square"}},
                          "tooltip": tooltip}},
            {"mark": {"type": "text", "fontSize": 13, "fontWeight": 600},
             "encoding": {"text": {"field": "mark"},
                          "color": {"field": "ink", "type": "nominal", "legend": None,
                                    "scale": {"domain": ["light", "dark", "fg"],
                                              "range": ["#ffffff", "#111111", LIGHT["fg"]]}},
                          "tooltip": tooltip}},
        ],
    })
    meta = {"rows": len(matrix["rows"]), "columns": len(matrix["columns"]), "notes": notes,
            "source": f"{source} ({len(matrix['rows'])}×{len(matrix['columns'])}칸"
                      + (f", {matrix.get('title')}" if matrix.get("title") else "") + ")"}
    return spec, meta
