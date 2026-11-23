"""Check lineage.json without rendering anything (fast; no browser, no network).

Runs the same validation as `lineage page` / `lineage report-section` plus the layout warnings,
including edges drawn through a third paper's box. Run it after every edit of lineage.json and
render the page and the figure once, at the end.

Then, offline from the local corpus (audit.py): s edges without a citation link or a recorded basis,
contested claims resting on non-full-text reading or lacking an x edge, an unsaturated query log, and
"not found" claims without a search log. A summary line counts s edges with / without citation link.

Usage: lineage check WORK_DIR [--no-corpus]   (the topic folder holding lineage.json)
Exit code 0 = renderable (warnings may remain), 1 = problems that block rendering.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from .page import load, validate, warnings, width_budget


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("work_dir")
    ap.add_argument("--no-corpus", action="store_true",
                    help="skip the corpus-backed checks (edge citation links, contested evidence, search saturation)")
    a = ap.parse_args(argv)
    path = Path(a.work_dir) / "lineage.json"
    L = load(path)
    if L is None:
        print(f"{path} not found")
        return 1
    errs = validate(L)
    for e in errs:
        print("problem:", e)
    summary = []
    if not errs:
        for w in warnings(L):
            print("warning:", w)
        if not a.no_corpus:
            from .audit import audit

            extra, summary = audit(L, Path(a.work_dir))
            for w in extra:
                print("warning:", w)
    events = any(n.get("kind") == "event" for n in L.get("nodes", []))
    for line in summary:
        print(line)
    print(f"box budget: {width_budget('title')}; {width_budget('sub')}"
          + (f"; {width_budget('event')}" if events else ""))
    print(f"{len(errs)} problem(s)" + ("" if errs else f"; {len(L['nodes'])} nodes, {len(L['edges'])} edges, "
                                       f"{len(L['lanes'])} lanes"))
    return 1 if errs else 0
