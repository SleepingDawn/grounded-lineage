"""Merge a topic folder's reports into one Markdown source, so the folder is delivered as one HTML page.

Default parts, in order, when present: `README.md` (review, with any lineage chapter),
`ideas/README.md` (topic recommendations), `ideas/novelty-*.md` (single-idea novelty
reports), `ideas/calc-*.md` (calculation plans). With
several parts the output is `# <title>`, a metadata line, an optional overall summary file,
then one `## <part title>` section per part with the part's own headings moved down one level,
and a single `<!-- references -->` list at the end (the citation keys of every part resolve
against the same `evidence/`). Relative links and images are rebased to the topic folder;
code blocks are left alone. A single part is copied unchanged. The output, `<Topic>.md` by
default, is generated: edit the parts and run this again.
"""
from __future__ import annotations

import datetime as _dt
import os
import re
from pathlib import Path
from typing import Any, Iterable, Sequence

DEFAULT_PARTS = ("README.md", "ideas/README.md", "ideas/novelty-*.md", "ideas/calc-*.md")
REFERENCES = "<!-- references -->"
FENCE = re.compile(r"^\s*(```|~~~)")
HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
LINK = re.compile(r"(!?\[[^\]]*\]\()([^)\s]+)(\))")
EXTERNAL = ("http://", "https://", "mailto:", "data:", "#", "/")


def default_parts(topic: Path) -> list[Path]:
    found: list[Path] = []
    for pattern in DEFAULT_PARTS:
        for p in sorted(topic.glob(pattern)):
            if p.is_file() and p not in found:
                found.append(p)
    return found


def _rebase(target: str, part_dir: Path, topic: Path) -> str:
    if target.startswith(EXTERNAL) or re.match(r"^[A-Za-z]:[\\/]", target):
        return target
    path, sep, anchor = target.partition("#")
    if not path:
        return target
    new = os.path.relpath(os.path.normpath(part_dir / path), topic).replace("\\", "/")
    return new + (sep + anchor if sep else "")


def _rebase_links(line: str, part_dir: Path, topic: Path) -> str:
    return LINK.sub(lambda m: m.group(1) + _rebase(m.group(2), part_dir, topic) + m.group(3), line)


def _split(text: str) -> dict[str, Any]:
    """Title, metadata line, body lines (references placeholder and its empty heading removed)."""
    lines = text.splitlines()
    title, meta, body, ref_heading = None, None, [], None
    in_fence, i = False, 0
    while i < len(lines):
        line = lines[i]
        if FENCE.match(line):
            in_fence = not in_fence
            body.append(line)
        elif in_fence:
            body.append(line)
        elif title is None and line.startswith("# "):
            title = line[2:].strip()
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines) and not lines[j].lstrip().startswith(("#", "|", "-", "*", "!", ">", "<")):
                meta = lines[j].strip()
                i = j
        elif line.strip() == REFERENCES:
            k = len(body) - 1
            while k >= 0 and not body[k].strip():
                k -= 1
            if k >= 0 and HEADING.match(body[k]):
                ref_heading = HEADING.match(body[k]).group(2)
                del body[k:]
        else:
            body.append(line)
        i += 1
    while body and not body[0].strip():
        body.pop(0)
    while body and not body[-1].strip():
        body.pop()
    return {"title": title, "meta": meta, "body": body, "ref_heading": ref_heading}


def _shifted(body: Iterable[str], part_dir: Path, topic: Path) -> list[str]:
    out, in_fence = [], False
    for line in body:
        if FENCE.match(line):
            in_fence = not in_fence
        elif not in_fence:
            m = HEADING.match(line)
            if m:
                line = "#" * min(len(m.group(1)) + 1, 6) + " " + m.group(2)
            line = _rebase_links(line, part_dir, topic)
        out.append(line)
    return out


def _lint(paths: Sequence[Path], names: Sequence[str]) -> list[dict[str, Any]]:
    """Markdown findings per source file (the parts to fix, not the generated page)."""
    from scholarly_access_agent.mdlint import lint_markdown

    return [{"file": name, **f} for p, name in zip(paths, names)
            for f in lint_markdown(p.read_text(encoding="utf-8"))]


def combine_reports(topic: str | Path, parts: Sequence[str | Path] | None = None, title: str | None = None,
                    summary: str | Path | None = None, output: str | Path | None = None) -> dict[str, Any]:
    topic = Path(topic).expanduser().resolve()
    if not topic.is_dir():
        raise NotADirectoryError(str(topic))
    if parts:
        paths = [(topic / p) if not Path(p).is_absolute() else Path(p) for p in parts]
        for p in paths:
            if not p.is_file():
                raise FileNotFoundError(str(p))
    else:
        paths = default_parts(topic)
        if not paths:
            raise FileNotFoundError(f"no report Markdown in {topic} (looked for {', '.join(DEFAULT_PARTS)})")
    out = Path(output).expanduser().resolve() if output else topic / f"{topic.name}.md"
    if out in [p.resolve() for p in paths]:
        raise ValueError(f"output {out} would overwrite one of its parts")
    rel = [p.resolve().relative_to(topic).as_posix() if p.resolve().is_relative_to(topic) else str(p) for p in paths]
    sources, names = list(paths), list(rel)
    if summary is not None:
        s = Path(summary).expanduser().resolve()
        sources.append(s)
        names.append(s.relative_to(topic).as_posix() if s.is_relative_to(topic) else str(s))
    lint = _lint(sources, names)

    if len(paths) == 1 and summary is None and title is None:
        text = paths[0].read_text(encoding="utf-8")
        if paths[0].parent.resolve() != out.parent:
            text = "\n".join(_rebase_links(l, paths[0].parent.resolve(), out.parent) for l in text.splitlines()) + "\n"
        out.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
        return {"ok": True, "output": str(out), "parts": rel, "mode": "single", "lint": lint}

    split = [_split(p.read_text(encoding="utf-8")) for p in paths]
    doc_title = title or split[0]["title"] or topic.name
    meta = f"{_dt.date.today().isoformat()} · " + " · ".join(s["title"] or r for s, r in zip(split, rel))
    doc = [f"# {doc_title}", "", meta, ""]
    if summary is not None:
        s_path = Path(summary).expanduser().resolve()
        s_lines = [_rebase_links(l, s_path.parent, topic) for l in s_path.read_text(encoding="utf-8").splitlines()]
        doc += s_lines + [""]
    for p, s, r in zip(paths, split, rel):
        doc += [f"## {s['title'] or r}", ""]
        if s["meta"]:
            doc += [f"*{_rebase_links(s['meta'], p.parent.resolve(), topic)}*", ""]
        doc += _shifted(s["body"], p.parent.resolve(), topic) + [""]
    ref_heading = next((s["ref_heading"] for s in split if s["ref_heading"]), "References")
    doc += [f"## {ref_heading}", "", REFERENCES, ""]
    out.write_text("\n".join(doc), encoding="utf-8")
    return {"ok": True, "output": str(out), "parts": rel, "mode": "combined", "lint": lint}
