# Report delivery (HTML first)
Reports are read on screen. Write the finished report in Markdown, then render it with `render_report_pdf(markdown_path)` (CLI: `scholarly-access-agent render-report REPORT.md [-o OUT.html] [--format html|pdf] [--engine auto|quarto|reportlab]`). The default output is one standalone HTML page next to the Markdown (`output_path` = `html_path`): table of contents, figures and styles embedded, nothing loaded from the network. Add a PDF only when the user asks for one (sharing, submission, page-stable citation): `formats: ["html", "pdf"]` or `["pdf"]`. HTML needs Quarto; without it the built-in reportlab engine writes the PDF instead and says so in `warnings` (`quarto_unavailable`).

Structure:
1. `# Title`, then one metadata line (date · version · method · evidence files); it becomes the subtitle.
2. Summary (한눈에 보기): 4–7 bullets, one claim each, with its key number and unit.
3. Body under `##`/`###` (they become the table of contents and PDF outline). Compare items in pipe tables: one row per item, short cells, units in the header or cell; split tables wider than about 7 columns.
4. Put the key conclusion or current verdict in a `>` quote: it becomes a callout box.
5. Evidence status per item (**본문 확인 (섹션/페이지)**, **초록만 확인**, **미확인**) and its source type (저널 · 학회 논문 · 학회 초록 · 학위논문 · preprint · 보고서), a change log when revising, then sources with links; mark preprints and 예비 근거.

**Topic reports** (a subject, policy or phenomenon rather than a method's genealogy): the body follows the reader's questions, not a taxonomy of the literature.
- One `##` section per question, 3–5 questions, in the order the summary answers them; the questions are the same as the topic-mode lanes of a research flow map when there is one (research-lineage).
- Each section opens with its one-line answer (with the key number), then an evidence table: 연구 | 장소·대상 | 설계 | 결과 (수치·단위) | 근거 상태. Rows ordered by design strength or year, so effect sizes can be compared at a glance.
- Disagreements go in the section where they bear on the answer, with both sides cited.
- The full per-paper list goes last, as an appendix grouped by question.
- Preliminary items (conference abstracts, preprints, abstract-only, per research-workflow.md "Source quality") sit below the peer-reviewed rows of a table, labelled 예비 근거, or in a separate "최신·예비 근거" block; the one-line answer never rests on them alone.
- A grouping of the literature that you made up yourself may appear only as a labelled framing ("이 보고서의 정리 방식"), at most three groups, and never as the section structure.

Authoring: pipe tables only; figures as local PNG/JPG inside the report folder (`![caption](figs/x.png)`), since SVG and remote images are skipped; no raw HTML except `<sub>`, `<sup>`, `<br>`. `**bold**` before a Korean particle and Unicode sub/superscripts (H₂, Å³) are handled. Interactive figure: give the static image the title `"interactive=page.html"` (a local HTML page in the report folder, e.g. the research-lineage page) and the HTML report inlines that clickable page in place of the image; a PDF keeps the PNG. `lineage report-section` writes its figure this way.

Layout (theme in `src/scholarly_access_agent/data/quarto`): one Korean sans family (Pretendard, NanumBarunGothic, Noto Sans KR, Malgun Gothic, first installed; override with `SNU_REPORT_FONT_FAMILY`), about 1.6 line height and a short measure (KRDS-style type, Tufte-style measure); `##` headings with a rule, `###` in the accent colour; quiet tables with a header band, zebra rows and column widths sized to content (the longest token of a column never wraps); one ink and one accent colour, all text at least 4.5:1 contrast. HTML: 17 px body, `word-break: keep-all` for Korean, side table of contents. PDF (Typst): A4, 10.5 pt, title block and page n/N footer. Built-in reportlab PDF (no Quarto): 9.6 pt body, NanumBarunGothic first (`SNU_REPORT_FONT`/`SNU_REPORT_FONT_BOLD`), same palette.

Before delivering: `missing_glyphs` must be empty and `warnings` explained; open the HTML (or view the first page and one table page of a PDF as images, e.g. `pdftoppm -r 70 -png`) and check the summary, one table and the figures. Basis: KRDS (Korean government design system) typography and Tufte's layout guidance for the theme; reportlab Platypus as in Anthropic's `pdf` skill for the fallback; neither is vendored.
