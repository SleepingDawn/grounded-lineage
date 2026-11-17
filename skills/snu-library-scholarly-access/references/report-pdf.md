# Report and PDF delivery
Write the finished report in Markdown, then render it with `render_report_pdf(markdown_path)` (CLI: `scholarly-access-agent render-report REPORT.md [-o OUT.pdf]`). The PDF lands next to the Markdown unless `output_path` is given.

Structure:
1. `# Title`, then one metadata line (date · version · method · evidence files); it becomes the subtitle.
2. Summary (한눈에 보기): 4–7 bullets, one claim each, with its key number and unit.
3. Body under `##`/`###` (they become the PDF outline). Compare items in pipe tables: one row per item, short cells, units in the header or cell; split tables wider than about 7 columns.
4. Evidence status per item (**본문 확인 (섹션/페이지)**, **초록만 확인**, **미확인**), a change log when revising, then sources with links; mark preprints.

Authoring: pipe tables only; figures as local PNG/JPG inside the report folder (`![caption](figs/x.png)`), since SVG and remote images are skipped; no raw HTML except `<sub>`, `<sup>`, `<br>`. `**bold**` before a Korean particle and Unicode sub/superscripts (H₂, Å³) are handled.

Layout the renderer applies: A4; a Korean TrueType body font (NanumBarunGothic first, then NanumGothic, Noto Sans KR, Malgun Gothic; override with `SNU_REPORT_FONT`/`SNU_REPORT_FONT_BOLD`) with wide-coverage fallbacks for symbols, tried in order; 9.6 pt body at 1.6 leading; 7.9 pt tables with repeated headers, zebra rows and content-sized columns; one ink and one accent colour, all text at least 4.5:1 contrast; title and page n/N footer.

Before delivering: `missing_glyphs` must be empty and `warnings` explained; view the first page and one table page as images (for example `pdftoppm -r 70 -png`). Basis: reportlab Platypus as in Anthropic's `pdf` skill and the palette, font-pairing and contrast guidance of its `theme-factory` skill (anthropics/skills); neither is vendored.
