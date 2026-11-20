"""Research root and per-investigation folders.

One investigation = one folder under the research root, the same layout the
literature reports already use:

  <root>/<Topic>/README.md        report (Markdown) → <Topic>.pdf via render-report
  <root>/<Topic>/evidence/        per-paper evidence records (JSON)
  <root>/<Topic>/figs/            figures (figs/lineage.png from report-section)
  <root>/<Topic>/archive/         earlier report versions
  <root>/<Topic>/lineage.json     lineage curation (research-lineage only)
  <root>/<Topic>/data/, data_x/   OpenAlex corpus and analysis (research-lineage only)

The root is SNU_RESEARCH_ROOT (environment, or the saved Windows user variable);
without it, ~/Documents/research.

Usage: lineage init <Topic> [--root DIR]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path


def user_env(name: str) -> str | None:
    """Environment variable, falling back on Windows to the saved user variable
    (so a value saved after the client started is still seen)."""
    value = os.environ.get(name)
    if not value and sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as handle:
                value = winreg.QueryValueEx(handle, name)[0]
        except OSError:
            pass
    return value or None


def research_root() -> Path:
    value = user_env("SNU_RESEARCH_ROOT")
    return Path(os.path.expandvars(value)).expanduser() if value else Path.home() / "Documents" / "research"


SKELETON = {
    "meta": {"page_title": "", "slug": "lineage", "date": "", "headline": "", "lede": "",
             "seed_label": "", "seed_ids": [], "papers_read": [], "data_dir": "data"},
    "lanes": [], "nodes": [], "edges": [], "axes": [], "trends": [], "one_line": "",
    "verdict": [], "evidence": {}, "rows": [], "limits": [],
}


def init(topic: str, root: Path | None = None, lineage: bool = True) -> Path:
    if not topic or re.search(r'[\\/:*?"<>|]', topic) or topic in (".", ".."):
        raise ValueError(f"invalid topic folder name: {topic!r} (no path separators or reserved characters)")
    folder = (root or research_root()) / topic
    for sub in ("evidence", "figs", "archive") + (("data",) if lineage else ()):
        (folder / sub).mkdir(parents=True, exist_ok=True)
    skeleton = folder / "lineage.json"
    if lineage and not skeleton.exists():
        data = json.loads(json.dumps(SKELETON))
        data["meta"]["slug"] = re.sub(r"[^A-Za-z0-9_-]+", "-", topic).strip("-").lower() or "lineage"
        skeleton.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return folder


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="lineage init")
    ap.add_argument("topic", help="folder name, e.g. LES-lineage (same style as existing topic folders)")
    ap.add_argument("--root", help="override the research root (default: SNU_RESEARCH_ROOT)")
    ap.add_argument("--no-lineage", action="store_true", help="report folders only (no data/, lineage.json)")
    a = ap.parse_args(argv)
    folder = init(a.topic, Path(a.root) if a.root else None, lineage=not a.no_lineage)
    print(json.dumps({"ok": True, "folder": str(folder), "root": str(folder.parent)}, ensure_ascii=False))
    return 0
