"""Lineage analysis on a corpus produced by `lineage collect`.

1. Field references: everything cited by the seed + forward papers (metadata fetched).
2. RPYS: reference-year spectrum and deviation from 5-year median -> origin peaks.
3. Core ancestors: references most often cited by the forward set.
4. Branches: bibliographic-coupling network of forward papers -> Louvain clusters.
5. Main path: SPC (search path count) weights on the citation DAG -> global main path.

Writes DATA_DIR/analysis.json and the readable report DATA_DIR/analysis.txt (also printed).

Usage: lineage analyze DATA_DIR [MIN_REF]
  MIN_REF (default 1): only fetch metadata for references cited by >= MIN_REF field papers.
  Use 2-3 for expanded corpora to save OpenAlex quota; RPYS then reflects shared references only.
"""
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

import networkx as nx

from .openalex import REF_FIELDS, fetch_many, short

STOP = set("""a an the of for and in on with by to from via at as is are using based
learning machine interatomic potentials potential neural network networks model models
long range long-range interactions molecular simulations simulation accurate towards
data efficient""".split())


def label(w):
    a = w.get("authorships") or []
    first = a[0]["author"]["display_name"].split()[-1] if a else "?"
    return f"{first} {w.get('publication_year') or 'n.d.'}"


def main(argv=None):
    argv = argv if argv is None else list(argv)
    d = Path(argv[0])
    min_ref = int(argv[1]) if len(argv) > 1 else 1
    corpus = json.loads((d / "corpus.json").read_text(encoding="utf-8"))
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
    if cache.exists():
        meta = json.loads(cache.read_text(encoding="utf-8"))
    else:
        meta = {}
    need = [r for r in field_refs if r not in meta and r not in corpus and field_refs[r] >= min_ref]
    if need:
        print(f"fetching metadata for {len(need)} references", flush=True)

        def merge(got):
            for k, w in got.items():
                a = w.get("authorships") or []
                meta[k] = {x: w.get(x) for x in ("id", "doi", "title", "publication_year", "cited_by_count")}
                # keep only the first author to keep the cache small
                meta[k]["authorships"] = a[:1]
                meta[k]["referenced_works"] = w.get("referenced_works", [])
            cache.write_text(json.dumps(meta), encoding="utf-8")

        merge(fetch_many(need, fields=REF_FIELDS, on_chunk=merge))
    allw = {**meta, **corpus}
    # OpenAlex returns publication_year: null for some records (often arXiv-like ones).
    # Year-based statistics skip them; how many were skipped is reported.
    no_year = sorted(k for k, w in corpus.items() if not w.get("publication_year"))

    # ---- 2. RPYS ---------------------------------------------------------
    # n_refs by cited year, weighted by how often each ref is cited in the field
    yr = Counter()
    refs_no_year = 0
    for r, n in field_refs.items():
        y = (allw.get(r) or {}).get("publication_year")
        if y:
            yr[y] += n
        elif r in allw:  # metadata known but undated (refs below MIN_REF are not fetched at all)
            refs_no_year += 1
    years = range(min(yr), max(yr) + 1) if yr else range(0)
    rpys = []
    for y in years:
        win = [yr.get(t, 0) for t in range(y - 2, y + 3)]
        rpys.append((y, yr.get(y, 0), yr.get(y, 0) - statistics.median(win)))
    peaks = sorted([p for p in rpys if p[0] < 2024], key=lambda p: -p[2])[:12]

    def top_in_year(y, n=3):
        c = [(field_refs[r], r) for r in field_refs
             if (allw.get(r) or {}).get("publication_year") == y]
        return sorted(c, reverse=True)[:n]

    # ---- 3. core ancestors ----------------------------------------------
    core = field_refs.most_common(60)

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
    clusters = []
    for ci, c in enumerate(comms):
        if len(c) < 3:
            continue
        words = Counter()
        for k in c:
            t = (corpus[k].get("title") or "").lower()
            words.update(x.strip(":,.()") for x in t.split() if x.strip(":,.()") not in STOP)
        # references distinctive to this cluster
        cref = Counter()
        for k in c:
            cref.update(fset[k])
        members = sorted(c, key=lambda k: -corpus[k]["cited_by_count"])
        yrs = [corpus[k]["publication_year"] for k in c if corpus[k].get("publication_year")]
        clusters.append({
            "cluster": ci, "size": len(c),
            "years": f"{min(yrs)}-{max(yrs)}" if yrs else "n.d.",
            "median_year": statistics.median(yrs) if yrs else None,
            "no_year": len(c) - len(yrs),
            "words": [w for w, _ in words.most_common(10)],
            "top_members": [(label(corpus[k]), corpus[k]["cited_by_count"], corpus[k]["title"][:110], k)
                            for k in members[:8]],
            "top_refs": [(label(allw[r]) if r in allw else r, n, (allw.get(r) or {}).get("title", "")[:90])
                         for r, n in cref.most_common(8) if r not in seeds],
        })

    # ---- 5. main path (SPC) ---------------------------------------------
    # nodes: seed, forward, and core ancestors cited >= 5 times by the field
    nodes = set(seeds) | set(fwd) | {r for r, n in field_refs.items() if n >= 5}
    D = nx.DiGraph()  # edge: cited -> citing (knowledge flow)
    D.add_nodes_from(nodes)
    for k in nodes:
        for r in (allw.get(k) or {}).get("referenced_works", []) or []:
            r = short(r)
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
    # global main path: max-total-SPC path from any source to any sink
    best = {v: (0, [v]) for v in D}
    for v in reversed(order):
        for u in D.successors(v):
            cand = spc[(v, u)] + best[u][0]
            if cand > best[v][0]:
                best[v] = (cand, [v] + best[u][1])
    start = max((v for v in D if D.in_degree(v) == 0), key=lambda v: best[v][0])
    main_path = best[start][1]
    # also top-SPC edges (key-route seeds)
    top_edges = sorted(spc.items(), key=lambda kv: -kv[1])[:15]

    def desc(k):
        w = allw.get(k) or {}
        return f"{label(w)} | {w.get('cited_by_count')} cit | {(w.get('title') or '')[:100]} | {k}"

    res = {
        "rpys_peaks": [(y, n, dev, [desc(r) for _, r in top_in_year(y)]) for y, n, dev in peaks],
        "core_ancestors": [(n, desc(r)) for r, n in core],
        "clusters": clusters,
        "main_path": [desc(k) for k in main_path],
        "top_spc_edges": [(s, desc(u), desc(v)) for (u, v), s in top_edges],
        "rpys_series": rpys,
        "forward_by_year": Counter(corpus[k]["publication_year"] for k in fwd if corpus[k].get("publication_year")),
        "missing_year": {"corpus": no_year, "forward": sum(1 for k in fwd if k in set(no_year)),
                         "field_refs": refs_no_year},
    }
    if no_year or refs_no_year:
        print(f"note: skipped {len(no_year)} corpus record(s) and {refs_no_year} reference(s) without "
              f"publication year in year-based statistics", file=sys.stderr)
    (d / "analysis.json").write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")

    text = report_text(res)
    # The report is always saved: a piped or truncated console must not force a rerun.
    (d / "analysis.txt").write_text(text, encoding="utf-8")
    print(text, end="")
    print(f"\nwrote {d / 'analysis.txt'} and {d / 'analysis.json'}")


def report_text(res):
    out = ["== RPYS peaks (year, n_refs, deviation, top refs) =="]
    for y, n, dev, tops in res["rpys_peaks"]:
        out.append(f"{y} {n} {dev}")
        out += [f"     {t}" for t in tops]
    out += ["", "== Core ancestors (times cited by field) =="]
    out += [f"{n:4d}  {s}" for n, s in res["core_ancestors"]]
    out += ["", "== Clusters =="]
    for c in res["clusters"]:
        undated = f" (+{c['no_year']} undated)" if c.get("no_year") else ""
        out += ["", f"[C{c['cluster']}] size={c['size']} years={c['years']}{undated} median={c['median_year']}",
                "  words: " + ", ".join(c["words"])]
        out += [f"   * {m}" for m in c["top_members"]]
        out.append("  refs:")
        out += [f"   - {r}" for r in c["top_refs"]]
    out += ["", "== Main path =="]
    out += [f"  -> {s}" for s in res["main_path"]]
    out += ["", f"== forward by year == {dict(sorted(res['forward_by_year'].items()))}"]
    miss = res.get("missing_year") or {}
    if miss.get("corpus") or miss.get("field_refs"):
        ids = miss.get("corpus") or []
        out.append(f"   skipped in year-based statistics: {len(ids)} corpus record(s) without publication year"
                   f" ({miss.get('forward', 0)} forward){': ' + ', '.join(ids[:10]) if ids else ''}"
                   f"{' ...' if len(ids) > 10 else ''}; {miss.get('field_refs', 0)} undated reference(s) left out of RPYS")
    return "\n".join(out) + "\n"

