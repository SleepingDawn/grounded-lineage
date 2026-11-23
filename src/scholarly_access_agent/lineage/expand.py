"""One-hop citation expansion for a plain review (snowballing), not a lineage corpus.

From a few seed papers already judged central, list their references (backward) and the
papers citing them (forward), ranked by how many seeds each one connects to plus a small
bonus for citations per year (score = links + 0.5*log10(1 + citations/year)). Candidates already screened (--known) are flagged, so the output
shows what the web search missed. Citing papers are capped per seed: half most-cited,
half newest, so recent work with few citations is kept.

Usage:
  lineage expand SEED [SEED ...] [--known evidence/ --known 10.1038/x ...]
                 [--per-seed 40] [--top 40] [--since 2018] [--out data/expansion.json]
SEED: DOI, arXiv:ID or OpenAlex ID (W...). --known: DOIs/IDs, or files/folders whose
text holds DOIs, arXiv IDs or JSON "title" fields (an evidence/ folder, a candidate log).
Prints JSON.
About 3 + references/50 OpenAlex requests per seed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import re
from pathlib import Path

from .openalex import fetch_citing, fetch_many, norm_doi, resolve_dois, short

FIELDS = "id,doi,title,publication_year,cited_by_count,primary_location,type,referenced_works"
DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>,;)\]]+", re.I)
WID = re.compile(r"W\d+")                 # a value that is an OpenAlex ID
WID_IN_TEXT = re.compile(r"\bW\d{6,}\b")  # OpenAlex IDs inside free text (real IDs are long)
ARXIV_RE = re.compile(r"arxiv(?:\.org/(?:abs|pdf)/|:\s*|\.)(\d{4}\.\d{4,5})", re.I)
TITLE_RE = re.compile(r'"title"\s*:\s*"((?:[^"\\]|\\.){12,})"')


def resolve_seeds(seeds: list[str]) -> list[str]:
    ids, dois = [], []
    for s in seeds:
        s = s.strip()
        if WID.fullmatch(short(s)):
            ids.append(short(s))
        elif s.lower().startswith("arxiv:"):
            dois.append("10.48550/arxiv." + s.split(":", 1)[1])
        else:
            dois.append(s)
    found = resolve_dois(dois) if dois else {}
    missing = [d for d in dois if norm_doi(d) not in found]
    if missing:
        raise ValueError(f"not in OpenAlex: {', '.join(missing)}")
    return ids + [found[norm_doi(d)] for d in dois]


def norm_title(title: str) -> str:
    return re.sub(r"[^0-9a-z]+", " ", title.lower()).strip()


def known_keys(values: list[str]) -> tuple[set[str], set[str], set[str]]:
    """(DOIs, OpenAlex IDs, normalised titles) from literal values and from the text of
    files or folders. arXiv IDs count as their 10.48550 DOIs; titles come from JSON
    "title" fields, because evidence records do not always carry a DOI."""
    dois: set[str] = set()
    wids: set[str] = set()
    titles: set[str] = set()
    for v in values:
        if WID.fullmatch(short(v.strip())):
            wids.add(short(v.strip()))
            continue
        p = Path(v)
        texts = []
        if p.is_dir():
            texts = [f.read_text(encoding="utf-8", errors="ignore")
                     for f in sorted(p.rglob("*")) if f.is_file() and f.suffix in {".json", ".md", ".txt", ".csv", ".jsonl"}]
        elif p.is_file():
            texts = [p.read_text(encoding="utf-8", errors="ignore")]
        else:
            texts = [v]
        for t in texts:
            dois |= {norm_doi(m.rstrip(".")) for m in DOI_RE.findall(t)}
            dois |= {"10.48550/arxiv." + m for m in ARXIV_RE.findall(t)}
            wids |= set(WID_IN_TEXT.findall(t))
            for m in TITLE_RE.findall(t):
                try:
                    titles.add(norm_title(json.loads(f'"{m}"')))
                except ValueError:
                    titles.add(norm_title(m))
    return dois, wids, titles


def venue(w: dict) -> str:
    return (((w.get("primary_location") or {}).get("source") or {}).get("display_name")) or ""


def expand(seeds: list[str], per_seed: int = 40, since: int | None = None,
           known: tuple = (set(), set(), set())) -> list[dict]:
    seed_works = fetch_many(seeds, FIELDS)
    links: dict[str, dict[str, set[str]]] = {}

    def link(wid: str, seed: str, how: str) -> None:
        if wid not in seed_works:
            links.setdefault(wid, {"backward": set(), "forward": set()})[how].add(seed)

    for s, w in seed_works.items():
        for r in w.get("referenced_works") or []:
            link(short(r), s, "backward")
    works = fetch_many([k for k in links], FIELDS)
    for s in seed_works:
        citing = fetch_citing(s, per_seed)
        for k, w in citing.items():
            link(k, s, "forward")
            works.setdefault(k, w)

    year_now = dt.date.today().year
    known_dois, known_ids, *rest = known
    known_titles = rest[0] if rest else set()
    rows = []
    for k, rel in links.items():
        w = works.get(k)
        if not w:
            continue
        year = w.get("publication_year") or 0
        if since and year < since:
            continue
        doi = norm_doi(w["doi"]) if w.get("doi") else ""
        cites = w.get("cited_by_count") or 0
        rows.append({
            "openalex": k, "doi": doi, "title": w.get("title") or "", "year": year,
            "venue": venue(w), "type": w.get("type") or "", "cited_by": cites,
            "cites_per_year": round(cites / max(1, year_now - year + 1), 1) if year else 0,
            "links": len(rel["backward"] | rel["forward"]),
            "cited_by_seeds": sorted(rel["backward"]), "cites_seeds": sorted(rel["forward"]),
            "known": bool(k in known_ids or (doi and doi in known_dois)
                          or norm_title(w.get("title") or "") in known_titles),
        })
    for r in rows:
        # Seed links lead; citations per year add at most about one link's worth, so a new
        # paper that merely cites every seed does not outrank a well-used one with one link fewer.
        r["score"] = round(r["links"] + 0.5 * math.log10(1 + r["cites_per_year"]), 2)
    rows.sort(key=lambda r: (-r["score"], r["known"]))
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="lineage expand", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("seeds", nargs="+")
    ap.add_argument("--known", action="append", default=[])
    ap.add_argument("--per-seed", type=int, default=40, help="citing papers kept per seed")
    ap.add_argument("--top", type=int, default=40, help="candidates printed (0 = all)")
    ap.add_argument("--since", type=int, help="drop candidates published before this year")
    ap.add_argument("--include-known", action="store_true", help="also list already screened papers")
    ap.add_argument("--out", help="also write the full ranked list as JSON here")
    a = ap.parse_args(argv)

    seeds = resolve_seeds(a.seeds)
    rows = expand(seeds, a.per_seed, a.since, known_keys(a.known))
    shown = [r for r in rows if a.include_known or not r["known"]]
    if a.top:
        shown = shown[:a.top]
    summary = {"seeds": seeds, "candidates": len(rows), "new": sum(not r["known"] for r in rows),
               "known": sum(bool(r["known"]) for r in rows), "shown": len(shown)}
    if a.out:
        out = Path(a.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({**summary, "date": dt.date.today().isoformat(), "rows": rows},
                                  ensure_ascii=False, indent=1), encoding="utf-8")
        summary["out"] = str(out)
    print(json.dumps({**summary, "rows": shown}, ensure_ascii=False, indent=1))
    return 0
