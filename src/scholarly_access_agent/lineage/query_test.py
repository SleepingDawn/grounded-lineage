"""Test a boolean search query before using it to widen the corpus.

Reports for one query:
  hits        total OpenAlex works matching it in title + abstract
  precision   share of the top N (by relevance) that cite a core paper of the field (lineage/topic.py);
              wording-independent. --focus adds a weaker regex check on title + abstract
  recall      how many gold papers (known key papers) the query finds; missed ones are listed,
              flagged when OpenAlex has no abstract for them (title-only match is then the limit)
  novelty     on-topic papers in the top N that are not yet in the corpus or its references
  saturated   novelty < 10% of the on-topic top N: this query adds little; stop varying it
Each run is appended to DATA_DIR/queries.json (the search log shown on the page).

Usage:
  lineage query-test DATA_DIR 'QUERY' --focus 'regex' --gold-from-lineage lineage.json [--top 100] [--list 15]
  lineage query-test DATA_DIR 'QUERY' --gold W123,W456
QUERY is OpenAlex boolean syntax: "exact phrase", AND, OR, NOT, parentheses. Commas are not allowed.
Example (one concept block per parenthesis):
  '("charge equilibration" OR "electronegativity equalization" OR "fluctuating charge" OR QEq)
   AND ("neural network" OR "machine learning" OR "machine-learned") NOT (photovoltaic OR battery)'
"""
import argparse
import datetime
import json
import re
from pathlib import Path

from .openalex import check_query, get, search as oa_search, short
from .topic import core_set, in_field

SELECT = "id,title,publication_year,cited_by_count,abstract_inverted_index,referenced_works"


def text_of(w):
    ii = w.get("abstract_inverted_index") or {}
    pos = sorted((p, t) for t, ps in ii.items() for p in ps)
    return (w.get("title") or "") + " " + " ".join(t for _, t in pos)


def search(q, n):
    return oa_search(q, n, select=SELECT)


def gold_ids(a):
    if a.gold:
        return [short(x.strip()) for x in a.gold.split(",") if x.strip()]
    if a.gold_from_lineage:
        L = json.loads(Path(a.gold_from_lineage).read_text(encoding="utf-8"))
        ids = [n.get("openalex") for n in L.get("nodes", [])] + [r.get("openalex") for r in L.get("rows", [])]
        return list(dict.fromkeys(i for i in ids if i))
    return []


def recall(q, gold):
    found = set()
    for k in range(0, len(gold), 50):
        chunk = gold[k:k + 50]
        r = get({"filter": f"title_and_abstract.search:{q},openalex_id:{'|'.join(chunk)}",
                 "per-page": 50, "select": "id"})
        found |= {short(w["id"]) for w in r["results"]}
    missed = [g for g in gold if g not in found]
    info = {}
    for k in range(0, len(missed), 50):
        r = get({"filter": "openalex_id:" + "|".join(missed[k:k + 50]), "per-page": 50,
                 "select": "id,title,publication_year,abstract_inverted_index"})
        for w in r["results"]:
            info[short(w["id"])] = w
    return found, [(g, info.get(g, {})) for g in missed]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir")
    ap.add_argument("query")
    ap.add_argument("--focus", default="")
    ap.add_argument("--gold", default="")
    ap.add_argument("--gold-from-lineage", default="")
    ap.add_argument("--top", type=int, default=100)
    ap.add_argument("--list", type=int, default=15)
    ap.add_argument("--label", default="")
    a = ap.parse_args(argv)
    check_query(a.query)
    d = Path(a.data_dir)
    known = set()
    for name in ("corpus.json", "refs_meta.json"):
        p = d / name
        if p.exists():
            known |= set(json.loads(p.read_text(encoding="utf-8")))
    focus = re.compile(a.focus, re.I) if a.focus else None

    r = search(a.query, a.top)
    total = r["meta"]["count"]
    top = r["results"][:a.top]
    core = core_set(d)
    on = [w for w in top if in_field(w, core)]  # citation-anchored: cites a core paper of the field
    on_re = [w for w in top if focus.search(text_of(w))] if focus else []
    new_on = [w for w in on if short(w["id"]) not in known]
    precision = len(on) / max(1, len(top))
    novelty = len(new_on) / max(1, len(on))

    gold = gold_ids(a)
    found, missed = recall(a.query, gold) if gold else (set(), [])

    print(f"query    : {a.query}")
    print(f"hits     : {total:,}")
    print(f"precision: {len(on)}/{len(top)} of top {len(top)} cite a core paper of the field ({precision:.0%})")
    if focus:
        print(f"topic    : {len(on_re)}/{len(top)} match --focus (weaker: trivially high if the query's own terms match it)")
    if gold:
        print(f"recall   : {len(found)}/{len(gold)} gold papers found ({len(found)/len(gold):.0%})")
        for g, w in missed:
            flag = "no abstract in OpenAlex" if w and not w.get("abstract_inverted_index") else "has abstract: query misses its wording"
            print(f"   missed {g} {w.get('publication_year', '')} {(w.get('title') or '')[:70]}  [{flag}]")
    print(f"novelty  : {len(new_on)}/{len(on)} in-field results not yet in corpus or its references ({novelty:.0%})"
          + ("  -> SATURATED" if on and novelty < 0.10 else ""))
    for w in sorted(new_on, key=lambda w: -(w.get("cited_by_count") or 0))[:a.list]:
        print(f"   new {short(w['id'])} {w.get('publication_year')} cit={w.get('cited_by_count'):<5} {(w.get('title') or '')[:85]}")

    log_p = d / "queries.json"
    log = json.loads(log_p.read_text(encoding="utf-8")) if log_p.exists() else []
    if gold:
        # the search strategy is the union of all queries: judge recall on that, not per query
        union = set(found)
        for e in log:
            union |= set(e.get("gold_found_ids", []))
        union &= set(gold)
        print(f"strategy recall (all logged queries + this one): {len(union)}/{len(gold)} ({len(union)/len(gold):.0%})")
    log.append({"date": datetime.date.today().isoformat(), "label": a.label, "query": a.query,
                "hits": total, "top": len(top), "on_topic": len(on), "precision": round(precision, 3),
                "gold": len(gold), "gold_found": len(found), "gold_found_ids": sorted(found),
                "new_on_topic": len(new_on),
                "novelty": round(novelty, 3), "saturated": bool(on) and novelty < 0.10,
                "new_examples": [{"id": short(w["id"]), "year": w.get("publication_year"),
                                  "cites": w.get("cited_by_count"), "title": w.get("title")}
                                 for w in sorted(new_on, key=lambda w: -(w.get("cited_by_count") or 0))[:5]]})
    log_p.write_text(json.dumps(log, indent=1, ensure_ascii=False), encoding="utf-8")

