"""Freeze an independent gold set for query-test recall.

The curated lineage is not a fair gold set: the agent picked those papers, partly from the same searches, so
recall on it is circular. Freeze a list built independently instead, e.g. the papers on the topic cited by two
independent reviews, before testing queries.

Usage:
  lineage gold freeze DATA_DIR --from-file FILE [--note 'a-SiO2 papers cited by both Review A and Review B']
FILE: one OpenAlex ID (W123, https://openalex.org/W123) or DOI (10.x/..., https://doi.org/...) per line;
blank lines and text after '#' are ignored. DOIs are resolved to OpenAlex IDs (network); unresolved ones are kept
in gold.json under "unresolved" and reported.
Writes DATA_DIR/gold.json {"date", "source", "note", "ids", "entries", "unresolved"}. `lineage query-test` uses it
by default when no other gold is given and prints "gold: independent (N)".
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
from pathlib import Path

from . import openalex

WID = re.compile(r"^(?:https?://openalex\.org/)?(W\d+)$", re.I)


def parse(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        tok = line.split("#", 1)[0].strip()
        if tok:
            out.append(tok.split()[0])
    return out


def freeze(d: Path, src: Path, note: str = "") -> dict:
    items = parse(src.read_text(encoding="utf-8"))
    dois = [x for x in items if not WID.match(x)]
    resolved = openalex.resolve_dois(dois) if dois else {}
    entries, unresolved = [], []
    for x in items:
        m = WID.match(x)
        if m:
            entries.append({"input": x, "id": m.group(1).upper()})
        elif openalex.norm_doi(x) in resolved:
            entries.append({"input": x, "id": resolved[openalex.norm_doi(x)]})
        else:
            unresolved.append(x)
    ids = list(dict.fromkeys(e["id"] for e in entries))
    g = {"date": datetime.date.today().isoformat(), "source": src.name, "note": note, "ids": ids,
         "entries": entries, "unresolved": unresolved}
    d.mkdir(parents=True, exist_ok=True)
    (d / "gold.json").write_text(json.dumps(g, indent=1, ensure_ascii=False), encoding="utf-8")
    return g


def load_ids(path: Path) -> list[str]:
    """Gold IDs from a gold.json (from `gold freeze`) or a plain file of OpenAlex IDs (one per line)."""
    text = Path(path).read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    if isinstance(data, dict):
        return list(data.get("ids", []))
    if isinstance(data, list):
        return [openalex.short(str(x)) for x in data]
    items = parse(text)
    bad = [x for x in items if not WID.match(x)]
    if bad:
        raise ValueError(f"{path}: {len(bad)} line(s) are not OpenAlex IDs (e.g. {bad[0]!r}); resolve DOIs first "
                         "with `lineage gold freeze DATA_DIR --from-file FILE`")
    return [WID.match(x).group(1).upper() for x in items]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="lineage gold")
    sub = ap.add_subparsers(dest="cmd", required=True)
    fz = sub.add_parser("freeze", help="write DATA_DIR/gold.json from a list of OpenAlex IDs / DOIs")
    fz.add_argument("data_dir")
    fz.add_argument("--from-file", required=True)
    fz.add_argument("--note", default="", help="where the list came from (shown in the report method section)")
    a = ap.parse_args(argv)
    g = freeze(Path(a.data_dir), Path(a.from_file), a.note)
    print(f"gold: independent ({len(g['ids'])}) frozen to {Path(a.data_dir) / 'gold.json'} from {g['source']}")
    for x in g["unresolved"]:
        print(f"  unresolved (not in OpenAlex by DOI): {x}")
    return 0
