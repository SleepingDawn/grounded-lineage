"""Resolve a journal-first link for each OpenAlex work ID.

Priority:
  1. the work's own DOI when it is not a preprint/repository DOI
  2. a journal/conference location listed on the same OpenAlex work
  3. another OpenAlex record with the same title that has a journal DOI
     (OpenAlex sometimes keeps the preprint and the journal version apart)
  4. fallback: the preprint landing page (marked kind="preprint")

Usage: lineage links OUT_JSON ID [ID ...]
       lineage links OUT_JSON --from-lineage lineage.json   (all node and row IDs)
Results are saved after each ID, so an interrupted run keeps what it resolved.
"""
import json
import re
import sys
from pathlib import Path

from .openalex import get, short

# preprint servers, including engineering ones: TechRxiv (10.36227), engrXiv (10.31224), Preprints.org (10.20944)
PREPRINT_DOI = ("10.48550/", "10.5281/", "10.21203/", "10.26434/", "10.1101/", "10.2139/", "10.22541/",
                "10.36227/", "10.31224/", "10.20944/")
PREPRINT_HOST = re.compile(r"arxiv\.org|chemrxiv|biorxiv|medrxiv|researchsquare|zenodo|ssrn|authorea|techrxiv|engrxiv"
                           r"|preprints\.org|essopenarchive", re.I)


def norm(t):
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())


def is_preprint_doi(doi):
    d = (doi or "").lower().replace("https://doi.org/", "")
    return (not d) or d.startswith(PREPRINT_DOI)


def work(wid):
    """Single-work lookup through the shared backoff/quota handling."""
    res = get({"filter": f"openalex_id:{short(wid)}", "per-page": 1})["results"]
    if not res:
        raise KeyError(f"{wid} not found in OpenAlex")
    return res[0]


def venue(loc):
    src = (loc or {}).get("source") or {}
    return src.get("display_name"), src.get("type")


def resolve(w):
    doi = (w.get("doi") or "").replace("https://doi.org/", "")
    if doi and not is_preprint_doi(doi):
        v, _ = venue(w.get("primary_location"))
        return {"url": f"https://doi.org/{doi}", "kind": "journal", "venue": v, "doi": doi}
    for loc in w.get("locations") or []:
        v, typ = venue(loc)
        url = loc.get("landing_page_url") or ""
        if typ in ("journal", "conference") and url and not PREPRINT_HOST.search(url):
            m = re.search(r"10\.\d{4,}/\S+", url)
            if m and not is_preprint_doi(m.group(0)):
                return {"url": f"https://doi.org/{m.group(0)}", "kind": "journal", "venue": v, "doi": m.group(0)}
            return {"url": url, "kind": "journal", "venue": v, "doi": None}
    # look for a separate journal record with the same title
    title = w.get("title") or ""
    if title:
        r = get({"filter": "title.search:" + re.sub(r"[,:|]", " ", title)[:200], "per-page": 10})
        for c in r.get("results", []):
            cd = (c.get("doi") or "").replace("https://doi.org/", "")
            if norm(c.get("title")) == norm(title) and cd and not is_preprint_doi(cd):
                v, _ = venue(c.get("primary_location"))
                return {"url": f"https://doi.org/{cd}", "kind": "journal", "venue": v, "doi": cd,
                        "via": short(c["id"])}
    loc = w.get("primary_location") or {}
    v, _ = venue(loc)
    url = (f"https://doi.org/{doi}" if doi else None) or loc.get("landing_page_url") or w.get("id")
    return {"url": url, "kind": "preprint", "venue": v, "doi": doi or None}


def ids_from_lineage(path):
    L = json.loads(Path(path).read_text(encoding="utf-8"))
    ids = [n["openalex"] for n in L.get("nodes", []) if n.get("openalex")]
    ids += [r["openalex"] for r in L.get("rows", []) if r.get("openalex")]
    return list(dict.fromkeys(ids))


def main(argv=None):
    argv = argv if argv is None else list(argv)
    out = Path(argv[0])
    res = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    args = argv[1:]
    ids = ids_from_lineage(args[1]) if args[:1] == ["--from-lineage"] else args
    for wid in ids:
        wid = short(wid)
        if wid in res:
            continue
        w = work(wid)
        a = w.get("authorships") or []
        first = a[0]["author"]["display_name"] if a else ""
        info = resolve(w)
        info.update({"title": w.get("title"), "year": w.get("publication_year"),
                     "cites": w.get("cited_by_count"), "first_author": first, "n_authors": len(a)})
        res[wid] = info
        out.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")  # save as we go
        print(f"{wid} [{info['kind']:8}] {info['venue']} | {info['url']} | {(info['title'] or '')[:60]}")

