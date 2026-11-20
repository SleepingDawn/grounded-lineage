"""List OpenAlex candidates for a seed paper (title words, DOI, or arXiv ID).

Usage: lineage seed "latent ewald summation"
       lineage seed 10.1038/s41524-025-01577-7
Prints: OpenAlex ID, year, citations, venue, DOI, title. Pick the journal version;
preprint and journal versions are sometimes separate records with split citations.
"""
import sys

from .openalex import get, short


def main(argv=None):
    argv = argv if argv is None else list(argv)
    q = " ".join(argv).strip()
    if q.lower().startswith(("10.", "https://doi.org/")):
        d = q.replace("https://doi.org/", "")
        res = get({"filter": f"doi:{d}", "per-page": 5})["results"]
    elif q.lower().startswith("arxiv:"):
        res = get({"filter": f"doi:10.48550/arxiv.{q.split(':', 1)[1]}", "per-page": 5})["results"]
    else:
        res = get({"filter": f"title.search:{q}", "per-page": 15, "sort": "cited_by_count:desc"})["results"]
    for w in res:
        src = ((w.get("primary_location") or {}).get("source") or {}).get("display_name") or ""
        print(f"{short(w['id'])}  {w['publication_year']}  cit={w['cited_by_count']:<5} {src[:30]:30}  "
              f"{(w.get('doi') or '').replace('https://doi.org/', '')}  | {w['title'][:100]}")

