"""Render a finished Markdown research report to a readable A4 PDF.

The rendering follows the reportlab Platypus approach of Anthropic's `pdf`
skill (anthropics/skills) - including its rule to typeset Unicode sub- and
superscripts as <sub>/<super> markup - and the one-palette, one-font-pairing,
contrast-first guidance of its `theme-factory` skill. No code or text from
either skill is vendored. Local files only; nothing is fetched from the network.
"""
from __future__ import annotations

import html
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from markdown_it import MarkdownIt
from markdown_it.token import Token
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (
    BaseDocTemplate,
    CondPageBreak,
    Flowable,
    Frame,
    HRFlowable,
    Image,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
    Table,
    TableStyle,
)

# Palette: one ink, one accent, neutral rules. Every text colour is >= 4.5:1 on white.
INK = colors.HexColor("#1d232b")
INK_STRONG = colors.HexColor("#0f1720")
MUTED = colors.HexColor("#5b6470")
ACCENT = colors.HexColor("#1f5f99")
RULE = colors.HexColor("#d5dae1")
HEAD_RULE = colors.HexColor("#9aa3ae")
HEAD_BG = colors.HexColor("#eef2f6")
ZEBRA = colors.HexColor("#f8f9fb")
QUOTE_BG = colors.HexColor("#f5f8fb")
CODE_BG = colors.HexColor("#f3f5f8")

PAGE_W, PAGE_H = A4
MARGIN_X, MARGIN_TOP, MARGIN_BOTTOM = 16 * mm, 17 * mm, 18 * mm

MARKDOWN_SUFFIXES = {".md", ".markdown"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif"}

# Korean-capable TrueType families (regular, bold), most readable first.
FONT_FAMILIES = [
    ("NanumBarunGothic.ttf", "NanumBarunGothicBold.ttf"),
    ("NanumGothic.ttf", "NanumGothicBold.ttf"),
    ("NotoSansKR-Regular.ttf", "NotoSansKR-Bold.ttf"),
    ("malgun.ttf", "malgunbd.ttf"),
    ("AppleGothic.ttf", None),
]
# Fonts tried in order for symbols the body font lacks (Greek, arrows, math brackets).
FALLBACK_FONTS = ["Arial Unicode.ttf", "Apple Symbols.ttf", "DejaVuSans.ttf", "arialuni.ttf",
                  "seguisym.ttf", "cambria.ttf"]
FONT_DIRS = [
    Path.home() / "Library/Fonts",
    Path("/Library/Fonts"),
    Path("/System/Library/Fonts/Supplemental"),
    Path("/System/Library/Fonts"),
    Path.home() / ".local/share/fonts",
    Path.home() / ".fonts",
    Path("/usr/local/share/fonts"),
    Path("/usr/share/fonts"),
    Path("C:/Windows/Fonts"),
]

SUPER_CHARS = "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ"
SUB_CHARS = "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎"
SUPER_MAP = str.maketrans(SUPER_CHARS, "0123456789+-=()n")
SUB_MAP = str.maketrans(SUB_CHARS, "0123456789+-=()")
SUPSUB = re.compile(f"[{SUPER_CHARS}]+|[{SUB_CHARS}]+")
BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")
INLINE_HTML = {
    "<sub>": "<sub>", "</sub>": "</sub>", "<sup>": "<super>", "</sup>": "</super>",
    "<strong>": "<b>", "</strong>": "</b>", "<b>": "<b>", "</b>": "</b>",
    "<em>": "<i>", "</em>": "</i>", "<br>": "<br/>", "<br/>": "<br/>", "<br />": "<br/>",
}


class ReportError(ValueError):
    """A user-correctable problem with the report or its paths."""


# --------------------------------------------------------------------------- fonts

@lru_cache(maxsize=1)
def _font_index() -> dict[str, Path]:
    index: dict[str, Path] = {}
    for directory in FONT_DIRS:
        if not directory.is_dir():
            continue
        for root, _dirs, files in os.walk(directory):
            for name in files:
                if name.lower().endswith(".ttf"):
                    index.setdefault(name.lower(), Path(root) / name)
    return index


def _cmap(path: Path) -> frozenset[int]:
    from fontTools.ttLib import TTFont as FTFont

    with FTFont(str(path), lazy=True) as font:
        return frozenset(font.getBestCmap() or {})


class Fonts:
    """Registered fonts plus glyph coverage used to route missing characters."""

    def __init__(self) -> None:
        self.warnings: list[str] = []
        regular, bold = self._pick_family()
        if regular is None:
            self.regular, self.bold = "Helvetica", "Helvetica-Bold"
            self.coverage = frozenset(range(32, 256))
            self.label = "Helvetica (no Korean TrueType font found)"
            self.warnings.append("no_korean_font: install NanumBarunGothic or set SNU_REPORT_FONT")
        else:
            self.regular, self.bold = "ReportBody", "ReportBody-Bold"
            pdfmetrics.registerFont(TTFont(self.regular, str(regular)))
            pdfmetrics.registerFont(TTFont(self.bold, str(bold or regular)))
            pdfmetrics.registerFontFamily(self.regular, normal=self.regular, bold=self.bold,
                                          italic=self.regular, boldItalic=self.bold)
            self.coverage = _cmap(regular)
            self.label = regular.name + (f" + {bold.name}" if bold and bold != regular else "")
        self.fallbacks: list[tuple[str, frozenset[int]]] = []
        for name in FALLBACK_FONTS:
            path = _font_index().get(name.lower())
            if not path:
                continue
            font_name = f"ReportFallback{len(self.fallbacks)}"
            try:
                pdfmetrics.registerFont(TTFont(font_name, str(path)))
            except Exception:  # PostScript-outline or broken font files
                continue
            self.fallbacks.append((font_name, _cmap(path)))
            self.label += f"; fallback {path.name}"
        self.missing: set[str] = set()

    def _pick_family(self) -> tuple[Path | None, Path | None]:
        env_regular = os.environ.get("SNU_REPORT_FONT")
        if env_regular and Path(env_regular).is_file():
            env_bold = os.environ.get("SNU_REPORT_FONT_BOLD")
            return Path(env_regular), Path(env_bold) if env_bold and Path(env_bold).is_file() else None
        index = _font_index()
        for regular, bold in FONT_FAMILIES:
            if regular.lower() in index:
                return index[regular.lower()], index.get(bold.lower()) if bold else None
        return None, None

    def runs(self, text: str) -> str:
        """Escape text, wrapping characters the body font lacks in the fallback font."""
        out: list[str] = []
        run: list[str] = []
        run_font: str | None = None
        for ch in text:
            code = ord(ch)
            font: str | None = None
            if code not in self.coverage and not ch.isspace():
                font = next((name for name, cover in self.fallbacks if code in cover), None)
                if font is None:
                    self.missing.add(ch)
            if font != run_font and run:
                out.append(self._wrap("".join(run), run_font))
                run = []
            run_font = font
            run.append(ch)
        if run:
            out.append(self._wrap("".join(run), run_font))
        return "".join(out)

    @staticmethod
    def _wrap(text: str, font: str | None) -> str:
        escaped = html.escape(text, quote=False)
        return f'<font name="{font}">{escaped}</font>' if font else escaped

    def text(self, raw: str) -> str:
        """Paragraph markup for plain text: sub/superscript digits become tags."""
        out, pos = [], 0
        for match in SUPSUB.finditer(raw):
            out.append(self.runs(raw[pos:match.start()]))
            segment = match.group(0)
            if segment[0] in SUPER_CHARS:
                out.append("<super>" + self.runs(segment.translate(SUPER_MAP)) + "</super>")
            else:
                out.append("<sub>" + self.runs(segment.translate(SUB_MAP)) + "</sub>")
            pos = match.end()
        out.append(self.runs(raw[pos:]))
        return "".join(out)


# --------------------------------------------------------------------------- markdown

def cjk_bold(markdown: str) -> str:
    """CommonMark leaves `**…)**와` unbolded (punctuation before a Hangul particle).
    Convert **bold** to <strong> outside fenced blocks and inline code."""
    out, fenced = [], False
    for line in markdown.splitlines(keepends=True):
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        if fenced or "**" not in line:
            out.append(line)
            continue
        parts = re.split(r"(`[^`]*`)", line)
        out.append("".join(p if p.startswith("`") else BOLD.sub(r"<strong>\1</strong>", p) for p in parts))
    return "".join(out)


def _parser() -> MarkdownIt:
    return MarkdownIt("commonmark", {"html": True}).enable("table").enable("strikethrough")


def _plain(markup: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", markup))


class _Heading(Paragraph):
    """Paragraph that registers a PDF outline entry when drawn."""

    def __init__(self, text: str, style: ParagraphStyle, level: int, title: str, key: str):
        super().__init__(text, style)
        self.outline = (level, title, key)


class _Builder:
    def __init__(self, fonts: Fonts, base_dir: Path, width: float, frame_height: float):
        self.f = fonts
        self.base_dir = base_dir
        self.width = width
        self.frame_height = frame_height
        self.warnings: list[str] = []
        self.title: str | None = None
        self._after_title = False
        self._anchor = 0
        F, B = fonts.regular, fonts.bold
        self.body = ParagraphStyle("body", fontName=F, fontSize=9.6, leading=15.2, textColor=INK, spaceAfter=5.5)
        self.h1 = ParagraphStyle("h1", fontName=B, fontSize=19, leading=25, textColor=INK_STRONG, spaceAfter=3)
        self.meta = ParagraphStyle("meta", fontName=F, fontSize=8.4, leading=12.6, textColor=MUTED, spaceAfter=4)
        self.h2 = ParagraphStyle("h2", fontName=B, fontSize=13, leading=18, textColor=INK_STRONG,
                                 spaceBefore=15, spaceAfter=1)
        self.h3 = ParagraphStyle("h3", fontName=B, fontSize=10.8, leading=15, textColor=INK_STRONG,
                                 spaceBefore=10, spaceAfter=3)
        self.h4 = ParagraphStyle("h4", fontName=B, fontSize=9.8, leading=14, textColor=INK_STRONG,
                                 spaceBefore=8, spaceAfter=2)
        self.cell = ParagraphStyle("cell", fontName=F, fontSize=7.9, leading=11.4, textColor=INK)
        self.cell_key = ParagraphStyle("cell_key", parent=self.cell, fontName=B)
        self.cell_head = ParagraphStyle("cell_head", parent=self.cell, fontName=B, textColor=INK_STRONG)
        self.caption = ParagraphStyle("caption", fontName=F, fontSize=8, leading=11, textColor=MUTED,
                                      alignment=TA_CENTER, spaceAfter=9)
        self.code = ParagraphStyle("code", fontName="Courier", fontSize=7.8, leading=10.4, textColor=INK,
                                   backColor=CODE_BG, borderPadding=5, spaceBefore=3, spaceAfter=9)
        self._list_styles: dict[tuple[int, bool], ParagraphStyle] = {}

    # ---- inline
    def inline(self, token: Token) -> str:
        out: list[str] = []
        links: list[str] = []
        for child in token.children or []:
            kind = child.type
            if kind == "text":
                out.append(self.f.text(child.content))
            elif kind == "code_inline":
                content = child.content
                if all(ord(c) < 128 for c in content):
                    out.append(f'<font name="Courier" color="#36404c">{html.escape(content, quote=False)}</font>')
                else:
                    out.append(self.f.text(content))
            elif kind == "strong_open":
                out.append("<b>")
            elif kind == "strong_close":
                out.append("</b>")
            elif kind == "em_open":
                out.append("<i>")
            elif kind == "em_close":
                out.append("</i>")
            elif kind == "s_open":
                out.append("<strike>")
            elif kind == "s_close":
                out.append("</strike>")
            elif kind == "link_open":
                href = str(child.attrGet("href") or "")
                if href.startswith(("http://", "https://", "mailto:")):
                    out.append(f'<a href="{html.escape(href, quote=True)}" color="#1f5f99">')
                    links.append("</a>")
                else:  # relative links have no target inside a standalone PDF
                    out.append('<font color="#1f5f99">')
                    links.append("</font>")
            elif kind == "link_close":
                out.append(links.pop() if links else "")
            elif kind == "softbreak":
                out.append(" ")
            elif kind == "hardbreak":
                out.append("<br/>")
            elif kind == "html_inline":
                out.append(INLINE_HTML.get(child.content.strip().lower(), ""))
            elif kind == "image":
                out.append(self.f.text(child.content))
        return "".join(out)

    # ---- blocks
    @staticmethod
    def _close(tokens: list[Token], i: int) -> int:
        open_token = tokens[i]
        close_type = open_token.type.replace("_open", "_close")
        for j in range(i + 1, len(tokens)):
            if tokens[j].type == close_type and tokens[j].level == open_token.level:
                return j
        return len(tokens) - 1

    def _list_style(self, depth: int, bulleted: bool) -> ParagraphStyle:
        key = (depth, bulleted)
        if key not in self._list_styles:
            indent = 13 * depth
            self._list_styles[key] = ParagraphStyle(
                f"list{depth}{bulleted}", parent=self.body, leftIndent=indent,
                bulletIndent=max(indent - 10, 0), bulletFontName=self.f.regular,
                bulletFontSize=9.6, spaceAfter=2.6 if bulleted else 4)
        return self._list_styles[key]

    def blocks(self, tokens: list[Token], start: int, end: int, depth: int = 0,
               bullet: str | None = None) -> list[Flowable]:
        flows: list[Flowable] = []
        i = start
        while i < end:
            t = tokens[i]
            if t.type != "paragraph_open" or depth:
                self._after_title = False  # only a top-level paragraph right after the H1 is metadata
            if t.type == "heading_open":
                flows.extend(self._heading(int(t.tag[1]), tokens[i + 1]))
                i = self._close(tokens, i) + 1
            elif t.type == "paragraph_open":
                flows.extend(self._paragraph(tokens[i + 1], depth, bullet))
                bullet = None
                i = self._close(tokens, i) + 1
            elif t.type in ("bullet_list_open", "ordered_list_open"):
                close = self._close(tokens, i)
                flows.extend(self._list(tokens, i, close, depth))
                i = close + 1
            elif t.type == "table_open":
                close = self._close(tokens, i)
                flows.append(self._table(tokens[i + 1:close], depth))
                i = close + 1
            elif t.type == "blockquote_open":
                close = self._close(tokens, i)
                flows.append(self._quote(self.blocks(tokens, i + 1, close, depth)))
                i = close + 1
            elif t.type in ("fence", "code_block"):
                flows.append(Preformatted(t.content.rstrip("\n"), self.code))
                i += 1
            elif t.type == "hr":
                flows.append(HRFlowable(width="100%", thickness=0.6, color=RULE, spaceBefore=6, spaceAfter=8))
                i += 1
            else:
                i += 1
        return flows

    def _heading(self, level: int, inline: Token) -> list[Flowable]:
        markup = self.inline(inline)
        title = _plain(markup).strip()
        if level == 1 and self.title is None:
            self.title = title
            self._after_title = True
            return [Paragraph(markup, self.h1)]
        style = {1: self.h2, 2: self.h2, 3: self.h3}.get(level, self.h4)
        self._anchor += 1
        key = f"sec{self._anchor}"
        # A conditional break instead of keepWithNext: a heading never sits alone at a
        # page bottom, yet a long table after it still splits across pages.
        flows: list[Flowable] = [CondPageBreak(36 * mm if level <= 2 else 26 * mm),
                                 _Heading(f'<a name="{key}"/>{markup}', style, 0 if level <= 2 else 1, title, key)]
        if level <= 2:
            flows.append(HRFlowable(width="100%", thickness=0.6, color=RULE, spaceBefore=1.5, spaceAfter=6))
        return flows

    def _paragraph(self, inline: Token, depth: int, bullet: str | None) -> list[Flowable]:
        children = [c for c in inline.children or [] if not (c.type == "text" and not c.content.strip())]
        if children and all(c.type in ("image", "softbreak") for c in children):
            return [f for c in children if c.type == "image" for f in self._image(c)]
        markup = self.inline(inline)
        if self._after_title:
            self._after_title = False
            return [Paragraph(markup, self.meta),
                    HRFlowable(width="100%", thickness=1.1, color=INK, spaceBefore=3, spaceAfter=11)]
        if depth:
            style = self._list_style(depth, bullet is not None)
            return [Paragraph(markup, style, bulletText=bullet)]
        return [Paragraph(markup, self.body)]

    def _list(self, tokens: list[Token], i: int, close: int, depth: int) -> list[Flowable]:
        ordered = tokens[i].type == "ordered_list_open"
        number = int(tokens[i].attrGet("start") or 1)
        flows: list[Flowable] = []
        j = i + 1
        while j < close:
            if tokens[j].type == "list_item_open":
                item_close = self._close(tokens, j)
                mark = f"{number}." if ordered else ("•" if depth == 0 else "–")
                flows.extend(self.blocks(tokens, j + 1, item_close, depth + 1, mark))
                number += 1
                j = item_close + 1
            else:
                j += 1
        if depth == 0 and flows:
            flows.append(Spacer(1, 3))
        return flows

    def _table(self, tokens: list[Token], depth: int) -> Flowable:
        rows: list[list[str]] = []
        header_rows = 0
        in_head = False
        for t in tokens:
            if t.type == "thead_open":
                in_head = True
            elif t.type == "thead_close":
                in_head = False
            elif t.type == "tr_open":
                rows.append([])
                if in_head:
                    header_rows += 1
            elif t.type == "inline" and rows:
                rows[-1].append(self.inline(t))
        if not rows:
            return Spacer(1, 0)
        ncols = max(len(r) for r in rows)
        rows = [r + [""] * (ncols - len(r)) for r in rows]
        available = self.width - 13 * depth
        widths = self._column_widths(rows, available)
        key_column = ncols >= 3
        data = []
        for r_index, row in enumerate(rows):
            cells = []
            for c_index, markup in enumerate(row):
                if r_index < header_rows:
                    style = self.cell_head
                elif c_index == 0 and key_column:
                    style = self.cell_key
                else:
                    style = self.cell
                cells.append(Paragraph(markup or "&nbsp;", style))
            data.append(cells)
        table = Table(data, colWidths=widths, repeatRows=header_rows, hAlign="LEFT")
        commands: list[tuple[Any, ...]] = [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4.5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4.5),
            ("TOPPADDING", (0, 0), (-1, -1), 3.2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3.6),
            ("LINEBELOW", (0, header_rows), (-1, -1), 0.4, RULE),
        ]
        if header_rows:
            commands += [("BACKGROUND", (0, 0), (-1, header_rows - 1), HEAD_BG),
                         ("LINEBELOW", (0, header_rows - 1), (-1, header_rows - 1), 0.9, HEAD_RULE)]
        for r in range(header_rows + 1, len(rows), 2):
            commands.append(("BACKGROUND", (0, r), (-1, r), ZEBRA))
        table.setStyle(TableStyle(commands))
        table.spaceBefore, table.spaceAfter = 3, 11
        return table

    def _column_widths(self, rows: list[list[str]], available: float) -> list[float]:
        """Browser-like auto layout: share width by max-content, but never below a
        column's longest word (capped at 18% of the width so one token can't starve the rest)."""
        ncols = len(rows[0])
        pad = 9.0
        size = self.cell.fontSize
        cap = available * 0.18
        natural = [0.0] * ncols
        floor = [0.0] * ncols
        for row in rows:
            for c, markup in enumerate(row):
                text = _plain(markup)
                natural[c] = max(natural[c], pdfmetrics.stringWidth(text, self.f.regular, size) * 1.04 + pad)
                for word in text.split():
                    floor[c] = max(floor[c], min(pdfmetrics.stringWidth(word, self.f.regular, size) + pad, cap))
        floor = [max(f, 28.0) for f in floor]
        natural = [max(n, f) for n, f in zip(natural, floor)]
        if sum(natural) <= available:
            return [n * available / sum(natural) for n in natural]
        if sum(floor) >= available:
            return [f * available / sum(floor) for f in floor]
        fixed: dict[int, float] = {}
        while True:
            free = [c for c in range(ncols) if c not in fixed]
            room = available - sum(fixed.values())
            total = sum(natural[c] for c in free)
            share = {c: room * natural[c] / total for c in free}
            short = [c for c in free if share[c] < floor[c]]
            if not short:
                return [fixed[c] if c in fixed else share[c] for c in range(ncols)]
            for c in short:
                fixed[c] = floor[c]

    def _quote(self, inner: list[Flowable]) -> Flowable:
        box = Table([[inner or ""]], colWidths=[self.width])
        box.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), QUOTE_BG),
            ("LINEBEFORE", (0, 0), (0, -1), 2.5, ACCENT),
            ("LEFTPADDING", (0, 0), (-1, -1), 9),
            ("RIGHTPADDING", (0, 0), (-1, -1), 9),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        box.spaceBefore, box.spaceAfter = 2, 9
        return box

    def _image(self, token: Token) -> list[Flowable]:
        src = token.attrGet("src") or ""
        alt = token.content.strip()
        if re.match(r"^[a-z]+:", str(src), re.I):
            self.warnings.append(f"image_skipped_remote: {src}")
            return []
        path = (self.base_dir / str(src)).resolve()
        if not path.is_relative_to(self.base_dir):
            self.warnings.append(f"image_skipped_outside_report_folder: {src}")
            return []
        if path.suffix.lower() not in IMAGE_SUFFIXES or not path.is_file():
            self.warnings.append(f"image_skipped_unsupported_or_missing (use PNG/JPG): {src}")
            return []
        iw, ih = ImageReader(str(path)).getSize()
        width = min(self.width, float(iw))
        height = ih * width / iw
        if height > self.frame_height * 0.55:
            height = self.frame_height * 0.55
            width = iw * height / ih
        image = Image(str(path), width=width, height=height)
        image.hAlign = "CENTER"
        flows: list[Flowable] = [Spacer(1, 4), image]
        flows.append(Paragraph(self.f.text(alt), self.caption) if alt else Spacer(1, 9))
        return flows


# --------------------------------------------------------------------------- document

class _ReportDoc(BaseDocTemplate):
    def __init__(self, filename: str, **kwargs: Any):
        super().__init__(filename, pagesize=A4, leftMargin=MARGIN_X, rightMargin=MARGIN_X,
                         topMargin=MARGIN_TOP, bottomMargin=MARGIN_BOTTOM, **kwargs)
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="body",
                      leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        self.addPageTemplates([PageTemplate(id="page", frames=[frame])])

    def afterFlowable(self, flowable: Flowable) -> None:
        outline = getattr(flowable, "outline", None)
        if outline:
            level, title, key = outline
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(title, key, level=level, closed=level > 0)


def _canvas_class(footer: str, font: str):
    class NumberedCanvas(rl_canvas.Canvas):
        """Draws 'title … n / N' on every page once the total is known."""

        def __init__(self, *args: Any, **kwargs: Any):
            super().__init__(*args, **kwargs)
            self._pages: list[dict[str, Any]] = []

        def showPage(self) -> None:  # noqa: N802 (reportlab API)
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self) -> None:
            total = len(self._pages)
            for state in self._pages:
                self.__dict__.update(state)
                self.saveState()
                self.setFont(font, 7.5)
                self.setFillColor(MUTED)
                self.drawString(MARGIN_X, 10 * mm, footer)
                self.drawRightString(PAGE_W - MARGIN_X, 10 * mm, f"{self._pageNumber} / {total}")
                self.restoreState()
                super().showPage()
            super().save()

    return NumberedCanvas


def _resolve_paths(markdown_path: str | Path, output_path: str | Path | None,
                   suffix: str = ".pdf") -> tuple[Path, Path]:
    source = Path(markdown_path).expanduser()
    if source.suffix.lower() not in MARKDOWN_SUFFIXES:
        raise ReportError("markdown_path must be a .md or .markdown file")
    if not source.is_file():
        raise ReportError("markdown_path does not exist")
    source = source.resolve()
    output = Path(output_path).expanduser() if output_path else source.with_suffix(suffix)
    if output.suffix.lower() not in {".pdf", ".html"}:
        raise ReportError("output_path must end with .html or .pdf")
    if output.is_symlink():
        raise ReportError("output_path must not be a symbolic link")
    if not output.parent.is_dir():
        raise ReportError("output_path folder does not exist")
    return source, output.resolve()


ENGINES = ("auto", "quarto", "reportlab")


FORMATS = ("html", "pdf")


def render_report(markdown_path: str | Path, output_path: str | Path | None = None,
                  engine: str = "auto", formats: list[str] | tuple[str, ...] | None = None) -> dict[str, Any]:
    """Render a Markdown report. JSON-safe status dict; `output_path` in it is the main file.

    Reports are read on screen, so the default output is one standalone HTML page (Quarto).
    formats: any of "html", "pdf"; default ["html"], or ["pdf"] when output_path ends in .pdf.
    engine: "auto" uses Quarto when installed, otherwise the built-in reportlab PDF;
    "quarto" requires Quarto; "reportlab" forces the built-in PDF renderer.

    When the report's folder (or its parent, for ideas/README.md) holds an evidence/ folder,
    the evidence lint runs too: its errors and a summary line go into `warnings`. The lint
    never fails the render.
    """
    result = _render_report(markdown_path, output_path, engine, formats)
    if result.get("ok") and isinstance(result.get("warnings"), list):
        result["warnings"].extend(_evidence_lint_warnings(markdown_path))
    return result


def _evidence_lint_warnings(markdown_path: str | Path) -> list[str]:
    try:
        from scholarly_access_agent.evidence import lint_folder, summary_line

        folder = Path(markdown_path).expanduser().resolve().parent
        topic = next((f for f in (folder, folder.parent) if (f / "evidence").is_dir()), None)
        if topic is None:
            return []
        lint = lint_folder(topic)
        lines = [f"evidence_lint error: {f['file']} {f['rule']}: {f['message']}"
                 for f in lint["findings"] if f["level"] == "error"]
        return lines + [summary_line(lint, topic)]
    except Exception as exc:  # the lint must never break a render
        return [f"evidence_lint_failed: {type(exc).__name__}"]


def _render_report(markdown_path: str | Path, output_path: str | Path | None = None,
                   engine: str = "auto", formats: list[str] | tuple[str, ...] | None = None) -> dict[str, Any]:
    """Render without the evidence lint (see render_report)."""
    from . import quarto_report

    if engine not in ENGINES:
        return {"ok": False, "status": "invalid_input", "reason": f"engine must be one of {', '.join(ENGINES)}"}
    if formats is None:
        wanted = (".pdf" if str(output_path or "").lower().endswith(".pdf") or engine == "reportlab" else ".html",)
        formats = tuple(s.lstrip(".") for s in wanted)
    formats = tuple(dict.fromkeys(str(f).lower() for f in formats))
    if not formats or any(f not in FORMATS for f in formats):
        return {"ok": False, "status": "invalid_input", "reason": "formats must be html and/or pdf"}
    try:
        source, output = _resolve_paths(markdown_path, output_path, "." + formats[0])
    except ReportError as exc:
        return {"ok": False, "status": "invalid_input", "reason": str(exc)}
    notes: list[str] = []
    if engine != "reportlab":
        quarto = quarto_report.find_quarto()
        if quarto:
            return quarto_report.render_with_quarto(source, output, quarto, formats)
        if engine == "quarto":
            return {"ok": False, "status": "quarto_unavailable",
                    "reason": "Quarto not found: install it (https://quarto.org) or set QUARTO_PATH"}
        if "html" in formats:
            notes.append("quarto_unavailable: the HTML report needs Quarto (https://quarto.org); "
                         "wrote the PDF with the built-in reportlab engine instead")
    result = _render_reportlab(source, output.with_suffix(".pdf"))
    result["warnings"] = notes + result["warnings"]
    return result


def _render_reportlab(source: Path, output: Path) -> dict[str, Any]:
    fonts = Fonts()
    frame_width = PAGE_W - 2 * MARGIN_X
    frame_height = PAGE_H - MARGIN_TOP - MARGIN_BOTTOM
    builder = _Builder(fonts, source.parent, frame_width, frame_height)
    tokens = _parser().parse(cjk_bold(source.read_text(encoding="utf-8")))
    story = builder.blocks(tokens, 0, len(tokens))
    title = builder.title or source.stem

    footer = title
    while pdfmetrics.stringWidth(footer, fonts.regular, 7.5) > frame_width * 0.75 and len(footer) > 4:
        footer = footer[:-2]
    if footer != title:
        footer = footer.rstrip() + "…"

    temporary = output.with_name(f".{output.stem}.rendering.pdf")
    doc = _ReportDoc(str(temporary), title=title, subject="Research report", author="",
                     creator="snu-research-agent render-report (reportlab)")
    try:
        doc.build(story, canvasmaker=_canvas_class(footer, fonts.regular))
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)

    from pypdf import PdfReader

    pages = len(PdfReader(str(output)).pages)
    return {
        "ok": True,
        "engine": "reportlab",
        "output_path": str(output),
        "html_path": None,
        "pdf_path": str(output),
        "pages": pages,
        "title": title,
        "font": fonts.label,
        "missing_glyphs": "".join(sorted(fonts.missing)),
        "warnings": fonts.warnings + builder.warnings,
    }
