"""Check evidence records' bibliographic metadata against Crossref before a report ships.

  scholarly-access-agent refs check <evidence folder or .json files> [--offline]

For every record with a DOI (in `paper_id` or `journal_version`) it fetches the Crossref
record and compares title, year, first author's family name and venue, and maps the
Crossref item type to a suggested `venue_type`. Records without a DOI (many Korean items)
are listed for a manual KCI/RISS check. Only DOIs are sent to Crossref.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote
from urllib.request import Request, urlopen

CROSSREF = "https://api.crossref.org/works/"
TYPE_TO_VENUE = {
    "journal-article": "journal",
    "proceedings-article": "conference_paper",
    "posted-content": "preprint",
    "dissertation": "thesis",
    "report": "report",
    "report-component": "report",
    "book-chapter": "book",
    "book": "book",
    "monograph": "book",
}
DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>]+", re.IGNORECASE)


def find_doi(record: dict) -> str | None:
    for key in ("paper_id", "journal_version", "doi"):
        value = record.get(key)
        if isinstance(value, str):
            match = DOI_RE.search(value)
            if match:
                return match.group(0).rstrip(".,;)").lower()
    return None


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^0-9a-z가-힣]+", " ", text.lower()).strip()


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def fetch_crossref(doi: str, timeout: int = 20) -> dict | None:
    request = Request(CROSSREF + quote(doi, safe="/"), headers={"User-Agent": "scholarly-access-agent refs-check"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response).get("message")
    except Exception:
        return None


def _first_author(record: dict) -> str:
    authors = record.get("authors")
    if isinstance(authors, list) and authors:
        first = authors[0]
        return first.get("family", "") if isinstance(first, dict) else str(first)
    if isinstance(authors, str):
        return re.split(r"[;,]| and ", authors)[0]
    return ""


_STOP = {"of", "the", "and", "for", "in", "on", "de", "a"}


def _venue_match(mine: str, theirs: str) -> bool:
    """Full-name similarity, or an acronym in the record (PNAS, PRB, JCTC) matching the initials."""
    if similarity(mine, theirs) >= 0.5 or _norm(theirs) in _norm(mine):
        return True
    words = _norm(mine).split()
    first = words[0] if words else ""
    initials = "".join(w[0] for w in _norm(theirs).split() if w not in _STOP)
    return len(first) >= 2 and initials.startswith(first)


def compare(record: dict, cr: dict) -> dict[str, Any]:
    issues: list[str] = []
    cr_title = (cr.get("title") or [""])[0]
    title_sim = similarity(record.get("title", ""), cr_title)
    if record.get("title") and title_sim < 0.85:
        issues.append(f"title differs (similarity {title_sim:.2f}): Crossref '{cr_title[:90]}'")
    issued = (cr.get("issued") or {}).get("date-parts") or [[None]]
    cr_year = issued[0][0] if issued and issued[0] else None
    if record.get("year") and cr_year and int(record["year"]) != int(cr_year):
        issues.append(f"year {record['year']} vs Crossref {cr_year}")
    cr_authors = cr.get("author") or []
    cr_family = cr_authors[0].get("family", "") if cr_authors else ""
    mine = _first_author(record)
    if mine and cr_family and _norm(cr_family) not in _norm(mine) and _norm(mine) not in _norm(cr_family):
        issues.append(f"first author '{mine.strip()[:40]}' vs Crossref '{cr_family}'")
    venue = (cr.get("container-title") or [""])[0]
    if record.get("venue") and venue and not _venue_match(record["venue"], venue):
        issues.append(f"venue '{record['venue'][:50]}' vs Crossref '{venue[:50]}'")
    suggested = TYPE_TO_VENUE.get(cr.get("type", ""), cr.get("type"))
    if record.get("venue_type") and suggested and record["venue_type"] != suggested:
        issues.append(f"venue_type '{record['venue_type']}' vs Crossref type '{cr.get('type')}' -> '{suggested}'")
    return {"crossref_title": cr_title, "crossref_year": cr_year, "crossref_first_author": cr_family,
            "crossref_venue": venue, "crossref_type": cr.get("type"), "suggested_venue_type": suggested,
            "issues": issues}


def check(paths: list[Path], fetch: Callable[[str], dict | None] = fetch_crossref, offline: bool = False) -> dict:
    files: list[Path] = []
    for path in paths:
        files += sorted(path.glob("*.json")) if path.is_dir() else [path]
    rows = []
    for file in files:
        try:
            record = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            rows.append({"file": file.name, "status": "unreadable", "issues": [str(exc)]})
            continue
        doi = find_doi(record)
        row: dict[str, Any] = {"file": file.name, "doi": doi}
        if not doi:
            row.update(status="manual", issues=["no DOI: check title, authors, year and venue in KCI/RISS or the publisher page"])
        elif offline:
            row.update(status="skipped", issues=[])
        else:
            cr = fetch(doi)
            if cr is None:
                row.update(status="not_found", issues=["DOI not resolved by Crossref (KCI/DataCite DOIs: check manually)"])
            else:
                row.update(compare(record, cr))
                row["status"] = "mismatch" if row["issues"] else "ok"
        if not record.get("venue_type"):
            row.setdefault("issues", []).append("record has no venue_type")
        rows.append(row)
    summary = {s: sum(1 for r in rows if r["status"] == s) for s in ("ok", "mismatch", "manual", "not_found", "skipped", "unreadable")}
    return {"checked": len(rows), "summary": summary, "records": rows}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="scholarly-access-agent refs", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    c = sub.add_parser("check", help="Compare evidence records with Crossref metadata.")
    c.add_argument("paths", nargs="+", help="evidence folder(s) or record .json files")
    c.add_argument("--offline", action="store_true", help="only list DOIs and missing fields; no network")
    a = ap.parse_args(argv)
    out = check([Path(p) for p in a.paths], offline=a.offline)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0 if out["summary"]["mismatch"] == 0 and out["summary"]["unreadable"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
