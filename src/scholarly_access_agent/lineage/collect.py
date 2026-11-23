"""Collect a citation corpus around seed paper(s) from OpenAlex.

Base corpus = seeds + backward refs (level 1) + forward citing papers (level 1).
Optional widening (depth), each capped:
  --query 'Q'            add the most relevant works for a boolean query (concept blocks,
                         tested first with `lineage query-test`); repeatable, capped by --per-keyword,
                         plus --recent newest works on top (default half of --per-keyword), so recent
                         work gets in without pushing out the classical, most relevant results
  --keywords "kw1;kw2"   add works whose title/abstract match each keyword (inside --context):
                         half most-cited, half newest, so recent low-citation work is kept
  --ancestors N          take the N references most cited by the field (optionally only
                         those whose title matches --focus) and add their citing papers
                         (--per-ancestor M; half most-cited, half newest), role "ancestor-forward"
  --base DIR             start from an existing corpus.json (and refs_meta.json cache)

Usage:
  lineage collect OUT_DIR SEED [SEED ...]
  lineage collect OUT_DIR SEED --base data --query '<tested query>' --per-keyword 60
  lineage collect OUT_DIR SEED --base data --ancestors 6 --per-ancestor 40 --focus 'fatigue|crack'
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from collections import Counter
from pathlib import Path

from .openalex import FIELDS, SPLIT_HINT, check_query, fetch_citing, fetch_many, get, search, short, top_mixed


def search_keyword(kw: str, context: str, limit: int) -> dict:
    flt = f'title_and_abstract.search:"{kw}"' + (f" AND ({context})" if context else "")
    return top_mixed({"filter": flt, "select": FIELDS}, limit)[0]


def search_query(q: str, limit: int, recent: int = 0) -> tuple[dict, int]:
    """The `limit` most relevant works, plus up to `recent` newest works that are not among them.

    Relevance ranking favours older, well-cited work: in a 2026 test, works from the last three years sat at
    ranks 14-98. The newest works are added on top, never in place of relevant ones, so a classical topic
    keeps its full relevance list. Returns (works, number of newest works added)."""
    d = search(q, limit)
    out = {short(w["id"]): w for w in d["results"][:limit]}
    n_new = 0
    if recent > 0:
        newest = get({"filter": f"title_and_abstract.search:{check_query(q)}", "select": FIELDS,
                      "per-page": min(200, recent + limit), "sort": "publication_date:desc"}).get("results", [])
        for w in newest:
            if n_new >= recent:
                break
            if short(w["id"]) not in out:
                out[short(w["id"])] = w
                n_new += 1
    return out, n_new


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
    ap.add_argument("--recent", type=int, default=None,
                    help="per --query: newest works added on top of the --per-keyword most relevant "
                         "(default half of --per-keyword; 0 = relevance only)")
    ap.add_argument("--ancestors", type=int, default=0)
    ap.add_argument("--per-ancestor", type=int, default=40)
    ap.add_argument("--focus", default="")
    a, extra = ap.parse_known_args(argv)
    if extra:
        ap.error(f"unrecognized arguments: {' '.join(extra)}" + (f". {SPLIT_HINT}" if a.query else ""))

    seeds = [short(s) for s in a.seeds]
    # validate before any network call or output directory is created
    bad = [s for s in seeds if not re.fullmatch(r"[Ww]\d+", s)]
    if bad:
        ap.error(f"seeds must be OpenAlex work IDs (W123...), got {bad[:5]}"
                 + (f". {SPLIT_HINT}" if a.query else ""))
    for q in a.query:
        check_query(q)
    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
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

    recent = a.per_keyword // 2 if a.recent is None else a.recent
    for q in a.query:
        works, n_recent = search_query(q, a.per_keyword, recent)
        n = add(corpus, role, works, f"keyword:{q}")
        print(f"query '{q[:70]}': +{n} new ({a.per_keyword} most relevant + {n_recent} newest)")

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
