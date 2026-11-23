"""Adoption share of a method among the papers that cite the seeds (offline; logged so a verdict can cite it).

Denominator: forward (citing) papers only, i.e. records with role "forward" in corpus.json, whose title + abstract
match --scope. Records that entered only through keyword/query or ancestor widening are excluded: those were
selected by our own search words and would inflate (or bias) the base. Founder works themselves are left out
of the denominator even when they cite each other. Numerator: those that also match --method.
Self-citation: share of numerator papers sharing at least one OpenAlex author ID with a founder work
(--founders, else the seed_ids of --lineage, else the corpus seeds).

Every run is appended to DATA_DIR/adoption.json with its regexes, roles, counts and date, and gets an id
("adoption#3") that the verdict text can cite.

Usage:
  lineage adoption DATA_DIR --scope 'lithium.ion|Li-ion' --method 'physics.informed|neural network' [--since 2018]
                   [--founders W1,W2 | --lineage lineage.json] [--list]
Matching is case-insensitive over title + abstract. Papers without an abstract in OpenAlex are matched on the
title only, so counts are lower bounds (their number is reported).
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
from collections import Counter
from pathlib import Path

from .mentions import text_of

ROLES = ("forward",)


def short(wid) -> str:
    return str(wid).rsplit("/", 1)[-1]


def author_ids(w) -> set:
    return {short(a["author"]["id"]) for a in (w.get("authorships") or [])
            if (a.get("author") or {}).get("id")}


def founders_of(a, corpus: dict) -> tuple[list, str]:
    if a.founders:
        return [short(x.strip()) for x in a.founders.split(",") if x.strip()], "--founders"
    if a.lineage:
        L = json.loads(Path(a.lineage).read_text(encoding="utf-8"))
        ids = [short(x) for x in (L.get("meta") or {}).get("seed_ids", [])]
        if ids:
            return ids, f"seed_ids of {Path(a.lineage).name}"
    return sorted(k for k, w in corpus.items() if "seed" in w.get("_role", [])), "corpus seeds"


def run(d: Path, scope: str, method: str, since: int | None = None, founders: list | None = None,
        founders_from: str = "", roles=ROLES) -> dict:
    corpus = json.loads((d / "corpus.json").read_text(encoding="utf-8"))
    meta_p = d / "refs_meta.json"
    sc, me = re.compile(scope, re.I), re.compile(method, re.I)
    founders = founders or []
    # a founder that cites another founder is also "forward"; it is the origin, not an adopter: leave it out
    base = {k: w for k, w in corpus.items() if set(roles) & set(w.get("_role", [])) and k not in founders
            and (since is None or (w.get("publication_year") or 0) >= since)}
    widened = sum(1 for w in corpus.values() if not set(roles) & set(w.get("_role", []))
                  and any(r.startswith("keyword:") or r == "ancestor-forward" for r in w.get("_role", [])))
    den = {k: w for k, w in base.items() if sc.search(text_of(w))}
    num = {k: w for k, w in den.items() if me.search(text_of(w))}
    f_authors, partial = set(), []
    meta = None
    for f in founders:
        w = corpus.get(f)
        if w is None:
            if meta is None:
                meta = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else {}
            w = meta.get(f)
            if w is not None:
                partial.append(f)  # refs_meta keeps only the first author
        if w is not None:
            f_authors |= author_ids(w)
    self_ids = sorted(k for k, w in num.items() if author_ids(w) & f_authors)
    years = sorted({w.get("publication_year") for w in den.values() if w.get("publication_year")})
    per_year = {str(y): {"scope": sum(1 for w in den.values() if w.get("publication_year") == y),
                         "method": sum(1 for w in num.values() if w.get("publication_year") == y)} for y in years}
    for v in per_year.values():
        v["share"] = round(v["method"] / v["scope"], 3) if v["scope"] else 0.0
    return {
        "date": datetime.date.today().isoformat(), "data_dir": str(d), "scope": scope, "method": method,
        "since": since, "roles": list(roles), "excluded_widened": widened,
        "base": len(base), "denominator": len(den), "numerator": len(num),
        "share": round(len(num) / len(den), 3) if den else 0.0,
        "no_abstract": sum(1 for w in den.values() if not w.get("abstract_inverted_index")),
        "per_year": per_year,
        # undated records count in the totals but not in per_year (and are dropped by --since)
        "no_year": sum(1 for w in den.values() if not w.get("publication_year")),
        "founders": founders, "founders_from": founders_from, "founder_authors": len(f_authors),
        "founders_first_author_only": partial,
        "self_citing": len(self_ids), "self_share": round(len(self_ids) / len(num), 3) if num else 0.0,
        "self_citing_ids": self_ids, "numerator_ids": sorted(num),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="lineage adoption")
    ap.add_argument("data_dir")
    ap.add_argument("--scope", required=True, help="regex: papers about the object (denominator)")
    ap.add_argument("--method", required=True, help="regex: papers that use the method (numerator)")
    ap.add_argument("--since", type=int)
    ap.add_argument("--founders", default="", help="comma-separated OpenAlex IDs of the founder works")
    ap.add_argument("--lineage", default="", help="lineage.json whose meta.seed_ids are the founders")
    ap.add_argument("--list", action="store_true", help="list the numerator papers")
    a = ap.parse_args(argv)
    re.compile(a.scope)
    re.compile(a.method)
    d = Path(a.data_dir)
    corpus = json.loads((d / "corpus.json").read_text(encoding="utf-8"))
    founders, src = founders_of(a, corpus)
    res = run(d, a.scope, a.method, a.since, founders, src)
    log_p = d / "adoption.json"
    log = json.loads(log_p.read_text(encoding="utf-8")) if log_p.exists() else []
    res = {"id": f"adoption#{len(log) + 1}", **res}
    log.append(res)
    log_p.write_text(json.dumps(log, indent=1, ensure_ascii=False), encoding="utf-8")

    print(f"{res['id']}  ({log_p})")
    print(f"denominator: forward (citing) papers matching scope /{a.scope}/"
          + (f" since {a.since}" if a.since else "") + f": {res['denominator']} of {res['base']} forward papers "
          f"({res['excluded_widened']} widened-only records excluded)")
    print(f"numerator  : also matching method /{a.method}/: {res['numerator']} ({res['share']:.0%})")
    print(f"no abstract: {res['no_abstract']} of the denominator (title-only match; counts are lower bounds)")
    for y, v in res["per_year"].items():
        print(f"  {y}: {v['method']}/{v['scope']} ({v['share']:.0%})")
    if res["no_year"]:
        print(f"no year    : {res['no_year']} of the denominator have no publication year (in the totals, "
              f"not in the per-year rows)")
    note = f"; {len(res['founders_first_author_only'])} founder(s) known by first author only" \
        if res["founders_first_author_only"] else ""
    print(f"self-citation: {res['self_citing']}/{res['numerator']} ({res['self_share']:.0%}) numerator papers share an "
          f"author with the founders ({len(founders)} works from {src}, {res['founder_authors']} author IDs{note})")
    if a.list:
        for k in sorted(res["numerator_ids"], key=lambda k: -(corpus[k].get("publication_year") or 0)):
            w = corpus[k]
            mark = " [self]" if k in res["self_citing_ids"] else ""
            print(f"  {w.get('publication_year')} {k} {(w.get('title') or '')[:90]}{mark}")
    print(f"cite as: {res['id']} = {res['numerator']}/{res['denominator']} forward papers"
          + (f" (latest year {list(res['per_year'])[-1]}: {list(res['per_year'].values())[-1]['method']}/"
             f"{list(res['per_year'].values())[-1]['scope']})" if res["per_year"] else ""))
    return 0
