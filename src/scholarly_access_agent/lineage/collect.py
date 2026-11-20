"""Collect a citation corpus around seed paper(s) from OpenAlex.

Base corpus = seeds + backward refs (level 1) + forward citing papers (level 1).
Optional widening (depth), each capped:
  --query 'Q'            add the most relevant works for a boolean query (concept blocks,
                         tested first with `lineage query-test`); repeatable, capped by --per-keyword
  --keywords "kw1;kw2"   add the most-cited works whose title/abstract match each keyword
                         (inside --context)
  --ancestors N          take the N references most cited by the field (optionally only
                         those whose title matches --focus) and add their most-cited
                         citing papers (--per-ancestor M), role "ancestor-forward"
  --base DIR             start from an existing corpus.json (and refs_meta.json cache)

Usage:
  lineage collect OUT_DIR SEED [SEED ...]
  lineage collect OUT_DIR SEED --base data --query '<tested query>' --per-keyword 60
  lineage collect OUT_DIR SEED --base data --ancestors 6 --per-ancestor 40 --focus 'charge|electrostat'
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from collections import Counter
from pathlib import Path

from .openalex import FIELDS, fetch_citing, fetch_many, get, search, short


def search_keyword(kw: str, context: str, limit: int) -> dict:
    flt = f'title_and_abstract.search:"{kw}"' + (f" AND ({context})" if context else "")
    d = get({"filter": flt, "per-page": min(200, limit), "sort": "cited_by_count:desc", "select": FIELDS})
    return {short(w["id"]): w for w in d["results"][:limit]}


def search_query(q: str, limit: int) -> dict:
    d = search(q, limit)
    return {short(w["id"]): w for w in d["results"][:limit]}


def add(corpus: dict, role: dict, works: dict, tag: str) -> int:
    n = 0
    for k, w in works.items():
        if k not in corpus:
            corpus[k] = w
            n += 1
        role.setdefault(k, set()).add(tag)
    return n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="lineage collect")
    ap.add_argument("out_dir")
    ap.add_argument("seeds", nargs="+")
    ap.add_argument("--base")
    ap.add_argument("--keywords", default="")
    ap.add_argument("--context", default="")
    ap.add_argument("--query", action="append", default=[],
                    help="boolean query tested with `lineage query-test`; repeat for several")
    ap.add_argument("--per-keyword", type=int, default=40)
    ap.add_argument("--ancestors", type=int, default=0)
    ap.add_argument("--per-ancestor", type=int, default=40)
    ap.add_argument("--focus", default="")
    a = ap.parse_args(argv)

    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    seeds = [short(s) for s in a.seeds]
    corpus: dict = {}
    role: dict = {}

    if a.base:
        base = Path(a.base)
        corpus = json.loads((base / "corpus.json").read_text(encoding="utf-8"))
        for k, w in corpus.items():
            role[k] = set(w.get("_role", []))
        if (base / "refs_meta.json").exists() and base.resolve() != out_dir.resolve():
            shutil.copy(base / "refs_meta.json", out_dir / "refs_meta.json")
    else:
        corpus = fetch_many(seeds)
        for s in seeds:
            role[s] = {"seed"}
        back = set()
        for s in seeds:
            back |= {short(r) for r in corpus[s]["referenced_works"]}
        corpus.update(fetch_many(back - corpus.keys()))
        for b in back:
            role.setdefault(b, set()).add("backward")
        for s in seeds:
            add(corpus, role, fetch_citing(s), "forward")

    for kw in [k.strip() for k in a.keywords.split(";") if k.strip()]:
        n = add(corpus, role, search_keyword(kw, a.context, a.per_keyword), f"keyword:{kw}")
        print(f"keyword '{kw}': +{n} new")

    for q in a.query:
        n = add(corpus, role, search_query(q, a.per_keyword), f"keyword:{q}")
        print(f"query '{q[:70]}': +{n} new")

    if a.ancestors:
        field = [k for k, r in role.items() if r & {"seed", "forward"}]
        cnt: Counter = Counter()
        for k in field:
            cnt.update(short(x) for x in corpus[k]["referenced_works"])
        meta_p = out_dir / "refs_meta.json"
        meta = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else {}

        def title(k):
            return (corpus.get(k) or meta.get(k) or {}).get("title") or ""

        ranked = [k for k, _ in cnt.most_common() if k not in seeds
                  and (not a.focus or re.search(a.focus, title(k), re.I))][:a.ancestors]
        for k in ranked:
            n = add(corpus, role, fetch_citing(k, a.per_ancestor), "ancestor-forward")
            print(f"ancestor {k} ({title(k)[:60]}): +{n} new")

    for k, w in corpus.items():
        w["_role"] = sorted(role.get(k, []))
    (out_dir / "corpus.json").write_text(json.dumps(corpus), encoding="utf-8")
    c = Counter(r.split(":")[0] for rs in role.values() for r in rs)
    print(f"total={len(corpus)} roles={dict(c)}")
    return 0
