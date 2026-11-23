"""novelty: per card, its closest papers placed by overlap grade, filled/hollow by read depth, verdict at the right."""
from __future__ import annotations

import json
import re
from pathlib import Path

from scholarly_access_agent.evidence import GRADES, LABEL_NONE, derive_label, derive_verdict

from .common import VizError, access_channel, access_key, finish, load_records, study_label

GRADE_NAMES = {5: "Exact", 4: "High", 3: "Medium", 2: "Low", 1: "None", 0: "미등급"}
VERDICT_KO = {"not-novel": "새롭지 않음", "reframe": "재구성", "provisional": "잠정", "novel": "새로움"}
VERDICT_COLOR = {"not-novel": "#D55E00", "reframe": "#E69F00", "provisional": "#59636e", "novel": "#009E73"}


def _card_no(name: str) -> tuple[int, str]:
    m = re.search(r"\d+", name)
    return (int(m.group(0)) if m else 10**6, name)


def closest_label(item: dict, topic: Path, by_id: dict[str, tuple[str, dict]]) -> tuple[str, str]:
    """(read-depth label, display name) of one closest paper; an evidence record it points to wins."""
    via = str(item.get("read_via") or "")
    target = None
    if via.startswith("evidence/") or via.endswith(".json"):
        f = topic / via if not Path(via).is_absolute() else Path(via)
        if f.exists():
            try:
                target = (f.stem, json.loads(f.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                target = None
    if target is None:
        target = by_id.get(str(item.get("paper_id") or "").lower())
    if target is not None and isinstance(target[1], dict):
        return derive_label(target[1])["label"], study_label(target[1], target[0])
    loc = {k: item[k] for k in ("pdf_page", "section", "read_mode") if item.get(k) not in (None, "")}
    pseudo = {"access": item.get("access"), "read_via": item.get("read_via"),
              "criteria": [{"evidence": [loc]}] if loc else []}
    pid = str(item.get("paper_id") or "?")
    return derive_label(pseudo)["label"], (pid if len(pid) <= 28 else pid[:27] + "…")


def build(topic: Path) -> tuple[dict, dict]:
    folder = topic / "ideas" / "novelty"
    files = sorted(folder.glob("*.json"), key=lambda f: _card_no(f.stem)) if folder.is_dir() else []
    if not files:
        raise VizError(f"no ideas/novelty/*.json under {topic}")
    by_id = {str(r.get("paper_id") or "").lower(): (stem, r) for stem, r in load_records(topic) if r.get("paper_id")}
    points, verdicts, unread, has_unknown = [], [], 0, False
    for f in files:
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(rec, dict):
            continue
        card = str(rec.get("card") or f.stem)
        stored = str(rec.get("verdict") or "").strip().lower()
        derived, reason = derive_verdict(rec)
        verdict = stored if stored in VERDICT_KO else derived
        card_unread, slots = 0, {}
        for item in rec.get("closest") or []:
            if not isinstance(item, dict):
                continue
            label, name = closest_label(item, topic, by_id)
            if label == LABEL_NONE:
                card_unread += 1
                continue
            g = GRADES.get(str(item.get("grade") or "").strip().lower(), 0)
            has_unknown |= g == 0
            slots.setdefault(g, []).append({
                "card": card, "grade": GRADE_NAMES[g], "g": g, "paper": name,
                "paper_id": str(item.get("paper_id") or "-"), "label": label,
                "reason": str(item.get("reason") or "-")[:200],
                "overlap": " / ".join(f"{k}: {item[k]}" for k in ("question", "system", "method") if item.get(k))[:300]
                or "-"})
        for g, items in slots.items():
            n = len(items)
            for i, p in enumerate(items):
                p["x"] = g + (i - (n - 1) / 2) * 0.16
                points.append(p)
        unread += card_unread
        text = VERDICT_KO[verdict] + (f" · 미확인 {card_unread}" if card_unread else "")
        verdicts.append({"card": card, "verdict": verdict, "text": text, "x": 5.55,
                         "stored": stored or "-", "derived": derived, "reason": reason})
    if not verdicts:
        raise VizError("no readable novelty records")
    order = [v["card"] for v in verdicts]
    lo = -0.5 if has_unknown else 0.5
    ticks = ([0] if has_unknown else []) + [1, 2, 3, 4, 5]
    label_expr = "{" + ", ".join(f"'{k}': '{v}'" for k, v in GRADE_NAMES.items()) + "}[datum.value]"
    x = {"field": "x", "type": "quantitative", "title": "가장 가까운 논문과의 겹침 정도",
         "scale": {"domain": [lo, 7.3], "nice": False, "zero": False},
         "axis": {"values": ticks, "labelExpr": label_expr, "grid": True, "labelOverlap": False}}
    y = {"field": "card", "type": "nominal", "sort": order, "title": "질문 카드"}
    spec = finish({
        "usermeta": {"access_key": access_key(p["label"] for p in points)},
        "width": "container", "height": 40 * len(order), "autosize": {"type": "fit-x", "contain": "padding"},
        "layer": [
            {"data": {"values": points},
             "mark": {"type": "point", "filled": True, "opacity": 1, "size": 110, "strokeWidth": 1.8, "color": "#0072B2",
                      "stroke": "#0072B2"},
             "encoding": {"x": x, "y": y,
                          "fillOpacity": access_channel(p["label"] for p in points),
                          "tooltip": [{"field": "card", "title": "카드"}, {"field": "paper", "title": "논문"},
                                      {"field": "paper_id", "title": "ID"}, {"field": "grade", "title": "겹침"},
                                      {"field": "label", "title": "확인 수준"}, {"field": "overlap", "title": "비교"},
                                      {"field": "reason", "title": "이유"}]}},
            {"data": {"values": verdicts},
             "mark": {"type": "text", "align": "left", "baseline": "middle", "fontSize": 12, "fontWeight": 600},
             "encoding": {"x": {"field": "x", "type": "quantitative"}, "y": y, "text": {"field": "text"},
                          "color": {"field": "verdict", "type": "nominal", "legend": None,
                                    "scale": {"domain": list(VERDICT_COLOR), "range": list(VERDICT_COLOR.values())}},
                          "tooltip": [{"field": "card", "title": "카드"}, {"field": "stored", "title": "기록된 판정"},
                                      {"field": "derived", "title": "등급에서 유도"},
                                      {"field": "reason", "title": "근거"}]}},
        ],
    })
    notes = [f"미확인 {unread}편 생략"] if unread else []
    meta = {"cards": len(verdicts), "points": len(points), "notes": notes,
            "source": f"ideas/novelty/ {len(verdicts)}장 카드의 closest 논문 {len(points)}편 (오른쪽: 판정)"}
    return spec, meta
