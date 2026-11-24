"""Markdown checks for report sources: blocks that Pandoc (what Quarto renders) prints as plain text.

Pandoc's Markdown needs a blank line before a table, a list, a heading or a block quote that
follows a paragraph line; without it the block becomes more paragraph text, and a table shows
as `| a | b | |—|—|`. A table or heading right after a list item, and a table, list or heading
right after a block-quote line, are swallowed the same way. (GitHub's Markdown accepts all of
these, so a report can look right in an editor preview and still render broken.) Pipe-table
rows with more cells than the header lose the extra cells silently.

lint_markdown(text) lists the findings; fix_markdown(text) inserts the missing blank lines.
Cell counts are left to the author. Fenced code is never checked.
"""
from __future__ import annotations

import re
from typing import Any

FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
HEADING = re.compile(r"^#{1,6}\s+\S")
QUOTE = re.compile(r"^ {0,3}>")
LIST = re.compile(r"^ {0,3}(?:[-*+]|\d{1,3}[.)])\s+\S")
RULE_LINE = re.compile(r"^ {0,3}([-*_])(?:\s*\1){2,}\s*$")
SEPARATOR = re.compile(r"^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$")
DIV = re.compile(r"^\s*:::")
HTML = re.compile(r"^\s*<")

# Block (of the line above) -> blocks it swallows when no blank line separates them.
SWALLOWS = {"para": {"table", "list", "heading", "quote"},
            "quote": {"table", "list", "heading"},
            "list": {"table", "heading"}}
ABOVE = {"para": "paragraph", "quote": "block quote", "list": "list item"}
# A heading or a horizontal rule is one line: whatever follows starts a new block.
ONE_LINE = {"heading", "rule"}


def cell_count(line: str) -> int:
    """Cells in a pipe-table row; `\\|` and pipes inside code spans do not split cells."""
    s = line.strip()
    pipes: list[int] = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "`":
            n = len(s[i:]) - len(s[i:].lstrip("`"))
            close = re.compile(r"(?<!`)" + "`" * n + r"(?!`)")
            m = close.search(s, i + n)
            i = m.end() if m else i + n
            continue
        if ch == "|":
            pipes.append(i)
        i += 1
    count = len(pipes) + 1
    if pipes and pipes[0] == 0:
        count -= 1
    if pipes and pipes[-1] == len(s) - 1 and len(s) > 1:
        count -= 1
    return count


def _is_table_start(lines: list[str], i: int) -> bool:
    nxt = lines[i + 1] if i + 1 < len(lines) else ""
    return ("|" in lines[i] and "|" in nxt and SEPARATOR.match(nxt) is not None
            and SEPARATOR.match(lines[i]) is None)


def _kind(lines: list[str], i: int) -> str:
    line = lines[i]
    if DIV.match(line):
        return "div"
    if HEADING.match(line):
        return "heading"
    if RULE_LINE.match(line):
        return "rule"
    if _is_table_start(lines, i):
        return "table"
    if QUOTE.match(line):
        return "quote"
    if LIST.match(line):
        return "list"
    if HTML.match(line):
        return "html"
    if line.startswith(("    ", "\t")):
        return "indented"
    return "text"


def _short(text: str, limit: int = 90) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _finding(line_no: int, rule: str, message: str, text: str, fixable: bool) -> dict[str, Any]:
    return {"level": "error", "line": line_no, "rule": rule, "message": message,
            "sentence": _short(text), "fixable": fixable}


def _scan(lines: list[str]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    block: str | None = None
    fence: str | None = None
    header = 0
    separator = -1
    for i, line in enumerate(lines):
        if fence:
            m = FENCE.match(line)
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and not line.strip()[len(m.group(1)):].strip():
                fence, block = None, None
            continue
        m = FENCE.match(line)
        if m:
            fence, block = m.group(1), None
            continue
        if not line.strip():
            block = None
            continue
        if i == separator:
            continue
        if block == "table":
            if "|" in line and cell_count(line) > header:
                findings.append(_finding(i + 1, "table_column_mismatch",
                                         f"row has {cell_count(line)} cells, the header {header}: "
                                         "Pandoc drops the extra cells", line, False))
            continue
        kind = _kind(lines, i)
        if kind in SWALLOWS.get(block or "", ()):
            findings.append(_finding(i + 1, f"blank_line_before_{kind}",
                                     f"no blank line before this {kind}: Pandoc reads it as part of the "
                                     f"{ABOVE[block]} above and prints it as text", line, True))
            block = None
        if block is not None and block not in ONE_LINE:
            continue  # continuation of the block above (lazy lines, further list items)
        if kind == "table":
            header, separator = cell_count(line), i + 1
            if cell_count(lines[i + 1]) != header:
                findings.append(_finding(i + 2, "table_column_mismatch",
                                         f"separator row has {cell_count(lines[i + 1])} cells, the header "
                                         f"{header}", lines[i + 1], False))
            block = "table"
        elif kind == "div":
            block = None
        else:
            block = {"text": "para", "indented": "code"}.get(kind, kind)
    return findings


def lint_markdown(text: str) -> list[dict[str, Any]]:
    """Findings (level, line, rule, message, sentence, fixable), in line order."""
    return _scan(text.split("\n"))


def fix_markdown(text: str) -> tuple[str, list[dict[str, Any]]]:
    """(text with a blank line inserted before every swallowed block, the findings of the original)."""
    lines = text.split("\n")
    findings = _scan(lines)
    for f in sorted((f for f in findings if f["fixable"]), key=lambda f: f["line"], reverse=True):
        lines.insert(f["line"] - 1, "")
    return "\n".join(lines), findings
