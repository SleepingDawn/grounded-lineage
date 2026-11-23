"""Quality of the sources behind a lineage's boxes (OpenAlex; writes DATA_DIR/quality.json).

For every study box it records:
  found              where the box came from: the citation corpus, query widening, the references the collected
                     papers cite, or outside all of them (web search, reading); the report says how many boxes rest
                     on outside finds
  retracted          OpenAlex / Retraction Watch
  not_peer_reviewed  preprint, thesis or report (OpenAlex type, repository-only hosting, or the evidence record's
                     venue_type)
  abstract_only      the evidence record was read at abstract level only
  venue_unverified   a journal with h-index < 10 and 2-year citedness < 0.5 in OpenAlex (check by hand; young
                     journals look like this too)
  off_field          found outside the corpus and cites none of the field's core papers (data/core.json): an
                     outside find that the field's own literature does not anchor
`lineage check` reads quality.json offline and warns; `lineage page` draws not-peer-reviewed and abstract-only boxes
dashed. Only OpenAlex IDs are sent.

Usage: lineage quality WORK_DIR   (rerun after the boxes change)
"""
from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path

from ..quality import lookup
from .audit import corpus_dirs

PRELIM_VENUES = ("preprint", "thesis", "report", "conference_abstract", "abstract", "working_paper", "poster")
ABSTRACT_ACCESS = ("abstract_only", "unavailable")


def corpus_roles(L, work: Path) -> tuple[dict, set]:
    """({work ID: roles} for the collected corpus, IDs the collected papers cite)."""
    roles: dict = {}
    cited: set = set()
    for d in corpus_dirs(L, work):
        p = d / "corpus.json"
        if p.exists():
            for k, w in json.loads(p.read_text(encoding="utf-8")).items():
                roles.setdefault(k, set()).update(w.get("_role", []))
                cited.update(str(r).rsplit("/", 1)[-1] for r in w.get("referenced_works") or [])
    return roles, cited


def found_in(roles: set | None, cited: bool = False) -> str:
    if not roles:
        return "cited" if cited else "outside"
    return "corpus" if roles - {r for r in roles if r.startswith("keyword:")} else "widened"


def evidence_of(work: Path, stem: str | None) -> dict:
    p = work / "evidence" / f"{stem}.json"
    if not stem or not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def assess(L, work: Path, q: dict, core: set, roles: dict, cited: set = frozenset()) -> dict:
    out = {}
    for n in L.get("nodes", []):
        if n.get("kind") == "event":
            continue
        oa = n.get("openalex")
        info = q.get("by_id", {}).get(oa, {}) if oa else {}
        ev = evidence_of(work, n.get("evidence"))
        flags = list(info.get("flags", []))
        if (ev.get("venue_type") or "").lower() in PRELIM_VENUES and "not_peer_reviewed" not in flags:
            flags.append("not_peer_reviewed")
        if (ev.get("access") or "").lower() in ABSTRACT_ACCESS:
            flags.append("abstract_only")
        found = found_in(roles.get(oa), oa in cited) if oa else "outside"
        cites_core = bool(set(info.get("referenced", [])) & core) if info.get("referenced") and core else None
        if found == "outside" and cites_core is False:
            flags.append("off_field")
        out[n["id"]] = {"openalex": oa, "title": n.get("title"), "year": n.get("year"), "key": bool(n.get("key")),
                        "found": found, "flags": flags, "type": info.get("type"), "venue": info.get("venue"),
                        "h_index": info.get("h_index"), "citedness": info.get("citedness"), "cites_core": cites_core,
                        "evidence_venue_type": ev.get("venue_type"), "evidence_access": ev.get("access")}
    return out


def summary_line(nodes: dict) -> str:
    found = {k: sum(1 for v in nodes.values() if v["found"] == k) for k in ("corpus", "widened", "cited", "outside")}
    n = lambda f: sum(1 for v in nodes.values() if f in v["flags"])
    prelim = sum(1 for v in nodes.values() if {"not_peer_reviewed", "abstract_only"} & set(v["flags"]))
    return (f"quality: {len(nodes)} boxes: {found['corpus']} from the citation corpus, {found['widened']} from query "
            f"widening, {found['cited']} cited by the collected papers, {found['outside']} found outside (web search "
            f"or reading); {prelim} not peer-reviewed or read "
            f"as abstract only, {n('retracted')} retracted, {n('venue_unverified')} unverified venue(s), "
            f"{n('off_field')} off-field")


def load_quality(L, work: Path) -> dict | None:
    p = Path(work) / ((L.get("meta") or {}).get("data_dir") or "data") / "quality.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("nodes", {}) if p.exists() else None
    except (OSError, json.JSONDecodeError):
        return None


def quality_warnings(L, work: Path) -> tuple[list[str], list[str]]:
    """(warnings, summary lines) from DATA_DIR/quality.json, offline."""
    nodes = load_quality(L, work)
    if nodes is None:
        return [], ["quality: not checked (run `lineage quality .` once the boxes are settled)"]
    studies = {n["id"]: n for n in L.get("nodes", []) if n.get("kind") != "event"}
    stale = [i for i, n in studies.items() if i not in nodes or nodes[i].get("openalex") != n.get("openalex")]
    nodes = {i: v for i, v in nodes.items() if i in studies}
    name = lambda i: f"{i} ({nodes[i].get('title')}, {nodes[i].get('year')})"
    warns = []
    for i, v in nodes.items():
        if "retracted" in v["flags"]:
            warns.append(f"quality_retracted: box {name(i)} is retracted (OpenAlex / Retraction Watch); remove it, or "
                         "say on the box and in the text that it was retracted")
        if studies[i].get("key") and {"not_peer_reviewed", "abstract_only"} & set(v["flags"]):
            warns.append(f"quality_key_preliminary: key box {name(i)} is not peer-reviewed or was read as abstract "
                         "only; a key box needs a peer-reviewed, full-text source")
        if "venue_unverified" in v["flags"]:
            warns.append(f"quality_venue_unverified: box {name(i)} is in '{v.get('venue')}' (h-index {v.get('h_index')}, "
                         "2-year citedness < 0.5); check the journal's indexing (Scopus/WoS) and editorial board")
        if "off_field" in v["flags"]:
            warns.append(f"quality_off_field: box {name(i)} was found outside the corpus and cites none of the field's "
                         "core papers; check that it belongs to this field and is sound before keeping it")
    if stale:
        warns.append(f"quality_stale: {len(stale)} box(es) changed since `lineage quality` ({', '.join(stale[:5])}); "
                     "rerun it")
    return warns, [summary_line(nodes)]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="lineage quality")
    ap.add_argument("work_dir")
    a = ap.parse_args(argv)
    work = Path(a.work_dir)
    L = json.loads((work / "lineage.json").read_text(encoding="utf-8"))
    data = work / ((L.get("meta") or {}).get("data_dir") or "data")
    roles, cited = corpus_roles(L, work)
    core: set = set()
    if (data / "corpus.json").exists():
        from .topic import core_set
        core = core_set(data)
    ids = [n["openalex"] for n in L.get("nodes", []) if n.get("openalex")]
    q = lookup(ids=ids)
    nodes = assess(L, work, q, core, roles, cited)
    data.mkdir(parents=True, exist_ok=True)
    (data / "quality.json").write_text(json.dumps({"date": datetime.date.today().isoformat(), "nodes": nodes},
                                                  indent=1, ensure_ascii=False), encoding="utf-8")
    print(summary_line(nodes))
    for nid, v in nodes.items():
        if v["flags"]:
            print(f"  {nid:12s} {v['year']} {(v['title'] or '')[:24]:24s} [{v['found']}] {', '.join(v['flags'])}"
                  + (f"  ({v['venue']}, h={v['h_index']})" if "venue_unverified" in v["flags"] else ""))
    print(f"wrote {data / 'quality.json'}; `lineage check` reports it, `lineage page` draws preliminary boxes dashed")
    return 0
