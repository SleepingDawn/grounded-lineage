"""`scholarly-access-agent lineage <command> [args]` dispatcher.

Each command module keeps its own argparse; `lineage <command> -h` shows its options.
"""
from __future__ import annotations

import importlib
import sys
from typing import Sequence

COMMANDS = {
    "init": ("workspace", "Create <research root>/<Topic>/ with evidence/, figs/, data/, lineage.json."),
    "seed": ("seed", "Find OpenAlex candidates for a seed paper (title words, DOI, arXiv:ID)."),
    "collect": ("collect", "Collect seed + references + citing papers; optional widening."),
    "analyze": ("analyze", "RPYS, clusters and SPC main path on a collected corpus."),
    "keywords": ("keywords", "Rank OpenAlex keyword tags by field fit for widening."),
    "query-test": ("query_test", "Test a boolean query: precision, recall on gold, novelty; logs it."),
    "mentions": ("mentions", "Count corpus papers matching a pattern, by year (offline)."),
    "links": ("links", "Resolve journal-first links for OpenAlex IDs or a lineage.json."),
    "page": ("page", "Validate lineage.json and render the interactive lineage page."),
    "report-section": ("report", "Write the lineage chapter (Markdown + PNG figure) for a PDF report."),
}


def usage() -> str:
    lines = ["usage: scholarly-access-agent lineage <command> [args]", "", "commands:"]
    lines += [f"  {name:15s} {help_}" for name, (_, help_) in COMMANDS.items()]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(usage())
        return 0 if argv else 2
    name, rest = argv[0], argv[1:]
    if name not in COMMANDS:
        print(f"unknown lineage command: {name}\n\n{usage()}", file=sys.stderr)
        return 2
    module = importlib.import_module(f"scholarly_access_agent.lineage.{COMMANDS[name][0]}")
    from .openalex import OpenAlexError, QuotaExhausted

    try:
        result = module.main(rest)
    except QuotaExhausted as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    except (OpenAlexError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return int(result or 0)
