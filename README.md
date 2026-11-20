# SNU Research Agent — MCP + Skill

Local scholarly full-text evidence for Codex and Claude. Native search discovers papers; this package accesses permitted PDFs through SNU and returns page-grounded text. It is not a global full-text search index.

## Install

```sh
git clone https://github.com/SleepingDawn/snu-research-agent.git
cd snu-research-agent
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m playwright install chromium
.venv/bin/scholarly-access-agent setup
.venv/bin/scholarly-access-agent doctor
```

Connect MCP using `examples/claude-mcp.json` or `examples/codex-mcp.toml`, replacing the executable path. Claude Code: `claude mcp add --scope user snu-library -- /absolute/repo/.venv/bin/scholarly-access-agent mcp-server`. For Claude account Skills upload `dist/snu-library-scholarly-access.zip` and `dist/research-lineage.zip`. Restart clients after changing tools. A cloud-only session needs a local MCP connection to use local access.

## Authentication and research

Run `scripts/서울대 로그인.command` for user-assisted SNU sign-in. Passwords are never loaded or auto-entered. Routine research uses native search and CLI/MCP only, with headless downloads. Session renewal alone opens a window. Session files stay outside the repo, owner-only and unencrypted.

The canonical skill is `skills/snu-library-scholarly-access/SKILL.md`; references separate workflow, DFT/MLIP criteria, evidence format and authentication. Installed copies add a local executable hint, excluded from the upload ZIP.

Tools: `doctor`, `check_url`, `proxy_url`, `read_url`, `discover_pdfs`, `download_pdf`, `read_pdf`, `render_report_pdf`, `add_domain`. Workflow is text first and journal first: when a peer-reviewed journal version exists it is read before the arXiv/preprint (publisher OA or PMC via `read_url`, otherwise the SNU route), with the preprint as a labelled fallback; `read_url` reads open-access HTML (publisher OA, PMC, Europe PMC, arXiv, chemRxiv, bioRxiv) as an outline, term excerpts or whole sections; `download_pdf` fetches open-repository PDFs directly and publisher PDFs through the SNU session, for paywalled papers, page citations or figures. Large reviews delegate reading to sub-agents that return compact evidence records. MCP download operations always run headless. CLI and MCP share the same reading/downloading implementation. Doctor checks session presence, not validity. Subscription access does not establish external AI permission; see https://lib.snu.ac.kr/find/databases_openaccess/tdm/ . Scanned PDFs require OCR or visual review. For `read_pdf`, choose `terms` OR `pages`; never both. `pages_scanned` reports search coverage, not pages fully reviewed by the agent.

## PDF reports

The last step turns the finished Markdown review into a readable A4 PDF: `render_report_pdf` (MCP) or `scholarly-access-agent render-report REPORT.md [-o OUT.pdf]`. It reads only the Markdown and PNG/JPG figures inside the report folder, fetches nothing, and returns `pages`, `font`, `missing_glyphs` and `warnings`. Layout: Korean TrueType body font (NanumBarunGothic first; override with `SNU_REPORT_FONT`/`SNU_REPORT_FONT_BOLD`) with symbol fallback fonts tried in order, 9.6 pt body, tables with repeated headers and content-sized columns, PDF outline from `##`/`###`, page n/N footer. Report structure and checks: `skills/snu-library-scholarly-access/references/report-pdf.md`.

## Research lineage

A second skill, `skills/research-lineage/SKILL.md`, traces where a concept came from, how it branched and what is mainstream now. `scholarly-access-agent lineage <command>` does the deterministic part from OpenAlex: `seed`, `collect` (seed, references and citing papers; optional widening by tested boolean queries or by the most-cited ancestors), `analyze` (reference-year spectroscopy, bibliographic-coupling clusters, SPC main path; saves `analysis.txt`), `keywords` and `query-test` (concept-block queries scored by citation-anchored precision, recall on a gold set of key papers and novelty; several queries per call run in parallel; logged to `queries.json`), `mentions`, `links` (journal first), `check` (validation and layout warnings such as edges drawn through another box, without rendering), `page` (interactive HTML: boxes open the paper, hover shows the lineage) and `report-section` (a Markdown chapter with stage table, trends and a PNG diagram rendered with headless Chromium, for `render-report`). The agent chooses the seed, reads with the tools above, decides the branches and writes the text flow in one `lineage.json` (schema and worked example in the skill). `OPENALEX_API_KEY` raises the OpenAlex quota; it is read from the environment (and the Windows user variable) and never printed. A spent daily quota stops a command with exit code 3; caches are kept so rerunning resumes.

## Verify

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m pip check
```

CI uses synthetic fixtures and needs no SNU credentials. Before private GitHub upload, inspect staged files and history; exclude sessions, credentials, PDFs, reports and generated packages. Runtime data remains local even when this source repository is private.

## Provenance

Based on https://github.com/onetwothr1/SNU-library-scholarly-access-skill at `cad5e9a5e9ab259642b5dee13d6022427e56bd03`. Upstream README declares MIT. The original MIT notice, including its copyright attribution, is retained in `LICENSE`, recovered verbatim from upstream commit `b5d7927` (it was absent at the review revision). No ownership claim is made over upstream code.

Design references (consulted 2026-11-17):
- https://github.com/K-Dense-AI/scientific-agent-skills/tree/main/skills/literature-review
- https://github.com/K-Dense-AI/scientific-agent-skills/tree/main/skills/research-lookup
- https://liyux3.github.io/scholar-mcp/research-workflows/
- https://github.com/Future-House/paper-qa
- https://github.com/anthropics/skills/tree/main/skills/pdf (consulted 2026-11-18; reportlab Platypus rendering, sub/superscript markup rule)
- https://github.com/anthropics/skills/tree/main/skills/theme-factory (consulted 2026-11-18; one palette and font pairing, contrast first)

Their workflow and rendering patterns informed original code and instructions here; their code and text were not vendored.
