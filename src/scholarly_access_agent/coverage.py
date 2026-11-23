"""Coverage of a plain review: was the search measured, and do the records read cover both old and new work?

  scholarly-access-agent evidence coverage <topic folder> [--era-focus both|origin|current] [--json]

Offline. Reads what the review already produced, where it exists:
  data/queries.json, data/gold.json, data/anchor_checks.json   `lineage query-test data ...` on the review's queries
  data/corpus.json, data/expansion.json                         `lineage expand ... --out data/expansion.json`
  evidence/*.json                                               the records read
Reports
  search  queries tested, saturation (novelty < 10% at precision >= 50%), strategy recall on the gold, gold-era
          notes, query blocks flagged ANCHOR
  era     share of the expansion field from the last three years against the share of read records from those
          years; foundational candidates (cited by two or more seeds) and recent candidates (citing the seeds)
          that no record covers yet
Warnings: search_not_measured, unsaturated_search, anchor_flagged, era_recent_thin, era_founders_thin. The era focus
only switches off the warning for the era the question is not about; it never narrows the search.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

RECENT_YEARS = 3


def _load(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default
    except (OSError, json.JSONDecodeError):
        return default


def search_part(data: Path) -> tuple[dict, list[str]]:
    from .lineage.searchlog import saturation

    log = _load(data / "queries.json", [])
    if not log:
        return {"tested": 0}, ["search_not_measured: no tested queries (data/queries.json); run "
                               "`lineage query-test data '<q1>' '<q2>' ... --drop-blocks --focus '<topic regex>'` on the "
                               "main queries after `lineage expand` (it needs data/corpus.json)"]
    warns = []
    state = saturation(data) or {}
    gold = _load(data / "gold.json", {}).get("ids") or []
    found = set()
    for e in log:
        found |= set(e.get("gold_found_ids") or [])
    recall = f"{len(found & set(gold))}/{len(gold)}" if gold else None
    eras = [e["gold_era"] for e in log if e.get("gold_era")]
    anchors = [(e.get("label") or e.get("query", "")[:30], e.get("dropped")) for e in _load(data / "anchor_checks.json", [])
               if e.get("state") == "anchor"]
    if not state.get("saturated"):
        warns.append(f"unsaturated_search: none of {len(log)} tested queries reached novelty < 10% at precision >= 50%; "
                     "vary the vocabulary or say in the method section that the search did not converge")
    for name, block in anchors:
        warns.append(f"anchor_flagged: in {name}, dropping {str(block)[:50]} revealed many on-topic works not yet "
                     "collected; rewrite that block by function unless it defines the topic")
    return {"tested": len(log), "saturated": state.get("saturated", []), "best_precision": max(
        (e.get("precision") or 0) for e in log), "strategy_recall": recall, "gold_era": eras[-1] if eras else "",
        "anchors": anchors}, warns


def era_part(topic: Path, data: Path, focus: str, today: int) -> tuple[dict, list[str]]:
    from .lineage.expand import known_keys, norm_title

    corpus = _load(data / "corpus.json", {})
    rows = _load(data / "expansion.json", {}).get("rows", [])
    ev_dir = topic / "evidence"
    records = [_load(f, {}) for f in sorted(ev_dir.glob("*.json"))] if ev_dir.is_dir() else []
    lo = today - RECENT_YEARS + 1
    field_years = [w.get("publication_year") for w in corpus.values()
                   if "forward" in (w.get("_role") or []) and w.get("publication_year")]
    ev_years = [int(r["year"]) for r in records if str(r.get("year") or "").isdigit()]
    n_recent = sum(1 for y in field_years if y >= lo)
    share = n_recent / len(field_years) if field_years else 0.0
    ev_recent = sum(1 for y in ev_years if y >= lo)
    dois, wids, titles = known_keys([str(ev_dir)]) if ev_dir.is_dir() else (set(), set(), set())
    covered = lambda r: bool(r.get("openalex") in wids or (r.get("doi") and r["doi"] in dois)
                             or norm_title(r.get("title") or "") in titles)
    founders = sorted((r for r in rows if len(r.get("cited_by_seeds") or []) >= 2),
                      key=lambda r: (-r.get("links", 0), -(r.get("cited_by") or 0)))[:10]
    recent = sorted((r for r in rows if r.get("cites_seeds") and (r.get("year") or 0) >= lo),
                    key=lambda r: -r.get("score", 0))
    f_in = sum(1 for r in founders if covered(r))
    recent_open = [r for r in recent if not covered(r)][:5]
    warns = []
    if focus != "origin" and n_recent >= 10 and share >= 0.15 and ev_recent < 2:
        warns.append(f"era_recent_thin: {n_recent} field papers ({share:.0%}) are from {lo}-{today} but {ev_recent} "
                     "read record(s) are; read the current work (candidates below), or run with --era-focus origin "
                     "if the question is only about where it began")
    if focus != "current" and len(founders) >= 3 and f_in < 2:
        warns.append(f"era_founders_thin: {f_in} of the {len(founders)} works most cited by the seeds are read; add "
                     "the foundations (generic tools can stay out), or run with --era-focus current if the question "
                     "is only about now")
    return {"field_papers": len(field_years), "field_recent_share": round(share, 3), "recent_window": [lo, today],
            "records": len(records), "records_recent": ev_recent, "founders_read": f_in, "founders": len(founders),
            "founders_unread": [(r.get("year"), r.get("title"), r.get("doi") or r.get("openalex"))
                                for r in founders if not covered(r)][:5],
            "recent_unread": [(r.get("year"), r.get("title"), r.get("doi") or r.get("openalex")) for r in recent_open],
            "focus": focus}, warns


def coverage(topic: Path, focus: str = "both", today: int | None = None) -> dict:
    topic = Path(topic)
    data = topic / "data"
    s, w1 = search_part(data)
    e, w2 = era_part(topic, data, focus, today or dt.date.today().year)
    return {"search": s, "era": e, "warnings": w1 + w2}


def text(res: dict) -> str:
    s, e = res["search"], res["era"]
    out = []
    if s["tested"]:
        out.append(f"search: {s['tested']} tested queries, best precision {s['best_precision']:.0%}, saturated: "
                   f"{', '.join(s['saturated']) or 'none'}" + (f", strategy recall {s['strategy_recall']} of the gold"
                                                              if s["strategy_recall"] else ", no gold"))
        if s["gold_era"]:
            out.append("  " + s["gold_era"])
    else:
        out.append("search: not measured")
    lo, hi = e["recent_window"]
    out.append(f"era (focus {e['focus']}): {e['field_recent_share']:.0%} of {e['field_papers']} field papers and "
               f"{e['records_recent']} of {e['records']} read records are from {lo}-{hi}; {e['founders_read']} of the "
               f"{e['founders']} works most cited by the seeds are read")
    for label, items in (("foundational, not read", e["founders_unread"]), ("recent, not read", e["recent_unread"])):
        for y, t, ident in items:
            out.append(f"  {label}: {y} {(t or '')[:80]} ({ident})")
    out += [f"warning: {w}" for w in res["warnings"]]
    return "\n".join(out)
