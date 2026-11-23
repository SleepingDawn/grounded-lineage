"""Lineage analysis on a corpus produced by `lineage collect`.

1. Field references: everything cited by the seed + forward papers (metadata fetched).
2. RPYS: reference-year spectrum and deviation from 5-year median -> origin peaks. Counts only works outside
   the collected field (seeds and forward papers are left out: every forward paper cites the seeds, so they
   would only show up as their own peaks).
3. Core ancestors: references most often cited by the forward set (seeds left out for the same reason).
4. Branches: bibliographic-coupling network of forward papers -> Louvain clusters, labelled by the title
   words that are frequent in the cluster but not across the field.
5. Main path: SPC (search path count) weights on the citation DAG -> key-route main path: the highest-SPC
   edge, extended forward and backward along the highest-SPC edge at each step. (A global max-sum path
   favours long paths and wanders through the parent field.)

Writes DATA_DIR/analysis.json and the readable report DATA_DIR/analysis.txt; prints a short summary
(--print prints the full report too).

Usage: lineage analyze DATA_DIR [MIN_REF] [--print]
  MIN_REF: only fetch metadata for references cited by >= MIN_REF field papers. Default: the smallest value
  (1-5) that keeps the reference set at or below 5,000 works (most references are cited once; fetching
  them all can take 15+ minutes). RPYS then reflects references cited at least MIN_REF times.
"""
import json
import math
import os
import re
import statistics
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path

import networkx as nx

from .openalex import REF_FIELDS, fetch_many, short

# generic words only; topic words drop out because labels are scored against the whole field
STOP = set("""a an the of for and in on with by to from via at as is are be its their this that these into
under over between within without through toward towards using based study studies new approach approaches
method methods model models modeling modelling simulation simulations analysis application applications
investigation insights insight effect effects role case first two three high low large small use""".split())
REF_BUDGET = 5000      # automatic MIN_REF keeps the fetched reference set at or below this
SEC_PER_REQUEST = 1.5  # observed OpenAlex pace for 50-ID requests (estimate shown before fetching)
SAVE_EVERY = 60        # seconds between cache saves while fetching


def label(w):
    a = w.get("authorships") or []
    first = a[0]["author"]["display_name"].split()[-1] if a else "?"
    return f"{first} {w.get('publication_year') or 'n.d.'}"


def norm_title(t: str) -> str:
    return " ".join(re.findall(r"\w+", (t or "").lower()))


def version_rank(w) -> tuple:
    """Journal/conference record first, then the more cited, then the lower ID (stable)."""
    stype = ((w.get("primary_location") or {}).get("source") or {}).get("type") or ""
    return (stype not in ("journal", "conference", "book series"), -(w.get("cited_by_count") or 0), w.get("id", ""))


def version_aliases(corpus: dict) -> dict:
    """{duplicate ID: kept ID} for records that are versions of one paper (preprint, repository and journal
    copies are separate OpenAlex works): same normalised title (>= 25 characters), years at most 2 apart."""
    groups: dict = {}
    for k, w in corpus.items():
        t = norm_title(w.get("title"))
        if len(t) >= 25:
            groups.setdefault(t, []).append(k)
    alias = {}
    for ks in groups.values():
        if len(ks) < 2:
            continue
        ks = sorted(ks, key=lambda k: version_rank(corpus[k]))
        keep, ky = ks[0], corpus[ks[0]].get("publication_year")
        for k in ks[1:]:
            y = corpus[k].get("publication_year")
            if not (ky and y) or abs(ky - y) <= 2:
                alias[k] = keep
    return alias


def merge_versions(corpus: dict, alias: dict) -> dict:
    """Corpus with duplicates folded into the kept record (roles and references united, IDs remapped)."""
    out = {k: dict(w) for k, w in corpus.items() if k not in alias}
    for dup, keep in alias.items():
        w = out[keep]
        w["_role"] = sorted(set(w.get("_role", [])) | set(corpus[dup].get("_role", [])))
        w["referenced_works"] = list(w.get("referenced_works") or []) + list(corpus[dup].get("referenced_works") or [])
    for k, w in out.items():
        refs = dict.fromkeys(alias.get(short(r), short(r)) for r in w.get("referenced_works") or [])
        w["referenced_works"] = [r for r in refs if r != k]
    return out


def auto_min_ref(field_refs: Counter, budget: int = REF_BUDGET) -> int:
    for m in range(1, 6):
        if sum(1 for n in field_refs.values() if n >= m) <= budget:
            return m
    return 5


def save_json(p: Path, obj):
    """Atomic write: a killed run leaves the previous cache, never a truncated one."""
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(obj, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, p)


def title_words(t: str) -> set:
    words = re.findall(r"[^\W\d_](?:[\w\-]*\w)?", (t or "").lower())  # Unicode letters: 'cerámico' stays whole
    return {w for w in words if len(w) >= 3 and w not in STOP}


def cluster_words(members, df_all: Counter, n_all: int, titles: dict, n=10) -> list:
    """Words over-represented in the cluster (p_c * log(p_c / p_field)); words in half the field's titles
    (the field's own name, e.g. 'kinetic monte carlo') say nothing about a branch and are left out."""
    df = Counter()
    for k in members:
        df.update(titles[k])
    size = len(members)
    score = {}
    for w, c in df.items():
        p_c, p_all = c / size, df_all[w] / n_all
        if c >= 2 and p_all < 0.5 and p_c > p_all:
            score[w] = p_c * math.log(p_c / p_all)
    return [w for w, _ in sorted(score.items(), key=lambda x: (-x[1], x[0]))][:n]


def key_route(D, spc, year=lambda k: None) -> list:
    """Key-route main path: start at the highest-SPC edge, follow the highest-SPC edge both ways.
    Ties go to the temporally closer work, so a direct citation does not skip an intermediate step."""
    if not spc:
        return [max(D.nodes, key=lambda v: (D.degree(v), v))] if D.number_of_nodes() else []
    (u, v), _ = max(spc.items(), key=lambda kv: (kv[1], kv[0]))
    path = [u, v]
    x = v
    while D.out_degree(x):
        x = max(D.successors(x), key=lambda y: (spc[(x, y)], -(year(y) or 9999), y))
        path.append(x)
    x = u
    while D.in_degree(x):
        x = max(D.predecessors(x), key=lambda y: (spc[(y, x)], year(y) or 0, y))
        path.insert(0, x)
    return path


def fetch_refs(d: Path, meta: dict, need: list, cache: Path):
    """Fetch reference metadata into meta, with progress, time-based atomic saves and a missing-ID list."""
    n_req = math.ceil(len(need) / 50)
    print(f"fetching metadata for {len(need)} references: {n_req} requests, roughly "
          f"{max(1, round(n_req * SEC_PER_REQUEST / 60))} min", file=sys.stderr, flush=True)
    t0 = last_save = time.monotonic()
    step = max(1, n_req // 10)

    def merge(got, final=False):
        nonlocal last_save
        for k, w in got.items():
            a = w.get("authorships") or []
            meta[k] = {x: w.get(x) for x in ("id", "doi", "title", "publication_year", "cited_by_count")}
            # keep only the first author to keep the cache small
            meta[k]["authorships"] = a[:1]
            meta[k]["referenced_works"] = w.get("referenced_works", [])
        if final or time.monotonic() - last_save >= SAVE_EVERY:
            save_json(cache, meta)
            last_save = time.monotonic()

    def progress(done, total):
        i = math.ceil(done / 50)
        if i % step == 0 or done == total:
            el = time.monotonic() - t0
            left = el / done * (total - done)
            print(f"  {done}/{total} references, {el / 60:.1f} min elapsed, ~{left / 60:.1f} min left",
                  file=sys.stderr, flush=True)

    merge(fetch_many(need, fields=REF_FIELDS, on_chunk=merge, progress=progress), final=True)
    # IDs OpenAlex no longer returns (merged/deleted works): remember them so later runs do not ask again
    lost = sorted(set(need) - meta.keys())
    if lost:
        mp = d / "refs_missing.json"
        old = set(json.loads(mp.read_text(encoding="utf-8"))) if mp.exists() else set()
        mp.write_text(json.dumps(sorted(old | set(lost))), encoding="utf-8")
        print(f"  {len(lost)} reference IDs not found in OpenAlex (listed in {mp.name}; not requested again)",
              file=sys.stderr, flush=True)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    full = "--print" in argv
    pos = [a for a in argv if not a.startswith("--")]
    d = Path(pos[0])
    corpus = json.loads((d / "corpus.json").read_text(encoding="utf-8"))
    # a preprint and its journal version would count twice (inflating recent years) and split citations
    alias = version_aliases(corpus)
    if alias:
        corpus = merge_versions(corpus, alias)
    seeds = [k for k, w in corpus.items() if "seed" in w["_role"]]
    # field = citing papers plus anything added by keyword / ancestor expansion
    fwd = [k for k, w in corpus.items()
           if any(r == "forward" or r.startswith("keyword:") or r == "ancestor-forward" for r in w["_role"])]

    # ---- 1. field references -------------------------------------------
    cache = d / "refs_meta.json"
    refs_of = {k: [short(r) for r in corpus[k]["referenced_works"]] for k in corpus}
    field_refs = Counter()
    for k in seeds + fwd:
        field_refs.update(set(refs_of[k]))
    min_ref_auto = len(pos) < 2
    min_ref = auto_min_ref(field_refs) if min_ref_auto else int(pos[1])
    if min_ref_auto and min_ref > 1:
        print(f"MIN_REF {min_ref} (automatic): {sum(1 for n in field_refs.values() if n >= min_ref)} of "
              f"{len(field_refs)} references are cited by >= {min_ref} field papers; pass MIN_REF 1 to fetch all",
              file=sys.stderr, flush=True)
    meta = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {}
    mp = d / "refs_missing.json"
    missing = set(json.loads(mp.read_text(encoding="utf-8"))) if mp.exists() else set()
    need = [r for r in field_refs if r not in meta and r not in corpus and r not in missing
            and field_refs[r] >= min_ref]
    if need:
        fetch_refs(d, meta, need, cache)
    allw = {**meta, **corpus}
    # OpenAlex returns publication_year: null for some records (often arXiv-like ones).
    # Year-based statistics skip them; how many were skipped is reported.
    no_year = sorted(k for k, w in corpus.items() if not w.get("publication_year"))
    in_field = set(seeds) | set(fwd)

    # ---- 2. RPYS ---------------------------------------------------------
    # n_refs by cited year, weighted by how often each ref is cited in the field; works outside the field only
    yr = Counter()
    refs_no_year = 0
    for r, n in field_refs.items():
        if r in in_field or n < min_ref:
            continue
        y = (allw.get(r) or {}).get("publication_year")
        if y:
            yr[y] += n
        elif r in allw:  # metadata known but undated
            refs_no_year += 1
    years = range(min(yr), max(yr) + 1) if yr else range(0)
    rpys = []
    for y in years:
        win = [yr.get(t, 0) for t in range(y - 2, y + 3)]
        rpys.append((y, yr.get(y, 0), yr.get(y, 0) - statistics.median(win)))
    rpys_until = date.today().year - 2  # the last two years are still filling up
    peaks = sorted([p for p in rpys if p[0] <= rpys_until], key=lambda p: -p[2])[:12]

    def top_in_year(y, n=3):
        c = [(field_refs[r], r) for r in field_refs
             if r not in in_field and (allw.get(r) or {}).get("publication_year") == y]
        return sorted(c, reverse=True)[:n]

    # ---- 3. core ancestors ----------------------------------------------
    core = [(r, n) for r, n in field_refs.most_common(60 + len(seeds)) if r not in seeds][:60]

    # ---- 4. bibliographic coupling clusters -----------------------------
    G = nx.Graph()
    fset = {k: set(refs_of[k]) for k in fwd}
    G.add_nodes_from(fwd)
    for i, a in enumerate(fwd):
        for b in fwd[i + 1:]:
            s = len(fset[a] & fset[b])
            if s >= 3:
                # Salton cosine normalisation
                w = s / ((len(fset[a]) * len(fset[b])) ** 0.5 or 1)
                G.add_edge(a, b, weight=w)
    comms = nx.community.louvain_communities(G, weight="weight", seed=7, resolution=1.0)
    comms = sorted(comms, key=len, reverse=True)
    titles = {k: title_words(corpus[k].get("title")) for k in fwd}
    df_all = Counter()
    for k in fwd:
        df_all.update(titles[k])
    clusters = []
    for ci, c in enumerate(comms):
        if len(c) < 3:
            continue
        # references distinctive to this cluster
        cref = Counter()
        for k in c:
            cref.update(fset[k])
        members = sorted(c, key=lambda k: -(corpus[k]["cited_by_count"] or 0))
        yrs = [corpus[k]["publication_year"] for k in c if corpus[k].get("publication_year")]
        clusters.append({
            "cluster": ci, "size": len(c),
            "years": f"{min(yrs)}-{max(yrs)}" if yrs else "n.d.",
            "median_year": statistics.median(yrs) if yrs else None,
            "no_year": len(c) - len(yrs),
            "words": cluster_words(c, df_all, len(fwd), titles),
            "top_members": [(label(corpus[k]), corpus[k]["cited_by_count"], (corpus[k]["title"] or "")[:110], k)
                            for k in members[:8]],
            "top_refs": [(label(allw[r]) if r in allw else r, n, ((allw.get(r) or {}).get("title") or "")[:90])
                         for r, n in cref.most_common(8) if r not in seeds],
        })

    # ---- 5. main path (SPC) ---------------------------------------------
    main_path, top_edges = spc_main_path(in_field, allw, alias)

    def desc(k):
        w = allw.get(k) or {}
        return f"{label(w)} | {w.get('cited_by_count')} cit | {(w.get('title') or '')[:100]} | {k}"

    res = {
        "min_ref": min_ref, "min_ref_auto": min_ref_auto,
        "n_field": len(seeds) + len(fwd), "n_field_refs": len(field_refs),
        "merged_versions": sorted([dup, keep] for dup, keep in alias.items()),
        "rpys_peaks": [(y, n, dev, [desc(r) for _, r in top_in_year(y)]) for y, n, dev in peaks],
        "rpys_scope": f"references outside the field (seeds and forward papers excluded), cited >= {min_ref} "
                      f"times; peaks up to {rpys_until}",
        "core_ancestors": [(n, desc(r)) for r, n in core],
        "clusters": clusters,
        "main_path": [desc(k) for k in main_path],
        "main_path_method": MAIN_PATH_METHOD,
        "top_spc_edges": [(s, desc(u), desc(v)) for (u, v), s in top_edges],
        "rpys_series": rpys,
        "forward_by_year": Counter(corpus[k]["publication_year"] for k in fwd if corpus[k].get("publication_year")),
        "missing_year": {"corpus": no_year, "forward": sum(1 for k in fwd if k in set(no_year)),
                         "field_refs": refs_no_year},
    }
    (d / "analysis.json").write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")

    text = report_text(res)
    # The report is always saved: a piped or truncated console must not force a rerun.
    (d / "analysis.txt").write_text(text, encoding="utf-8")
    print(text if full else summary_text(res), end="")
    print(f"\nwrote {d / 'analysis.txt'} and {d / 'analysis.json'}")


MAIN_PATH_METHOD = ("key-route within the field (seeds + forward papers): highest-SPC edge, extended greedily "
                    "both ways; earlier history is in RPYS and core ancestors")


def spc_main_path(nodes: set, allw: dict, alias: dict | None = None):
    """(key-route main path, top-15 SPC edges) on the citation DAG among `nodes`."""
    alias = alias or {}
    D = nx.DiGraph()  # edge: cited -> citing (knowledge flow)
    D.add_nodes_from(nodes)
    for k in nodes:
        for r in (allw.get(k) or {}).get("referenced_works", []) or []:
            r = alias.get(short(r), short(r))
            if r in nodes and r != k:
                D.add_edge(r, k)
    # citation cycles (preprint/version artefacts): drop edges that go backward in time,
    # then break any remaining cycle one edge at a time. Undated nodes keep their edges
    # (treating null as year 0 would cut every citation into them).
    year = lambda k: (allw.get(k) or {}).get("publication_year")
    D.remove_edges_from([(u, v) for u, v in D.edges if year(u) and year(v) and year(u) > year(v)])
    while not nx.is_directed_acyclic_graph(D):
        cyc = nx.find_cycle(D)
        D.remove_edge(*cyc[0])
    order = list(nx.topological_sort(D))
    n_minus = {v: 1 if D.in_degree(v) == 0 else 0 for v in D}
    for v in order:
        for u in D.predecessors(v):
            n_minus[v] += n_minus[u]
    n_plus = {v: 1 if D.out_degree(v) == 0 else 0 for v in D}
    for v in reversed(order):
        for u in D.successors(v):
            n_plus[v] += n_plus[u]
    spc = {(u, v): n_minus[u] * n_plus[v] for u, v in D.edges}
    # also top-SPC edges (key-route seeds)
    return key_route(D, spc, year), sorted(spc.items(), key=lambda kv: -kv[1])[:15]


def summary_text(res):
    cl = res["clusters"]
    out = [f"field: {res['n_field']} papers, {res['n_field_refs']} distinct references "
           f"(MIN_REF {res['min_ref']}{' auto' if res['min_ref_auto'] else ''})",
           "RPYS peaks: " + ", ".join(str(p[0]) for p in res["rpys_peaks"][:6]),
           f"clusters: {len(cl)} (" + "; ".join(f"C{c['cluster']} {c['size']}: {', '.join(c['words'][:3])}"
                                                for c in cl[:6]) + ")",
           f"main path: {len(res['main_path'])} works (key-route)"]
    if res.get("merged_versions"):
        out.append(f"merged {len(res['merged_versions'])} duplicate version(s) of the same paper "
                   "(preprint/repository copy folded into the journal record)")
    miss = res.get("missing_year") or {}
    if miss.get("corpus") or miss.get("field_refs"):
        out.append(f"skipped without publication year: {len(miss.get('corpus') or [])} corpus record(s), "
                   f"{miss.get('field_refs', 0)} reference(s)")
    return "\n".join(out) + "\n"


def report_text(res):
    out = [f"MIN_REF {res.get('min_ref', 1)}{' (automatic)' if res.get('min_ref_auto') else ''}; "
           f"RPYS: {res.get('rpys_scope', '')}", "",
           "== RPYS peaks (year, n_refs, deviation, top refs) =="]
    for y, n, dev, tops in res["rpys_peaks"]:
        out.append(f"{y} {n} {dev}")
        out += [f"     {t}" for t in tops]
    out += ["", "== Core ancestors (times cited by field) ==", "(seeds left out)"]
    out += [f"{n:4d}  {s}" for n, s in res["core_ancestors"]]
    out += ["", "== Clusters ==", "(words: frequent in the cluster, not across the field)"]
    for c in res["clusters"]:
        undated = f" (+{c['no_year']} undated)" if c.get("no_year") else ""
        out += ["", f"[C{c['cluster']}] size={c['size']} years={c['years']}{undated} median={c['median_year']}",
                "  words: " + ", ".join(c["words"])]
        out += [f"   * {m}" for m in c["top_members"]]
        out.append("  refs:")
        out += [f"   - {r}" for r in c["top_refs"]]
    out += ["", "== Main path ==", f"({res.get('main_path_method', 'SPC')})"]
    out += [f"  -> {s}" for s in res["main_path"]]
    out += ["", f"== forward by year == {dict(sorted(res['forward_by_year'].items()))}"]
    miss = res.get("missing_year") or {}
    if miss.get("corpus") or miss.get("field_refs"):
        ids = miss.get("corpus") or []
        out.append(f"   skipped in year-based statistics: {len(ids)} corpus record(s) without publication year"
                   f" ({miss.get('forward', 0)} forward){': ' + ', '.join(ids[:10]) if ids else ''}"
                   f"{' ...' if len(ids) > 10 else ''}; {miss.get('field_refs', 0)} undated reference(s) left out of RPYS")
    return "\n".join(out) + "\n"
