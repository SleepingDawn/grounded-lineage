"""Log a search run outside OpenAlex (web, arXiv, KCI, Google Scholar, ...) so "not found" claims have a record.

Each call appends one entry to DATA_DIR/searches.json (created on first use); `lineage report-section`
lists them in the method section and the page shows them under the search log.

Usage:
  lineage log-search DIR --engine arXiv --query 'base editing off-target whole-genome sequencing in vivo' \
      --date 2026-11-20 --hits 14 --kept 'arXiv:2501.01234,W4400201232' [--note 'none measures off-target edits in vivo']
DIR is the topic folder (the log goes to its data dir: meta.data_dir of lineage.json, default data/) or a data
folder itself. --kept lists what was kept (OpenAlex IDs, DOIs, arXiv IDs); empty means nothing relevant was found.

Also holds the shared readers for the query log (saturation) used by check, page and report-section.
"""
from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path

SATURATION = 0.10  # novelty below this marks a query SATURATED (query-test)


def data_dir_of(path: Path) -> Path:
    """The data folder for DIR: a topic folder (lineage.json -> meta.data_dir, else data/) or a data folder."""
    path = Path(path)
    lj = path / "lineage.json"
    if lj.exists():
        try:
            meta = json.loads(lj.read_text(encoding="utf-8")).get("meta") or {}
        except (ValueError, OSError):
            meta = {}
        return path / (meta.get("data_dir") or "data")
    if (path / "corpus.json").exists() or (path / "queries.json").exists() or path.name.startswith("data"):
        return path
    return path / "data"


def load_json(p: Path, default):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def searches(data: Path) -> list:
    return load_json(Path(data) / "searches.json", [])


def saturation(data: Path) -> dict | None:
    """Saturation state of the logged OpenAlex queries, or None without a query log.

    {"n": number of queries, "saturated": [labels], "last_novelty": novelty of the last query (0-1),
     "last_label": its label}"""
    log = load_json(Path(data) / "queries.json", [])
    if not log:
        return None
    sat = [e.get("label") or e.get("query", "")[:40] for e in log if e.get("saturated")]
    last = log[-1]
    return {"n": len(log), "saturated": sat, "last_novelty": last.get("novelty"),
            "last_label": last.get("label") or last.get("query", "")[:40]}


def unsaturated_line(state: dict) -> str:
    nov = state.get("last_novelty")
    tail = f" (last query novelty {nov:.0%})" if isinstance(nov, (int, float)) else ""
    return f"UNSATURATED: no query reached novelty < {SATURATION:.0%}{tail}"


def unsaturated_ko(state: dict) -> str:
    nov = state.get("last_novelty")
    pct = f"{nov:.0%}" if isinstance(nov, (int, float)) else "?"
    return (f"검색은 포화에 이르지 않았다 (마지막 질의 신규 비율 {pct}; 기록된 질의 {state['n']}개 중 "
            f"신규 비율 {SATURATION:.0%} 미만인 질의 없음).")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="lineage log-search")
    ap.add_argument("dir", help="topic folder (log goes to its data dir) or the data folder itself")
    ap.add_argument("--engine", required=True, help="e.g. arXiv, Google Scholar, KCI, web")
    ap.add_argument("--query", required=True)
    ap.add_argument("--date", required=True, help="YYYY-MM-DD the search was run")
    ap.add_argument("--hits", required=True, type=int, help="number of results the engine reported or you screened")
    ap.add_argument("--kept", default="", help="comma-separated IDs kept (empty = nothing relevant)")
    ap.add_argument("--note", default="")
    a = ap.parse_args(argv)
    try:
        datetime.date.fromisoformat(a.date)
    except ValueError:
        raise ValueError(f"--date {a.date!r} must be YYYY-MM-DD")
    if a.hits < 0:
        raise ValueError("--hits must be >= 0")
    data = data_dir_of(Path(a.dir))
    data.mkdir(parents=True, exist_ok=True)
    p = data / "searches.json"
    log = load_json(p, [])
    entry = {"id": f"search#{len(log) + 1}", "engine": a.engine, "query": a.query, "date": a.date,
             "hits": a.hits, "kept": [k.strip() for k in a.kept.split(",") if k.strip()],
             "logged": datetime.date.today().isoformat()}
    if a.note:
        entry["note"] = a.note
    log.append(entry)
    p.write_text(json.dumps(log, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{entry['id']}: {a.engine} '{a.query}' ({a.date}) hits={a.hits} kept={len(entry['kept'])} -> {p}")
    return 0
