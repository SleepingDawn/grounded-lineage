"""Render a finished Markdown research report with Quarto: an A4 PDF (Typst) and a standalone HTML.

Theme (data/quarto): one Korean sans family at 10.5 pt and ~1.6 line height with >= 4.5:1
contrast (KRDS-style), a ~40-character Korean measure and quiet tables (Tufte-style).
The report's own `# title` and metadata line become a title block; pipe-table column widths
follow their content so short columns (years, labels) never wrap mid-token.

Local files only: remote images are dropped before rendering, code is never executed
(`engine: markdown`), math is not fetched from a CDN, and the HTML embeds its resources.
"""
from __future__ import annotations

import html
import os
import re
import shutil
import subprocess
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

THEME_DIR = Path(__file__).resolve().parent.parent / "data" / "quarto"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif"}
# Typst family names, most readable first (Pretendard is what KRDS recommends).
FONT_FAMILIES = ["Pretendard", "NanumBarunGothic", "NanumGothic", "Noto Sans KR", "Malgun Gothic",
                 "Apple SD Gothic Neo", "AppleGothic", "Noto Sans CJK KR"]
TABLE_UNITS = 88  # table text width in Latin character widths at the table font size
QUARTO_CANDIDATES = [
    Path("C:/Program Files/Quarto/bin/quarto.exe"),
    Path.home() / "AppData/Local/Programs/Quarto/bin/quarto.exe",
    Path("/Applications/quarto/bin/quarto"),
    Path("/opt/quarto/bin/quarto"),
]


# --------------------------------------------------------------------------- discovery

def find_quarto() -> str | None:
    """QUARTO_PATH, then PATH, then the default install locations."""
    env = os.environ.get("QUARTO_PATH")
    if env and Path(env).is_file():
        return env
    found = shutil.which("quarto")
    if found:
        return found
    return next((str(p) for p in QUARTO_CANDIDATES if p.is_file()), None)


@lru_cache(maxsize=4)
def typst_fonts(quarto: str) -> tuple[str, ...]:
    try:
        run = subprocess.run([quarto, "typst", "fonts"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=120)
    except (OSError, subprocess.SubprocessError):
        return ()
    # Quarto 1.11 forwards Typst's font list on stderr; accept either stream.
    return tuple(line.strip() for line in (run.stdout + "\n" + run.stderr).splitlines() if line.strip())


def pick_font(quarto: str) -> str | None:
    available = {f.lower(): f for f in typst_fonts(quarto)}
    override = os.environ.get("SNU_REPORT_FONT_FAMILY")
    if override and override.lower() in available:
        return available[override.lower()]
    return next((available[f.lower()] for f in FONT_FAMILIES if f.lower() in available), None)


# --------------------------------------------------------------------------- markdown preparation

def split_front(text: str) -> tuple[str, str, list[str]]:
    """`# Title` and the metadata line under it, then the body lines."""
    lines = text.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    title = ""
    if lines and re.match(r"^#\s", lines[0]):
        title = lines.pop(0)[1:].strip()
    while lines and not lines[0].strip():
        lines.pop(0)
    subtitle = ""
    if title and lines and not lines[0].lstrip().startswith(("#", "|", "-", "*", ">", "!", "```")):
        subtitle = lines.pop(0).strip()
    while lines and not lines[0].strip():
        lines.pop(0)
    return title, subtitle, lines


def _width(cell: str) -> float:
    cell = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", cell).replace("**", "").replace("`", "")
    return sum(1.8 if unicodedata.east_asian_width(c) in "WF" else 1.0 for c in cell)


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


SEPARATOR = re.compile(r"^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$")


def size_tables(lines: list[str]) -> list[str]:
    """Rewrite each pipe table's separator so column widths follow their content.

    Every column gets at least its longest unbreakable token; the remaining width goes to
    columns in proportion to their average cell length. Pandoc turns dash counts into
    relative widths for both Typst and HTML.
    """
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if (line.lstrip().startswith("|") and i + 1 < len(lines) and SEPARATOR.match(lines[i + 1])
                and "-" in lines[i + 1]):
            j = i + 2
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                j += 1
            header, seps, body = _cells(line), _cells(lines[i + 1]), [_cells(r) for r in lines[i + 2:j]]
            mins, want = [], []
            for c in range(len(header)):
                column = [row[c] for row in body if c < len(row)] or [""]
                tokens = [_width(t) for cell in column + [header[c]] for t in cell.split()] or [0.0]
                mins.append(max(tokens) + 2)
                want.append(max(sum(_width(x) for x in column) / len(column), mins[-1]))
            if sum(want) <= TABLE_UNITS:
                widths = want
            else:
                spare = max(TABLE_UNITS - sum(mins), 0.0)
                extra = [w - m for w, m in zip(want, mins)]
                widths = [m + (spare * e / sum(extra) if sum(extra) else 0.0) for m, e in zip(mins, extra)]
            new = []
            for c, w in enumerate(widths):
                old = seps[c] if c < len(seps) else "---"
                dashes = "-" * max(3, round(120 * w / sum(widths)))
                new.append((":" if old.startswith(":") else "") + dashes + (":" if len(old) > 1 and old.endswith(":") else ""))
            out += [line, "|" + "|".join(new) + "|"] + lines[i + 2:j]
            i = j
        else:
            out.append(line)
            i += 1
    return out


IMAGE = re.compile(r"!\[([^\]]*)\]\(\s*<?([^)\s>]+)>?(?:\s+\"([^\"]*)\")?\s*\)")
INTERACTIVE = "interactive="


def _local(base_dir: Path, src: str) -> Path | None:
    if re.match(r"^[a-z]+:", src, re.I):
        return None
    path = (base_dir / src).resolve()
    return path if path.is_relative_to(base_dir) else None


def _inline_frame(page: Path, caption: str) -> str:
    """A self-contained interactive figure: the local HTML page inlined as an iframe srcdoc."""
    doc = html.escape(page.read_text(encoding="utf-8"), quote=True)
    cap = html.escape(caption, quote=True)
    # column-page: Quarto's layout class that lets a wide figure use the full page width.
    return ("\n```{=html}\n<figure class=\"snu-interactive column-page\">"
            f"<iframe srcdoc=\"{doc}\" title=\"{cap}\" loading=\"lazy\" "
            "sandbox=\"allow-scripts allow-popups allow-popups-to-escape-sandbox\"></iframe>"
            f"<figcaption>{html.escape(caption, quote=False)}</figcaption></figure>\n```\n")


def prepare_body(lines: list[str], base_dir: Path, interactive: bool = False) -> tuple[list[str], list[str]]:
    """Make the body safe and Pandoc-ready: local images only, <sub>/<sup>/<br> as Markdown.

    An image titled `"interactive=page.html"` (a local HTML page in the report folder) becomes
    that page inlined as an interactive frame when `interactive` (the HTML output); otherwise
    the static image is kept.
    """
    base_dir = base_dir.resolve()
    warnings: list[str] = []

    def image(match: re.Match) -> str:
        alt, src, title = match.group(1), match.group(2), match.group(3) or ""
        if re.match(r"^[a-z]+:", src, re.I):
            warnings.append(f"image_skipped_remote: {src}")
            return ""
        path = (base_dir / src).resolve()
        if not path.is_relative_to(base_dir):
            warnings.append(f"image_skipped_outside_report_folder: {src}")
            return ""
        if path.suffix.lower() not in IMAGE_SUFFIXES or not path.is_file():
            warnings.append(f"image_skipped_unsupported_or_missing (use PNG/JPG): {src}")
            return ""
        if not title.startswith(INTERACTIVE):
            return match.group(0)
        if interactive:
            target = title[len(INTERACTIVE):].strip()
            page = _local(base_dir, target)
            if page is None or page.suffix.lower() not in {".html", ".htm"} or not page.is_file():
                warnings.append(f"interactive_figure_skipped (local .html in the report folder): {target}")
            else:
                return _inline_frame(page, alt)
        return f"![{alt}]({src})"

    out: list[str] = []
    fenced = False
    for line in lines:
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        if fenced:
            out.append(line)
            continue
        line = IMAGE.sub(image, line)
        line = re.sub(r"<sub>(.*?)</sub>", lambda m: "~" + m.group(1).replace(" ", "\\ ") + "~", line)
        line = re.sub(r"<sup>(.*?)</sup>", lambda m: "^" + m.group(1).replace(" ", "\\ ") + "^", line)
        brk = re.compile(r"\s*<br\s*/?>\s*", re.I)
        line = brk.sub(" ", line) if line.lstrip().startswith("|") else brk.sub("\\\\\n", line)
        out.append(line)
    return out, warnings


def typst_string(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _yaml_string(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


# --------------------------------------------------------------------------- glyph check

def missing_glyphs(text: str, font: str | None) -> str:
    """Characters no installed TrueType font covers (Typst falls back across all fonts)."""
    from .report import _cmap, _font_index

    needed = {ch for ch in text if not ch.isspace() and ord(ch) > 0x7E}
    if not needed:
        return ""
    for path in _font_index().values():
        try:
            needed -= {ch for ch in needed if ord(ch) in _cmap(path)}
        except Exception:  # unreadable or PostScript-outline font
            continue
        if not needed:
            return ""
    return "".join(sorted(needed))


# --------------------------------------------------------------------------- render

def _run(quarto: str, qmd: Path, to: str) -> subprocess.CompletedProcess:
    return subprocess.run([quarto, "render", qmd.name, "--to", to], cwd=qmd.parent, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=600)


def _cleanup_only(stderr: str) -> bool:
    """True when Quarto's only failure is removing its own temporary folder after rendering."""
    return "renderCleanup" in stderr and "safeRemoveDirSync" in stderr


def _problems(stderr: str) -> list[str]:
    return [f"quarto: {line.strip()[:200]}" for line in stderr.splitlines()
            if re.search(r"\b(warning|error)\b", line, re.I) and "WARN: Unable to resolve" not in line]


def render_with_quarto(source: Path, base: Path, quarto: str, formats: tuple[str, ...],
                       text: str | None = None) -> dict[str, Any]:
    """Render Markdown `source` to `base`.html and/or `base`.pdf (resolved paths, any suffix on `base`).

    `text`, when given, replaces the file's content (citation keys already rendered); images
    still resolve against the source's folder.
    """
    from pypdf import PdfReader

    text = source.read_text(encoding="utf-8") if text is None else text
    title, subtitle, body = split_front(text)
    title = title or source.stem
    folder = source.parent
    html_body, warnings = prepare_body(body, folder, interactive=True)
    pdf_body, _ = prepare_body(body, folder, interactive=False)
    font = pick_font(quarto)
    if font is None:
        warnings.append("no_korean_font: install Pretendard, NanumBarunGothic or Noto Sans KR")

    stem = f"_{source.stem}.snu-render"
    quarto_dir_existed = (folder / ".quarto").exists()
    work = {name: folder / f"{stem}{name}" for name in (".pdf.qmd", ".html.qmd", ".before.typ")}
    produced = {"pdf": folder / f"{stem}.pdf.pdf", "html": folder / f"{stem}.html.html"}
    targets = {"pdf": base.with_suffix(".pdf"), "html": base.with_suffix(".html")}
    done: dict[str, Path] = {}
    try:
        if "pdf" in formats:
            theme = (THEME_DIR / "snu-report.typ").read_text(encoding="utf-8")
            work[".before.typ"].write_text(
                f"#let snu-report-title = {typst_string(title)}\n#set document(title: {typst_string(title)})\n"
                + theme
                + f"\n#block(below: 1.6em)[\n  #text(size: 19pt, weight: \"bold\")[#{typst_string(title)}]\n"
                + (f"  #v(0.15em)\n  #text(size: 8.6pt, fill: snu-muted)[#{typst_string(subtitle)}]\n" if subtitle else "")
                + "]\n", encoding="utf-8")
            yaml = ["---", "lang: ko", "engine: markdown", "format:", "  typst:", "    papersize: a4",
                    "    margin:", "      x: 26mm", "      top: 22mm", "      bottom: 24mm",
                    "    fontsize: 10.5pt", "    shift-heading-level-by: 0",
                    f"    include-before-body: {_yaml_string(work['.before.typ'].name)}"]
            if font:
                yaml.append(f"    mainfont: {_yaml_string(font)}")
            work[".pdf.qmd"].write_text("\n".join(yaml + ["---", ""] + size_tables(pdf_body)) + "\n", encoding="utf-8")
        if "html" in formats:
            css = (THEME_DIR / "snu-report.css").as_posix()
            yaml = ["---", f"title: {_yaml_string(title)}"] + ([f"subtitle: {_yaml_string(subtitle)}"] if subtitle else []) + [
                "lang: ko", "engine: markdown", "format:", "  html:", "    embed-resources: true", "    toc: true",
                "    toc-depth: 3", '    toc-title: "목차"', "    theme: default", "    html-math-method: plain",
                f"    css: {_yaml_string(css)}", "---", ""]
            work[".html.qmd"].write_text("\n".join(yaml + size_tables(html_body)) + "\n", encoding="utf-8")

        for fmt, qmd, to in (("html", ".html.qmd", "html"), ("pdf", ".pdf.qmd", "typst")):
            if fmt not in formats:
                continue
            run = _run(quarto, work[qmd], to)
            if run.returncode != 0 and produced[fmt].is_file() and _cleanup_only(run.stderr):
                # Quarto wrote the output but could not delete its temporary folder (Dropbox or
                # antivirus holding it on Windows); the finally block below removes it instead.
                warnings.append("quarto_cleanup_failed: temporary folder removed afterwards")
            elif run.returncode != 0 or not produced[fmt].is_file():
                return {"ok": False, "status": "render_failed", "engine": "quarto", "format": fmt,
                        "reason": "\n".join(run.stderr.strip().splitlines()[-8:])}
            os.replace(produced[fmt], targets[fmt])
            done[fmt] = targets[fmt]
            warnings += _problems(run.stderr)
    finally:
        for path in list(work.values()) + list(produced.values()) + [folder / f"{stem}.pdf.typ"]:
            path.unlink(missing_ok=True)
        for leftover in (folder / f"{stem}.pdf_files", folder / f"{stem}.html_files"):
            shutil.rmtree(leftover, ignore_errors=True)
        if not quarto_dir_existed:
            shutil.rmtree(folder / ".quarto", ignore_errors=True)

    primary = done.get("html") or done["pdf"]
    return {
        "ok": True,
        "engine": "quarto",
        "output_path": str(primary),
        "html_path": str(done["html"]) if "html" in done else None,
        "pdf_path": str(done["pdf"]) if "pdf" in done else None,
        "pages": len(PdfReader(str(done["pdf"])).pages) if "pdf" in done else None,
        "title": title,
        "font": font or "Typst default (no Korean font found)",
        "missing_glyphs": missing_glyphs(text, font),
        "warnings": warnings,
    }


