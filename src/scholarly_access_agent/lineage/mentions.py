"""Count corpus papers whose title/abstract match a pattern, by year and role (offline).

Use it to back verdict cards with numbers, e.g. how many citing papers integrate,
benchmark or extend an approach.

Usage: lineage mentions DATA_DIR "REGEX" [--list]
  lineage mentions data "MACE-LES|LES-augmented|latent Ewald" --list
  lineage mentions data "baseline|benchmark|compared (with|to)" --list
Matching is case-insensitive over title + abstract of the citing / expanded papers.
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path


def text_of(w):
    ii = w.get("abstract_inverted_index") or {}
    pos = sorted((p, t) for t, ps in ii.items() for p in ps)
    return (w.get("title") or "") + " " + " ".join(t for _, t in pos)


def main(argv=None):
    argv = argv if argv is None else list(argv)
    d, pat = Path(argv[0]), re.compile(argv[1], re.I)
    show = "--list" in argv
    corpus = json.loads((d / "corpus.json").read_text(encoding="utf-8"))
    field = {k: w for k, w in corpus.items() if any(
        r == "forward" or r.startswith("keyword:") or r == "ancestor-forward" for r in w.get("_role", []))}
    hits = [w for w in field.values() if pat.search(text_of(w))]
    no_abs = sum(1 for w in field.values() if not w.get("abstract_inverted_index"))
    by_year = Counter(w.get("publication_year") for w in hits)
    tot_year = Counter(w.get("publication_year") for w in field.values())
    print(f"{len(hits)} of {len(field)} field papers match ({no_abs} have no abstract, so counts are lower bounds)")
    for y in sorted(tot_year):
        print(f"  {y}: {by_year.get(y, 0)} / {tot_year[y]}")
    if show:
        for w in sorted(hits, key=lambda w: (-(w.get("publication_year") or 0), -(w.get("cited_by_count") or 0))):
            a = (w.get("authorships") or [{}])[0].get("author", {}).get("display_name", "")
            print(f"  {w.get('publication_year')} cit={w.get('cited_by_count'):<4} {a[:22]:22} {w['id'].rsplit('/', 1)[-1]}  {w['title'][:90]}")

