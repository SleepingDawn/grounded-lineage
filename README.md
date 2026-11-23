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

Connect MCP using `examples/claude-mcp.json` or `examples/codex-mcp.toml`, replacing the executable path. Claude Code: `claude mcp add --scope user snu-library -- /absolute/repo/.venv/bin/scholarly-access-agent mcp-server`. Codex: copy the `examples/codex-mcp.toml` block into `~/.codex/config.toml` (`setup` installs skills only, not the MCP entry); keep `default_tools_approval_mode = "approve"`, because Codex otherwise asks approval for every MCP call and fails them in `codex exec` and automations, and `tool_timeout_sec = 300`, because the 60 s default can cut off `download_pdf`. `add_domain` stays on prompt. For Claude account Skills upload the four ZIPs in `dist/` (`snu-library-scholarly-access`, `research-lineage`, `research-topic-scout`, `research-pilot`). Restart clients after changing tools. A cloud-only session needs a local MCP connection to use local access.

## Authentication and research

Run `scripts/서울대 로그인.command` for user-assisted SNU sign-in. Passwords are never loaded or auto-entered. Routine research uses native search and CLI/MCP only, with headless downloads. Session renewal alone opens a window. Session files stay outside the repo, owner-only and unencrypted.

The canonical skill is `skills/snu-library-scholarly-access/SKILL.md`; references separate workflow, DFT/MLIP criteria, evidence format and authentication. Installed copies add a local executable hint, excluded from the upload ZIP.

Tools: `doctor`, `check_url`, `proxy_url`, `read_url`, `discover_pdfs`, `download_pdf`, `read_pdf`, `render_report_pdf`, `add_domain`. Workflow is text first and journal first: when a peer-reviewed journal version exists it is read before the arXiv/preprint (PMC via `read_url`, otherwise the publisher page through `download_pdf`), with the preprint as a labelled fallback; `read_url` reads open-access HTML from the open-repository allow-list (PMC, Europe PMC, arXiv, chemRxiv, bioRxiv, medRxiv) as an outline, term excerpts or whole sections; `download_pdf` fetches open-repository PDFs directly and publisher PDFs through the SNU session, for paywalled papers, page citations or figures. Large reviews delegate reading to sub-agents that return compact evidence records. MCP download operations always run headless. CLI and MCP share the same reading/downloading implementation. Doctor checks session presence, not validity; `doctor --probe <paywalled article URL>` (MCP `probe_url`) checks validity by fetching that one PDF into a temporary folder that is deleted at once. Per-publisher retrieval routes are in `skills/snu-library-scholarly-access/references/publisher-routes.md`. Publisher bot checks (Cloudflare and similar) are reported as `status: "blocked"`, `reason: "bot_challenge"`, separately from `login_required`; they are never solved or bypassed, and PDF endpoints served without a check are still tried. Subscription access does not establish external AI permission; see https://lib.snu.ac.kr/find/databases_openaccess/tdm/ . Scanned PDFs require OCR or visual review. For `read_pdf`, choose `terms` OR `pages`; never both. `pages_scanned` reports search coverage, not pages fully reviewed by the agent.

## Reports (HTML first)

The last step turns the finished Markdown review into one standalone HTML page, since reports are read on screen: `render_report_pdf` (MCP) or `scholarly-access-agent render-report REPORT.md [-o OUT.html] [--format html|pdf] [--engine auto|quarto|reportlab]`. It needs [Quarto](https://quarto.org) (it bundles Pandoc and Typst; `QUARTO_PATH` if it is not on PATH) and uses the theme in `src/scholarly_access_agent/data/quarto` (KRDS-style Korean type, Tufte-style measure, content-sized table columns, side table of contents). An image titled `"interactive=page.html"` is replaced in the HTML by that local clickable page (the research-lineage figure is written this way). `--format pdf` (MCP `formats`) adds an A4 PDF through Typst when one is wanted. Without Quarto the built-in reportlab engine below writes a PDF instead and reports `quarto_unavailable`. It reads only the Markdown and local figures and pages inside the report folder, fetches nothing, and returns `output_path`, `html_path`, `pdf_path`, `pages`, `font`, `missing_glyphs` and `warnings`. Built-in PDF layout: Korean TrueType body font (NanumBarunGothic first; override with `SNU_REPORT_FONT`/`SNU_REPORT_FONT_BOLD`) with symbol fallback fonts tried in order, 9.6 pt body, tables with repeated headers and content-sized columns, PDF outline from `##`/`###`, page n/N footer. Report structure and checks: `skills/snu-library-scholarly-access/references/report-pdf.md`.

## Research lineage

A second skill, `skills/research-lineage/SKILL.md`, traces where a concept came from, how it branched and what is mainstream now. `scholarly-access-agent lineage <command>` does the deterministic part from OpenAlex: `seed`, `collect` (seed, references and citing papers; optional widening by tested boolean queries or by the most-cited ancestors; every citing paper of the seed is kept, and capped lists take half most-cited and half newest so recent low-citation work is not cut), `analyze` (reference-year spectroscopy, bibliographic-coupling clusters, SPC main path; saves `analysis.txt`), `keywords` and `query-test` (concept-block queries scored by citation-anchored precision, recall on a gold set of key papers and novelty; several queries per call run in parallel; logged to `queries.json`), `mentions`, `links` (journal first), `check` (validation and layout warnings such as edges drawn through another box, without rendering), `page` (interactive HTML: boxes open the paper, hover shows the lineage) and `report-section` (a Markdown chapter with stage table, trends and a PNG diagram rendered with headless Chromium, for `render-report`). The agent chooses the seed, reads with the tools above, decides the branches and writes the text flow in one `lineage.json` (schema and worked example in the skill). `OPENALEX_API_KEY` raises the OpenAlex quota; it is read from the environment (and the Windows user variable) and never printed. A spent daily quota stops a command with exit code 3; caches are kept so rerunning resumes.

## Topic recommendation and the research pilot

`skills/research-topic-scout/SKILL.md` turns a finished review folder into research-topic recommendations: a gap matrix built from the saved evidence records (empty cells are searched before they count as gaps), question cards, a novelty check that reads the closest papers' Methods in full text and grades overlap (None to Exact), feasibility against the user's own resources, critique with a pre-mortem, and a five-point readiness gate. When research-lineage ran for the topic, its branch axes and stalled branches feed the gap matrix. After the report it offers, only on request, an ARS socratic dialogue to refine one card and a weekly watch for competing preprints. Card fields and the readiness-gate idea are adapted from Galaxy-Dawn/claude-scholar `research-ideation` (MIT).

`skills/research-pilot/SKILL.md` is one entry point that routes a request to a playbook (`status`: literature review; `topics`: review, then topic recommendation), stops at most twice with a recommended option first (or takes it automatically under `checkpoints: auto-recommend`), passes every sub-agent a shared `worker.md` and its model row from `references/research-models.md`, and logs each run to `<Topic>/run.jsonl`. Its structure (entry skill, playbooks ending in a required-reply list, shared worker rules, one model sheet) follows michael-denyer/pstack-claude (MIT).

`scholarly-access-agent cost` keeps runs inside a budget: `estimate` gives tokens per stage and role for a playbook and preset (the dry run), with a cap from the remaining plan limit and the reduced counts that fit it; `record` appends measured stage tokens to `<research root>/.cost/ledger.jsonl`; `report` compares estimate and measurement and shows the per-stage calibration that later estimates use.

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
