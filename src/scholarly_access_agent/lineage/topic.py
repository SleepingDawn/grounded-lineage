"""Citation-anchored relevance: is a search hit part of the field, independent of its wording?

Core set = references that the field (seed + citing papers) cites at least MIN_COUNT times AND
that are field-specific: field citations / global citations >= MIN_SPEC. Generic tools
(PBE: 45 / 226,970) drop out; field works (4G-HDNNP: 87 / 654) stay.
A hit is "in field" when its reference list contains at least one core paper.
The core list is cached in DATA_DIR/core.json so the user can inspect it.
"""
import json
from collections import Counter
from pathlib import Path

from .openalex import short

MIN_COUNT, MIN_SPEC = 3, 0.02


def core_set(data_dir):
    d = Path(data_dir)
    cache = d / "core.json"
    if cache.exists():
        return set(json.loads(cache.read_text(encoding="utf-8"))["ids"])
    corpus = json.loads((d / "corpus.json").read_text(encoding="utf-8"))
    meta_p = d / "refs_meta.json"
    meta = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else {}
    field = [k for k, w in corpus.items() if {"seed", "forward"} & set(w.get("_role", []))]
    cnt = Counter()
    for k in field:
        cnt.update({short(r) for r in corpus[k].get("referenced_works") or []})
    allw = {**meta, **corpus}
    core = []
    for r, n in cnt.items():
        g = (allw.get(r) or {}).get("cited_by_count") or 0
        if n >= MIN_COUNT and g and n / g >= MIN_SPEC:
            core.append((n / g, r, (allw[r].get("title") or "")[:100]))
    core.sort(reverse=True)
    field_ids = set(field)  # citing a seed-citing paper also anchors a hit
    ids = sorted({r for _, r, _ in core} | field_ids)
    cache.write_text(json.dumps({"min_count": MIN_COUNT, "min_spec": MIN_SPEC, "n_refs": len(core),
                                 "ids": ids, "top": [[round(s, 3), r, t] for s, r, t in core[:60]]},
                                ensure_ascii=False, indent=1), encoding="utf-8")
    return set(ids)


def in_field(w, core):
    return any(short(r) in core for r in (w.get("referenced_works") or []))
