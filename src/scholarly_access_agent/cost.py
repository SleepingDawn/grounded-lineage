"""Token estimates, a spend ledger and calibration for research-pilot runs.

The agent never does this arithmetic itself. Three commands:

  cost estimate  plan a run: tokens per stage and per role, optional cap and the
                 reduced budget that fits it (this output is the dry run)
  cost record    append one measured stage (sub-agent tokens, optional plan-%
                 change) to the ledger
  cost report    estimated vs measured for one run, and the calibration factors

Tokens are the unit. Defaults are rough first guesses; every recorded run
corrects later estimates (median measured/estimated per stage, last 10 runs).
Plan-limit percent is shown only as a rough conversion learned from runs that
recorded both, because other sessions on the same account also move it.

Ledger: <research root>/.cost/ledger.jsonl (one JSON object per line).
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

PRESETS = {
    "default": {"screened": 75, "read": 22, "pdf": 10, "figures": 5},
    "deep": {"screened": 200, "read": 50, "pdf": 30, "figures": 15},
}
TOPIC_DEFAULTS = {"records": None, "cells": 10, "cards": 6, "shortlist": 3, "closest": 3, "rounds": 3}

# Context tokens per item (research-workflow.md tiers). MULT covers the turns that
# re-send the context; AGENT_BASE is one sub-agent's fixed start-up cost.
SCREEN, TEXT, PDF, FIGURE = 200, 2500, 4000, 1500
MULT = 3.0
AGENT_BASE = 25_000
PAPERS_PER_READER = 5

# stage -> role (research-models.md rows)
ROLES = {
    "plan_screen": "main", "locate": "locator", "read": "reader", "synthesize": "main",
    "matrix": "main", "gap_check": "locator", "cards": "judge", "novelty_search": "locator",
    "novelty_read": "reader", "feasibility": "judge", "critique": "judge", "report": "writer",
}
SHRINK_ORDER = ("figures", "pdf", "cells", "cards", "shortlist", "read", "screened")


def ledger_path(root: Path | None = None) -> Path:
    if root is None:
        from scholarly_access_agent.lineage.workspace import research_root

        root = research_root()
    return Path(root) / ".cost" / "ledger.jsonl"


def load(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def status_stages(c: dict) -> dict:
    readers = math.ceil(c["read"] / PAPERS_PER_READER) if c["read"] else 0
    return {
        "plan_screen": c["screened"] * SCREEN * MULT + 10_000,
        "locate": c["read"] * 1_500 * MULT,
        "read": (c["read"] * TEXT + c["pdf"] * PDF + c["figures"] * FIGURE) * MULT + readers * AGENT_BASE,
        "synthesize": c["read"] * 400 * MULT + 15_000,
    }


def topic_stages(t: dict) -> dict:
    cards, short = t["cards"], t["shortlist"]
    return {
        "matrix": t["records"] * 600 * MULT + 10_000,
        "gap_check": t["cells"] * 3_000 * MULT + AGENT_BASE,
        "cards": cards * 2_000 * MULT,
        "novelty_search": cards * t["rounds"] * 3_000 * MULT + AGENT_BASE,
        "novelty_read": short * t["closest"] * 4_000 * MULT + short * AGENT_BASE,
        "feasibility": short * 8_000 * MULT,
        "critique": short * 5_000 * MULT,
        "report": 15_000,
    }


def calibration(rows: list[dict], last: int = 10) -> dict:
    """Median measured/estimated per stage over the last `last` runs that measured it."""
    ratios: dict[str, list[tuple[str, float]]] = {}
    for r in rows:
        if r.get("kind") == "stage" and r.get("tokens") and r.get("estimated"):
            ratios.setdefault(r["stage"], []).append((r.get("ts", ""), r["tokens"] / r["estimated"]))
    out = {}
    for stage, vals in ratios.items():
        vals.sort()
        recent = [v for _, v in vals[-last:]]
        out[stage] = {"factor": round(statistics.median(recent), 3), "runs": len(recent)}
    return out


def pct_per_mtok(rows: list[dict]) -> float | None:
    """Rough plan-% per million tokens from runs that recorded both."""
    vals = [r["plan_pct"] / (r["tokens"] / 1e6) for r in rows
            if r.get("kind") == "stage" and r.get("plan_pct") and r.get("tokens")]
    return round(statistics.median(vals), 3) if vals else None


def estimate(playbook: str, counts: dict, topic: dict | None, rows: list[dict]) -> dict:
    stages = {}
    if counts is not None:
        stages.update(status_stages(counts))
    if playbook == "topics":
        stages.update(topic_stages(topic))
    cal = calibration(rows)
    out_stages, by_role, total = {}, {}, 0
    for name, raw in stages.items():
        factor = cal.get(name, {}).get("factor", 1.0)
        tokens = int(round(raw * factor, -3))
        out_stages[name] = {"role": ROLES[name], "tokens": tokens, "default": int(round(raw, -3)),
                            "factor": factor, "calibrated_runs": cal.get(name, {}).get("runs", 0)}
        by_role[ROLES[name]] = by_role.get(ROLES[name], 0) + tokens
        total += tokens
    calibrated = sum(1 for s in out_stages.values() if s["calibrated_runs"])
    return {"stages": out_stages, "by_role": by_role, "total_tokens": total,
            "calibrated_stages": f"{calibrated}/{len(out_stages)}"}


FLOORS = {"figures": 0, "pdf": 0, "cells": 3, "cards": 3, "shortlist": 2, "read": 5, "screened": 20}


def fit(playbook: str, counts: dict | None, topic: dict | None, rows: list[dict], cap: int) -> dict:
    """Shrink in SHRINK_ORDER (figures, PDFs, empty cells checked, cards, shortlist, papers
    read, screened) down to FLOORS until the estimate fits. Novelty rounds never shrink."""
    counts = dict(counts) if counts else None
    topic = dict(topic) if topic else None
    for key in SHRINK_ORDER:
        bag = counts if counts is not None and key in counts else topic if topic and key in topic else None
        if bag is None:
            continue
        while estimate(playbook, counts, topic, rows)["total_tokens"] > cap and bag[key] > FLOORS[key]:
            bag[key] = max(FLOORS[key], bag[key] - max(1, bag[key] // 5))
            if counts is not None:
                counts["pdf"] = min(counts["pdf"], counts["read"])
                counts["figures"] = min(counts["figures"], counts["read"])
            if topic is not None:
                topic["shortlist"] = min(topic["shortlist"], topic["cards"])
    result = estimate(playbook, counts, topic, rows)
    return {"counts": counts, "topic": topic, "total_tokens": result["total_tokens"],
            "fits": result["total_tokens"] <= cap}


def cmd_estimate(a, path: Path) -> dict:
    rows = load(path)
    counts = None
    if not a.skip_status:
        counts = dict(PRESETS[a.preset])
        for key in counts:
            if getattr(a, key) is not None:
                counts[key] = getattr(a, key)
    topic = None
    if a.playbook == "topics":
        topic = {k: (getattr(a, k) if getattr(a, k) is not None else v) for k, v in TOPIC_DEFAULTS.items()}
        if topic["records"] is None:
            topic["records"] = counts["read"] if counts else 20
    out = {"playbook": a.playbook, "preset": None if a.skip_status else a.preset, "counts": counts,
           "topic": topic, **estimate(a.playbook, counts, topic, rows)}
    rate = pct_per_mtok(rows)
    out["plan_pct_per_mtok"] = rate
    if rate:
        out["plan_pct_estimate"] = round(out["total_tokens"] / 1e6 * rate, 1)
    cap = a.cap_tokens
    if cap is None and a.cap_pct is not None and rate:
        cap = int(a.cap_pct / rate * 1e6)
    if a.remaining_pct is not None and rate:
        half = int(a.remaining_pct / 2 / rate * 1e6)
        cap = half if cap is None else min(cap, half)
    if cap is not None:
        out["cap_tokens"] = cap
        out["fits"] = out["total_tokens"] <= cap
        if not out["fits"]:
            out["reduced"] = fit(a.playbook, counts, topic, rows, cap)
    elif a.cap_pct is not None or a.remaining_pct is not None:
        out["cap_note"] = "no calibrated plan-% rate yet: pass --cap-tokens, or record runs with --plan-pct"
    return out


def cmd_record(a, path: Path) -> dict:
    if a.stage not in ROLES:
        raise ValueError(f"unknown stage {a.stage!r}; one of {', '.join(ROLES)}")
    row = {"kind": "stage", "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "run": a.run, "stage": a.stage, "role": ROLES[a.stage], "model": a.model,
           "tokens": a.tokens, "estimated": a.estimated, "plan_pct": a.plan_pct, "note": a.note}
    row = {k: v for k, v in row.items() if v is not None}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"ok": True, "ledger": str(path), "recorded": row}


def cmd_report(a, path: Path) -> dict:
    rows = load(path)
    mine = [r for r in rows if r.get("run") == a.run and r.get("kind") == "stage"]
    stages = {}
    for r in mine:
        s = stages.setdefault(r["stage"], {"tokens": 0, "estimated": 0})
        s["tokens"] += r.get("tokens", 0)
        s["estimated"] += r.get("estimated", 0) or 0
    total = sum(s["tokens"] for s in stages.values())
    est = sum(s["estimated"] for s in stages.values())
    plan = sum(r.get("plan_pct", 0) or 0 for r in mine)
    return {"run": a.run, "stages": stages, "measured_tokens": total, "estimated_tokens": est,
            "plan_pct_measured": round(plan, 2) if plan else None,
            "calibration": calibration(rows), "plan_pct_per_mtok": pct_per_mtok(rows)}


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="scholarly-access-agent cost", description=__doc__.split("\n\n")[0])
    ap.add_argument("--ledger", help="ledger file (default: <research root>/.cost/ledger.jsonl)")
    sub = ap.add_subparsers(dest="command", required=True)

    e = sub.add_parser("estimate", help="Estimate a run (the dry run); optionally fit it under a cap.")
    e.add_argument("--playbook", choices=("status", "topics"), required=True)
    e.add_argument("--preset", choices=tuple(PRESETS), default="default")
    e.add_argument("--skip-status", action="store_true",
                   help="topics only: the review folder already exists, estimate topic stages alone")
    for key in PRESETS["default"]:
        e.add_argument(f"--{key}", type=int, help=f"override the preset's {key} count")
    for key in TOPIC_DEFAULTS:
        e.add_argument(f"--{key}", type=int, help=f"topics: {key} (default {TOPIC_DEFAULTS[key]})")
    e.add_argument("--cap-tokens", type=int, help="token cap for the whole run")
    e.add_argument("--cap-pct", type=float, help="cap as plan-limit percent (needs calibration)")
    e.add_argument("--remaining-pct", type=float,
                   help="plan-limit percent still free now; the cap becomes at most half of it")

    r = sub.add_parser("record", help="Append one measured stage to the ledger.")
    r.add_argument("--run", required=True, help="run id, e.g. <Topic>-YYYYMMDD-HHMM")
    r.add_argument("--stage", required=True, help=f"one of: {', '.join(ROLES)}")
    r.add_argument("--tokens", type=int, required=True, help="measured tokens (sub-agent usage, summed)")
    r.add_argument("--estimated", type=int, help="this stage's estimate from `cost estimate`")
    r.add_argument("--model", help="model used, e.g. opus")
    r.add_argument("--plan-pct", type=float, help="change in the 5-hour plan-limit percent over this stage")
    r.add_argument("--note")

    p = sub.add_parser("report", help="Estimated vs measured for one run, plus calibration.")
    p.add_argument("--run", required=True)
    return ap


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    path = Path(a.ledger) if a.ledger else ledger_path()
    try:
        out = {"estimate": cmd_estimate, "record": cmd_record, "report": cmd_report}[a.command](a, path)
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
