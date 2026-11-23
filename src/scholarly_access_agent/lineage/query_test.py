"""Test a boolean search query before using it to widen the corpus.

Reports for one query:
  hits        total OpenAlex works matching it in title + abstract
  precision   share of the top N (by relevance) that cite a core paper of the field (lineage/topic.py);
              wording-independent. --focus adds a weaker regex check on title + abstract
  recall      how many gold papers (known key papers) the query finds; missed ones are listed,
              flagged when OpenAlex has no abstract for them (title-only match is then the limit)
  novelty     on-topic papers in the top N that are not yet in the corpus or its references
  saturated   novelty < 10% of the on-topic top N: this query adds little; stop varying it
Each run is appended to DATA_DIR/queries.json (the search log shown on the page), with the gold source.
Gold: --gold IDs, --gold-file (independent, e.g. frozen with `lineage gold freeze`; DATA_DIR/gold.json is used by
default when no other gold is given: "gold: independent (N)"), or --gold-from-lineage (circular: the agent chose
those papers; "gold: from curated lineage (circular)"). After the run, if no logged query is SATURATED, an
"UNSATURATED: ..." line says so.

Usage:
  lineage query-test DATA_DIR 'QUERY' --focus 'regex' --gold-from-lineage lineage.json [--top 100] [--list 15]
  lineage query-test DATA_DIR 'QUERY' --gold W123,W456
  lineage query-test DATA_DIR 'QUERY' --gold-file gold.json   (independent gold; DATA_DIR/gold.json is the default)
  lineage query-test DATA_DIR 'Q1' 'Q2' 'Q3' --label q1 --label q2 --label q3 --gold-from-lineage lineage.json
    Batch: the queries are fetched in parallel (shared rate limit), then reported and logged in
    the given order, so strategy recall accumulates as if they had been run one by one. A
    summary table closes the run.
QUERY is OpenAlex boolean syntax: "exact phrase", AND, OR, NOT, parentheses. Commas are not allowed.
Example (one concept block per parenthesis):
  '("charge equilibration" OR "electronegativity equalization" OR "fluctuating charge" OR QEq)
   AND ("neural network" OR "machine learning" OR "machine-learned") NOT (photovoltaic OR battery)'
"""
import argparse
import datetime
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .gold import load_ids as load_gold
from .openalex import check_query, get, search as oa_search, short
from .searchlog import saturation, unsaturated_line
from .topic import core_set, in_field

SELECT = "id,title,publication_year,cited_by_count,abstract_inverted_index,referenced_works"


def text_of(w):
    ii = w.get("abstract_inverted_index") or {}
    pos = sorted((p, t) for t, ps in ii.items() for p in ps)
    return (w.get("title") or "") + " " + " ".join(t for _, t in pos)


def search(q, n):
    return oa_search(q, n, select=SELECT)


def gold_ids(a):
    """(gold IDs, source): source is 'given' (--gold), 'independent' (--gold-file or DATA_DIR/gold.json),
    'lineage' (--gold-from-lineage: circular) or '' (no gold)."""
    if a.gold:
        return [short(x.strip()) for x in a.gold.split(",") if x.strip()], "given"
    if a.gold_file:
        return load_gold(Path(a.gold_file)), "independent"
    if a.gold_from_lineage:
        L = json.loads(Path(a.gold_from_lineage).read_text(encoding="utf-8"))
        ids = [n.get("openalex") for n in L.get("nodes", [])] + [r.get("openalex") for r in L.get("rows", [])]
        return list(dict.fromkeys(i for i in ids if i)), "lineage"
    frozen = Path(a.data_dir) / "gold.json"
    if frozen.exists():
        return load_gold(frozen), "independent"
    return [], ""


GOLD_LINE = {"independent": "gold: independent ({n})", "lineage": "gold: from curated lineage (circular) ({n})",
             "given": "gold: given list ({n})"}


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


def fetch(query, top_n, gold):
    """Network part of one query test (search + recall); safe to run in parallel threads."""
    r = search(query, top_n)
    found, missed = recall(query, gold) if gold else (set(), [])
    return r, found, missed


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir")
    ap.add_argument("query", nargs="+",
                    help="one or more queries; several are fetched in parallel and logged in order")
    ap.add_argument("--focus", default="")
    ap.add_argument("--gold", default="")
    ap.add_argument("--gold-from-lineage", default="",
                    help="gold = the curated lineage's papers (circular: the agent chose them)")
    ap.add_argument("--gold-file", default="",
                    help="independent gold: a gold.json from `lineage gold freeze` or a file of OpenAlex IDs; "
                         "default DATA_DIR/gold.json when it exists and no other gold is given")
    ap.add_argument("--top", type=int, default=100)
    ap.add_argument("--list", type=int, default=15)
    ap.add_argument("--label", action="append", default=[],
                    help="label per query, repeated in the same order as the queries")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args(argv)
    if len(a.label) > len(a.query):
        ap.error(f"{len(a.label)} labels for {len(a.query)} queries")
    for q in a.query:
        check_query(q)  # reject every malformed query before any network call
    d = Path(a.data_dir)
    gold, a.gold_source = gold_ids(a)
    if gold:
        print(GOLD_LINE[a.gold_source].format(n=len(gold)))
    if len(a.query) == 1:
        results = [fetch(a.query[0], a.top, gold)]
    else:
        with ThreadPoolExecutor(max_workers=max(1, min(a.workers, len(a.query)))) as pool:
            results = list(pool.map(lambda q: fetch(q, a.top, gold), a.query))
    summary = []
    for i, (q, res) in enumerate(zip(a.query, results)):
        label = a.label[i] if i < len(a.label) else ""
        if len(a.query) > 1:
            print(f"\n######## [{i + 1}/{len(a.query)}] {label}")
        summary.append(report_one(d, a, q, label, gold, *res))
    if len(summary) > 1:
        print("\n== batch summary ==")
        print(f"{'label':28s} {'hits':>8s} {'prec':>5s} {'recall':>7s} {'novel':>6s}  strategy")
        for s in summary:
            print(f"{s['label'][:28]:28s} {s['hits']:>8,} {s['precision']:>5.0%} "
                  f"{s['recall']:>7s} {s['novelty']:>6.0%}  {s['strategy']}{'  SATURATED' if s['saturated'] else ''}")
    state = saturation(d)
    if state and not state["saturated"]:
        print(f"{unsaturated_line(state)}; none of the {state['n']} logged queries in {d / 'queries.json'} "
              "is SATURATED, so the search has not converged: vary the vocabulary or report it as unsaturated")


def report_one(d, a, query, label, gold, r, found, missed):
    known = set()
    for name in ("corpus.json", "refs_meta.json"):
        p = d / name
        if p.exists():
            known |= set(json.loads(p.read_text(encoding="utf-8")))
    focus = re.compile(a.focus, re.I) if a.focus else None

    total = r["meta"]["count"]
    top = r["results"][:a.top]
    core = core_set(d)
    on = [w for w in top if in_field(w, core)]  # citation-anchored: cites a core paper of the field
    on_re = [w for w in top if focus.search(text_of(w))] if focus else []
    new_on = [w for w in on if short(w["id"]) not in known]
    precision = len(on) / max(1, len(top))
    novelty = len(new_on) / max(1, len(on))

    print(f"query    : {query}")
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
    strategy = "-"
    if gold:
        # the search strategy is the union of all queries: judge recall on that, not per query
        union = set(found)
        for e in log:
            union |= set(e.get("gold_found_ids", []))
        union &= set(gold)
        strategy = f"{len(union)}/{len(gold)} ({len(union)/len(gold):.0%})"
        print(f"strategy recall (all logged queries + this one): {strategy}")
    log.append({"date": datetime.date.today().isoformat(), "label": label, "query": query,
                "hits": total, "top": len(top), "on_topic": len(on), "precision": round(precision, 3),
                "gold": len(gold), "gold_source": getattr(a, "gold_source", "") if gold else "",
                "gold_found": len(found), "gold_found_ids": sorted(found),
                "new_on_topic": len(new_on),
                "novelty": round(novelty, 3), "saturated": bool(on) and novelty < 0.10,
                "new_examples": [{"id": short(w["id"]), "year": w.get("publication_year"),
                                  "cites": w.get("cited_by_count"), "title": w.get("title")}
                                 for w in sorted(new_on, key=lambda w: -(w.get("cited_by_count") or 0))[:5]]})
    log_p.write_text(json.dumps(log, indent=1, ensure_ascii=False), encoding="utf-8")
    return {"label": label or query[:28], "hits": total, "precision": precision,
            "recall": f"{len(found)}/{len(gold)}" if gold else "-", "novelty": novelty,
            "saturated": bool(on) and novelty < 0.10, "strategy": strategy}

