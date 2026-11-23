"""Source-quality signals for papers, from OpenAlex (stdlib only).

Data-driven and field-general: no hand-written journal lists. Used by `refs check` (evidence records of any review)
and `lineage quality` (the boxes of a lineage).

  retracted          OpenAlex `is_retracted` (Retraction Watch data)
  not_peer_reviewed  a preprint, thesis or report, or a work hosted only in a repository
  venue_unverified   a journal with h-index < 10 and 2-year mean citedness < 0.5 in OpenAlex: young journals look
                     like this too, so it asks for a manual check (indexing, editorial board), it does not reject

Only identifiers (OpenAlex IDs, DOIs) are sent to OpenAlex.
"""
from __future__ import annotations

import re

from .lineage.openalex import get, short

WORK_SELECT = "id,doi,title,publication_year,type,is_retracted,primary_location,referenced_works,cited_by_count"
SOURCE_SELECT = "id,display_name,type,is_in_doaj,summary_stats"
NOT_PEER_REVIEWED_TYPES = ("preprint", "dissertation", "report")
LOW_H, LOW_CITEDNESS = 10, 0.5
FLAG_TEXT = {
    "retracted": "retracted (OpenAlex / Retraction Watch)",
    "not_peer_reviewed": "not peer-reviewed (preprint, thesis or report)",
    "venue_unverified": "journal with h-index < 10 and 2-year citedness < 0.5: check its indexing and editorial board",
}


def norm_doi(doi: str) -> str:
    d = (doi or "").strip().lower()
    return re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", d)


def _chunks(values, n=50):
    values = list(dict.fromkeys(v for v in values if v))
    for i in range(0, len(values), n):
        yield values[i:i + n]


def flags_of(info: dict) -> list[str]:
    out = []
    if info.get("retracted"):
        out.append("retracted")
    if info.get("type") in NOT_PEER_REVIEWED_TYPES or info.get("source_type") == "repository":
        out.append("not_peer_reviewed")
    h = info.get("h_index")
    if info.get("source_type") == "journal" and h is not None and h < LOW_H and (info.get("citedness") or 0) < LOW_CITEDNESS:
        out.append("venue_unverified")
    return out


def lookup(ids=(), dois=()) -> dict:
    """{"by_id": {W…: info}, "by_doi": {doi: info}} for the works OpenAlex knows; info carries `flags`."""
    works = []
    for chunk in _chunks(short(i) for i in ids):
        works += get({"filter": "openalex_id:" + "|".join(chunk), "per-page": 50, "select": WORK_SELECT})["results"]
    clean = [norm_doi(d) for d in dois if d and "," not in d and "|" not in d]
    for chunk in _chunks(clean):
        works += get({"filter": "doi:" + "|".join(chunk), "per-page": 50, "select": WORK_SELECT})["results"]
    sources = {}
    src_ids = [short(((w.get("primary_location") or {}).get("source") or {}).get("id") or "") for w in works]
    for chunk in _chunks(src_ids):
        for s in get({"filter": "openalex:" + "|".join(chunk), "per-page": 50, "select": SOURCE_SELECT},
                     endpoint="sources")["results"]:
            sources[short(s["id"])] = s
    by_id, by_doi = {}, {}
    for w in works:
        src = (w.get("primary_location") or {}).get("source") or {}
        s = sources.get(short(src.get("id") or ""), {})
        stats = s.get("summary_stats") or {}
        info = {"id": short(w["id"]), "doi": norm_doi(w.get("doi") or ""), "title": w.get("title"),
                "year": w.get("publication_year"), "type": w.get("type"), "retracted": bool(w.get("is_retracted")),
                "venue": src.get("display_name"), "source_type": s.get("type") or src.get("type"),
                "h_index": stats.get("h_index"), "citedness": stats.get("2yr_mean_citedness"),
                "in_doaj": s.get("is_in_doaj"), "cited_by": w.get("cited_by_count"),
                "referenced": [short(r) for r in w.get("referenced_works") or []]}
        info["flags"] = flags_of(info)
        by_id[info["id"]] = info
        if info["doi"]:
            by_doi[info["doi"]] = info
    return {"by_id": by_id, "by_doi": by_doi}
