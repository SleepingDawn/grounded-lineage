"""Suggest related keywords for widening the corpus beyond the seed's citation neighbourhood.

1. Collect OpenAlex keyword tags of the seed's citing papers and of the core ancestors
   (references cited >= MIN_ANC times by the field).
2. Rank tags by how many of those documents carry them; drop generic ones.
3. For each candidate, count works whose title/abstract match `"tag" AND (CONTEXT)`
   and how many of the 50 most-cited matches are NOT already in the corpus.
   A high "new" share means the keyword reaches papers the seed's citations miss.

Usage: lineage keywords DATA_DIR "CONTEXT" [TOP_N] [MIN_ANC] [FOCUS_REGEX]
  e.g. lineage keywords data '"machine learning" OR "neural network"' 15 5 'long-range|electrostat|charge'
FOCUS_REGEX (optional) keeps only tags that are concentrated in on-topic titles.
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

from .openalex import get, short
from .query_test import text_of
from .topic import core_set, in_field

GENERIC = {
    "machine learning interatomic potentials", "machine learning", "neural network potentials",
    "molecular dynamics", "density functional theory", "potential energy surface", "deep learning",
    "machine learning potentials", "interatomic potentials", "atomistic simulation", "atomistic simulations",
    "machine learning force fields", "force fields", "neural networks", "neural network", "first-principles",
    "ab initio", "molecular dynamics simulations", "graph neural networks", "materials science",
    "computational chemistry", "machine-learned interatomic potentials", "interatomic potential",
    "machine learning interatomic potential", "computational efficiency", "high-throughput screening",
    "electronic structure", "quantum chemistry", "transferability", "equivariance", "data efficiency",
    "deep neural network", "deep neural networks", "convolutional neural network", "artificial intelligence",
}


def fetch_keywords(ids):
    out = {}
    ids = sorted(set(ids))
    for k in range(0, len(ids), 50):
        r = get({"filter": "openalex_id:" + "|".join(ids[k:k + 50]), "per-page": 50,
                 "select": "id,keywords"})
        for w in r["results"]:
            out[short(w["id"])] = [x["display_name"].lower() for x in w.get("keywords") or [] if x["score"] >= 0.5]
    return out


def main(argv=None):
    argv = argv if argv is None else list(argv)
    d = Path(argv[0])
    context = argv[1]
    top_n = int(argv[2]) if len(argv) > 2 else 15
    min_anc = int(argv[3]) if len(argv) > 3 else 5
    focus = argv[4] if len(argv) > 4 else None
    corpus = json.loads((d / "corpus.json").read_text(encoding="utf-8"))
    mp = d / "refs_meta.json"
    meta = json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else {}
    fwd = [k for k, w in corpus.items() if "forward" in w["_role"]]
    cnt = Counter()
    for k in fwd:
        cnt.update(short(r) for r in corpus[k]["referenced_works"])
    anc = [r for r, n in cnt.items() if n >= min_anc]
    kw = fetch_keywords(fwd + anc)
    df = Counter()
    for ws in kw.values():
        df.update(set(ws))
    if focus:
        # keep tags concentrated in on-topic documents (title matches FOCUS regex)
        titles = {k: (corpus.get(k) or meta.get(k) or {}).get("title") or "" for k in kw}
        rel = [k for k in kw if re.search(focus, titles[k], re.I)]
        df_rel = Counter()
        for k in rel:
            df_rel.update(set(kw[k]))
        scored = [(p, df_rel[p]) for p in df if p not in GENERIC and df_rel[p] >= 3
                  and df_rel[p] / df[p] >= 0.5]
        cands = sorted(scored, key=lambda x: (-x[1], x[0]))[:top_n]
    else:
        cands = [(p, n) for p, n in df.most_common() if p not in GENERIC and n >= 3][:top_n]

    have = set(corpus) | set(meta)  # "new" = neither in the corpus nor cited by it
    res = []
    fre = re.compile(focus, re.I) if focus else None
    core = core_set(d)
    for p, n in cands:
        flt = f'title_and_abstract.search:"{p}" AND ({context})'
        r = get({"filter": flt, "per-page": 50, "sort": "cited_by_count:desc",
                 "select": "id,title,publication_year,cited_by_count,abstract_inverted_index,referenced_works"})
        total = r.get("meta", {}).get("count", 0)
        top = r.get("results", [])
        # precision = citation-anchored: the hit cites a core paper of the field (wording-independent).
        # "new" counts only in-field works, so a keyword that drags in unrelated papers scores low.
        on = [w for w in top if in_field(w, core)]
        new = [w for w in on if short(w["id"]) not in have]
        # topic regex is a second, weaker signal; uninformative when the keyword itself matches it
        self_match = bool(fre and fre.search(p))
        on_re = [w for w in top if fre.search(text_of(w))] if fre else []
        res.append({"keyword": p, "docs_in_corpus": n, "openalex_hits": total, "self_match": self_match,
                    "top50_on_topic": len(on), "top50_topic_regex": len(on_re),
                    "top50_new": len(new), "top50": len(top),
                    "examples_new": [{"year": w["publication_year"], "cites": w["cited_by_count"],
                                      "title": w["title"], "id": short(w["id"])} for w in new[:5]]})
        print(f"{p:42s} in_corpus={n:3d} hits={total:5d} in_field={len(on):2d}/{len(top)} new_in_field={len(new):2d}"
              + (f" topic_regex={len(on_re)}/{len(top)}" if fre and not self_match else ""))
        for e in res[-1]["examples_new"][:3]:
            print(f"      {e['year']} {e['cites']:5d}  {e['title'][:95]}")
    (d / "keywords.json").write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")

