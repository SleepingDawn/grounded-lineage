"""Evidence checks behind `lineage check` that read the local corpus (offline): are the claims in lineage.json backed?

  edge_no_citation_link       an s edge ("later built on earlier") whose later work does not cite the earlier one in
                              the OpenAlex reference lists of data/ or data_x/ (corpus.json, refs_meta.json)
  edge_no_basis               s edges without a recorded basis/evidence (edge object form)
  contested_side_not_fulltext a contested claim whose side rests on a node read below full text (or with no row)
  contested_without_x_edge    a contested pair with no x (disputes) edge between its sides
  unsaturated_search          queries.json exists and no logged query reached novelty < 10%
  not_found_without_search_log  verdict/trends/limits claim "not found" but no searches.json records the searches
  era_recent_thin             many field papers from the last three years, (almost) none in the tree
  era_founders_thin           (almost) none of the 10 most-cited ancestors in the tree
                              (meta.era_focus 'origin' / 'current' turns off the warning for the other era)

All are warnings: an old lineage.json stays valid.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .page import edge_list, edge_meta, node_levels, side_levels
from .searchlog import saturation, searches, unsaturated_line


def short(wid) -> str:
    return str(wid).rsplit("/", 1)[-1]


def corpus_dirs(L, work: Path) -> list[Path]:
    meta = L.get("meta") or {}
    dirs = [work / (meta.get("data_dir") or "data")]
    if meta.get("expanded_dir"):
        dirs.append(work / meta["expanded_dir"])
    return [d for d in dirs if d.is_dir()]


class RefIndex:
    """Reference lists of works in the local corpus files; refs_meta.json is read only when needed."""

    def __init__(self, dirs: list[Path]):
        self.dirs, self.refs, self._meta_loaded = dirs, {}, False
        for d in dirs:
            self._add(d / "corpus.json")

    def _add(self, p: Path):
        if not p.exists():
            return
        for k, w in json.loads(p.read_text(encoding="utf-8")).items():
            refs = w.get("referenced_works") or []
            if refs and short(k) not in self.refs:
                self.refs[short(k)] = {short(r) for r in refs}

    def of(self, wid: str):
        """Set of works `wid` cites, or None when its reference list is not in the local corpus."""
        if wid not in self.refs and not self._meta_loaded:
            self._meta_loaded = True
            for d in self.dirs:
                self._add(d / "refs_meta.json")
        return self.refs.get(wid)


def edge_citations(L, work: Path):
    """(warnings, summary) for the s edges: does the later work cite the earlier one?"""
    by = {n["id"]: n for n in L.get("nodes", [])}
    raw = {(s, t): e for e, (s, t, _) in zip(L.get("edges", []), edge_list(L))}
    index = RefIndex(corpus_dirs(L, work))
    linked, missing, unverifiable, warns = [], [], [], []
    for s, t, st in edge_list(L):
        if st != "s" or s not in by or t not in by:
            continue
        a, b = by[s], by[t]
        if not a.get("openalex") or not b.get("openalex"):
            unverifiable.append((s, t))
            continue
        # later = the work published later (the edge should already point that way); same year: either direction
        pairs = [(a, b), (b, a)] if a["year"] == b["year"] else [(a, b) if a["year"] < b["year"] else (b, a)]
        known = False
        hit = False
        for early, late in pairs:
            refs = index.of(late["openalex"])
            if refs is None:
                continue
            known = True
            if early["openalex"] in refs:
                hit = True
                break
        if hit:
            linked.append((s, t))
        elif not known:
            unverifiable.append((s, t))
        else:
            missing.append((s, t))
            early, late = pairs[0]
            basis = edge_meta(raw.get((s, t))).get("basis")
            note = f"; recorded basis: {basis}" if basis else "; record the basis (method/data/authors/conceptual) or use d"
            warns.append(f"edge_no_citation_link: {s} -> {t}: {late.get('sub', late['id'])} ({late['openalex']}) does "
                         f"not cite {early.get('sub', early['id'])} ({early['openalex']}) in the local OpenAlex "
                         f"reference lists{note}")
    summary = (f"s edges: {len(linked)} with citation link, {len(missing)} without, "
               f"{len(unverifiable)} unverifiable (no OpenAlex/refs)")
    return warns, summary, {"linked": linked, "missing": missing, "unverifiable": unverifiable}


def edge_basis(L) -> list[str]:
    bare = [f"{s}->{t}" for e, (s, t, st) in zip(L.get("edges", []), edge_list(L))
            if st == "s" and not edge_meta(e)]
    if not bare:
        return []
    shown = ", ".join(bare[:12]) + (f", … (+{len(bare) - 12})" if len(bare) > 12 else "")
    return [f"edge_no_basis: {len(bare)} s edge(s) have no basis/evidence; write them as "
            '{"from", "to", "type": "s", "basis": "cites|method|data|authors|conceptual", "evidence": "<locator>"}: '
            + shown]


def contested(L) -> list[str]:
    from .page import LEVEL_KO

    out = []
    levels = node_levels(L)
    x_pairs = {frozenset((s, t)) for s, t, st in edge_list(L) if st == "x"}
    for c in L.get("contested") or []:
        claim = (c.get("claim") or "")[:40]
        for side in ("side_a", "side_b"):
            weak = [(nid, lv) for nid, lv in side_levels(L, c.get(side), levels) if lv != "fulltext"]
            if weak:
                what = ", ".join(f"{nid} ({LEVEL_KO.get(lv, 'no row in the evidence table')})" for nid, lv in weak)
                out.append(f"contested_side_not_fulltext: '{claim}' {side} rests on {what}; read the full text "
                           "before calling it a dispute")
        a = set((c.get("side_a") or {}).get("nodes", []))
        b = set((c.get("side_b") or {}).get("nodes", []))
        if a and b and not any(frozenset((x, y)) in x_pairs for x in a for y in b):
            out.append(f"contested_without_x_edge: '{claim}' has no x edge between side_a {sorted(a)} and "
                       f"side_b {sorted(b)}; add one so the figure shows the dispute")
    return out


NOT_FOUND = re.compile(r"찾지 못|못 찾|발견되지 않|없었다|not found|no (?:paper|study|work)s? (?:was |were )?found", re.I)


def not_found(L, data: Path) -> list[str]:
    texts = [p for v in L.get("verdict", []) for p in [v.get("title", "")] + v.get("points", [])]
    texts += [p for t in L.get("trends", []) for p in [t.get("title", "")] + t.get("points", [])]
    texts += list(L.get("limits", []))
    hits = [t for t in texts if NOT_FOUND.search(t or "")]
    if hits and not searches(data):
        return [f"not_found_without_search_log: {len(hits)} statement(s) claim nothing was found (e.g. "
                f"'{hits[0][:60]}') but data/searches.json records no search; log each with `lineage log-search`"]
    return []


ERA_FOCUS = ("both", "origin", "current")
RECENT_YEARS = 3  # "recent" = the current year and the two before it


def era_balance(L, work: Path, today: int | None = None) -> tuple[list[str], list[str]]:
    """Does the tree cover both the field's recent work and its founding works?

    The tool measures; the agent only records the question's focus (meta.era_focus: both | origin | current, with
    meta.era_note saying why). The focus turns off the warning for the era the question is not about; it never
    narrows what was collected."""
    from datetime import date

    from .analyze import merge_versions, version_aliases

    meta = L.get("meta") or {}
    focus = meta.get("era_focus") or "both"
    today = today or date.today().year
    corpus: dict = {}
    for d in corpus_dirs(L, work):
        p = d / "corpus.json"
        if p.exists():
            corpus.update(json.loads(p.read_text(encoding="utf-8")))
    if not corpus:
        return [], []
    corpus = merge_versions(corpus, version_aliases(corpus))
    field = [w for w in corpus.values() if any(r == "forward" or r.startswith("keyword:") or r == "ancestor-forward"
                                                for r in w.get("_role", []))]
    years = [w.get("publication_year") for w in field if w.get("publication_year")]
    lo = today - RECENT_YEARS + 1
    n_recent = sum(1 for y in years if y >= lo)
    studies = [n for n in L.get("nodes", []) if n.get("kind") != "event"]
    tree_recent = sum(1 for n in studies if (n.get("year") or 0) >= lo)
    warns = []
    share = n_recent / len(years) if years else 0
    if focus != "origin" and n_recent >= 10 and share >= 0.15 and tree_recent < 2:
        warns.append(f"era_recent_thin: {n_recent} field papers ({share:.0%}) are from {lo}-{today} but the tree "
                     f"has {tree_recent} box(es) from those years; add the current work, or set meta.era_focus "
                     "'origin' with meta.era_note if the question is only about where it began")
    # founding works: the most-cited ancestors from `lineage analyze` (seeds already left out)
    core, k_in = [], None
    for d in reversed(corpus_dirs(L, work)):  # expanded corpus first
        p = d / "analysis.json"
        if p.exists():
            core = [s for _, s in json.loads(p.read_text(encoding="utf-8")).get("core_ancestors", [])[:10]]
            break
    if core:
        ids = {n.get("openalex") for n in studies if n.get("openalex")}
        missing = [s for s in core if s.rsplit("| ", 1)[-1] not in ids]
        k_in = len(core) - len(missing)
        if focus != "current" and k_in < 2:
            names = "; ".join(" | ".join(s.split(" | ")[::2])[:70] for s in missing[:3])
            warns.append(f"era_founders_thin: {k_in} of the field's 10 most-cited ancestors are boxes (missing e.g. "
                         f"{names}); add the founding works (generic tools such as software, solvers or standard test methods can stay "
                         "out), or set meta.era_focus 'current' with meta.era_note if the question is only about now")
    line = (f"era: {share:.0%} of {len(years)} field papers from {lo}-{today}, {tree_recent}/{len(studies)} boxes; "
            + (f"{k_in}/10 most-cited ancestors are boxes; " if k_in is not None else "")
            + f"focus {focus}" + (f" ({meta['era_note']})" if meta.get("era_note") else ""))
    return warns, [line]


def audit(L, work: Path) -> tuple[list[str], list[str]]:
    """(warnings, summary lines) of every corpus-backed check."""
    work = Path(work)
    data = work / ((L.get("meta") or {}).get("data_dir") or "data")
    warns, summary = [], []
    if any(st == "s" for _, _, st in edge_list(L)):
        w, line, _ = edge_citations(L, work)
        warns += w
        summary.append(line)
        warns += edge_basis(L)
    warns += contested(L)
    state = saturation(data)
    if state and not state["saturated"]:
        warns.append(f"unsaturated_search: {unsaturated_line(state)} across {state['n']} logged queries; "
                     "say so in the method section or run more query variants")
    warns += not_found(L, data)
    w, line = era_balance(L, work)
    warns += w
    summary += line
    return warns, summary
