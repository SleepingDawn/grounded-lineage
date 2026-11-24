# grounded-lineage

Literature research for Claude Code, Codex and claude.ai that traces how a field developed, grounds every claim in full text you can check down to the page, and draws the figures a reader actually asks for. Subscription papers are read through the SNU library.

- **Logical prior-work and research-flow investigation.** Citation data from OpenAlex finds the candidates (seed, references, citing papers, reference-year spectroscopy, coupling clusters, main path); reading decides the branches. The result is a `lineage.json` flow, organised by the questions that split a method or, for a topic, by the reader's questions.
- **Claims grounded in full text, traceable to the page.** Each paper read becomes an evidence record with its access level, locators and `results[]` numbers. `evidence lint` checks the records, `evidence labels` derives the read-depth label (it is never typed by hand), `report trace` ties every cited key and number back to a record, and `evidence verify` re-reads the PDF page.
- **Visualization that answers the reader's questions.** An interactive research flow map whose boxes open an evidence panel (version read, label, judgments with locators, results), plus figures planned per report question in `figs/figures.json` and drawn by `viz figure` from evidence numbers only.

> **Existing users:** only the display name and repository changed (formerly `snu-research-agent`). The CLI `scholarly-access-agent`, the Python module `scholarly_access_agent`, the MCP server `snu-library` and all skill names are unchanged.

## What it looks like

Each investigation lives in its own folder under the research root (`SNU_RESEARCH_ROOT`), e.g. `<root>/LES-lineage/`. It holds `README.md` (the report source) and `<Topic>.html`, a standalone report page with the research flow map embedded as an auto-sized iframe and the per-question Vega-Lite figures placed in the sections they answer; `evidence/` with one JSON record per paper; `figs/` (figure specs and pages); `data/` (OpenAlex corpus, `analysis.txt`, query and search logs); `run.jsonl` (the pilot's run log); and, after topic recommendation, `ideas/` with the gap matrix, question cards, novelty checks and a recommendation report.

## Quick start

**One command** (needs only git; installs [uv](https://docs.astral.sh/uv/), which brings Python 3.12):

```powershell
# Windows (PowerShell)
irm https://raw.githubusercontent.com/SleepingDawn/grounded-lineage/main/install.ps1 | iex
```

```sh
# macOS / Linux
curl -LsSf https://raw.githubusercontent.com/SleepingDawn/grounded-lineage/main/install.sh | sh
```

It clones into `~/.local/share/research-tools/grounded-lineage` (`GL_ROOT` or `--root` to change; from a clone, `install.ps1` / `sh install.sh` use that clone), then:

1. builds the venv, installs the package and Playwright Chromium, and installs the four skills;
2. installs a portable Quarto for HTML reports if none is found (release hash checked; `QUARTO_PATH` saved on Windows);
3. optionally sets up ReadCube filing (below);
4. registers the `snu-library` (and `readcube`) MCP servers in `~/.claude.json`, and in `~/.codex/config.toml` when Codex is installed, backing up a config before changing it;
5. asks for an optional OpenAlex API key (hidden input; Windows user variable, or your shell rc on macOS/Linux);
6. opens the SNU sign-in window when there is no session (you sign in yourself; on Windows an installed Chrome/Edge is used first) and checks one subscription PDF download;
7. signs in to ReadCube and verifies its writes, if set up.

On Linux, Korean reports need a Korean font (e.g. `sudo apt install fonts-noto-cjk`), and headless Chromium may need `sudo .venv/bin/python -m playwright install-deps chromium`; the installer warns when Chromium does not start. Signing in to SNU needs a desktop session.

Every step checks before acting, so rerun the same command after a session expires or to repair an install. Options (after `install.ps1`, in `$env:GL_INSTALL_ARGS` for the `irm | iex` form, or after `sh -s --`): `--readcube` / `--no-readcube`, `--non-interactive` (install and check only), `--update` (also update readcube-mcp), `--no-register` (leave skills and client configs alone).

**ReadCube filing (optional).** Uses the unofficial [Zhilin0001/readcube-mcp](https://github.com/Zhilin0001/readcube-mcp), pinned to a reviewed commit, with its own venv in `<root>/readcube-mcp`. It needs a ReadCube email + password account (no SSO/MFA); its sign-in prompts are in Chinese (邮箱 email, 密码 password). Its write tools only work after a session-bound verification: the installer offers to run it in a private test collection `grounded-lineage verify <date>` and empties it afterwards; delete the empty collection in the ReadCube app. Signing in again voids the verification (rerun the installer). Do not run `login_local.py --check` by hand: it saves rotated cookies, which also voids it.

**Manual install:**

```sh
git clone https://github.com/SleepingDawn/grounded-lineage.git
cd grounded-lineage
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m playwright install chromium
.venv/bin/scholarly-access-agent setup      # installs the skills for Codex and Claude Code
.venv/bin/scholarly-access-agent doctor
```

On Windows the executables are in `.venv\Scripts\`; set `PYTHONUTF8=1`. Run `lineage query-test` and `lineage collect --query` from Bash (Git Bash): Windows PowerShell 5.1 drops the double quotes inside a quoted query and splits it into words (in PowerShell, write each inner quote as `\"`). Both commands refuse a query with unbalanced parentheses or quotes, which is the usual sign of such a split.

**Register the MCP server** (`setup` installs skills only, not the MCP entry). Templates: `examples/claude-mcp.json`, `examples/codex-mcp.toml`; replace the executable path.

| Client | How |
| --- | --- |
| Claude Code | `claude mcp add --scope user snu-library -- /absolute/repo/.venv/bin/scholarly-access-agent mcp-server` |
| Codex | Copy the `examples/codex-mcp.toml` block into `~/.codex/config.toml`. Keep `default_tools_approval_mode = "approve"` (otherwise Codex asks approval for every MCP call and fails them in `codex exec` and automations) and `tool_timeout_sec = 300` (the 60 s default can cut off `download_pdf`). `add_domain` stays on `prompt`. |
| claude.ai | Upload the four ZIPs in `dist/` as account Skills: `snu-library-scholarly-access`, `research-lineage`, `research-topic-scout`, `research-pilot`. A cloud-only session needs a local MCP connection for local access. |

Restart clients after changing tools.

**HTML reports** need [Quarto](https://quarto.org) (bundles Pandoc and Typst; set `QUARTO_PATH` if it is not on PATH). Without it, `render-report` falls back to a built-in reportlab PDF and reports `quarto_unavailable`.

**SNU sign-in:** rerun the installer, or run `scripts/서울대 로그인.command` (macOS) for user-assisted sign-in. On Windows, if the visible window does not open with the bundled Chromium (application control can block it), add `--browser-channel chrome` (or `msedge`) to `scholarly-access-agent open-url <URL> --wait-for-login --headless false`. Passwords are never loaded or auto-entered; session files stay outside the repo, owner-only and unencrypted. Routine research is headless; only session renewal opens a window. When `doctor`, `download_pdf` or `discover_pdfs` finds the session expired, you get a desktop notification (Windows toast, macOS Notification Center, Linux `notify-send`; at most once per 30 min, `SNU_LOGIN_ALERT_INTERVAL` in seconds, `SNU_LOGIN_ALERT=0` to turn off) and the result carries `user_action_required` with the re-login command, which the agent passes on at once. Optional: `OPENALEX_API_KEY` raises the OpenAlex quota (read from the environment and the Windows user variable, never printed).

## Skills

| Skill | Use it when | What it produces |
| --- | --- | --- |
| `snu-library-scholarly-access` | Any paper search or literature review; the base for every other skill (access rules, version priority, evidence format, report) | Evidence records in `evidence/`, a Markdown report rendered to one HTML page (PDF on request), papers filed in ReadCube when available |
| `research-lineage` | Where a method or concept came from, how it branched, what is mainstream now (`lineage` mode); or the research flow of a topic, policy or phenomenon (`topic` mode, lanes = reader's questions) | `lineage.json`, an interactive flow map page, and a report chapter (stage table, trends, diagram) |
| `research-topic-scout` | Recommending topics, gaps or next projects from an existing review folder; novelty checks | `ideas/`: gap matrix, 5–8 question cards, novelty verdicts (overlap None to Exact) from closest prior work read in full text, feasibility, critique and pre-mortem, readiness gate, report; on request, an ARS socratic dialogue to refine one card and a weekly watch for competing preprints |
| `research-pilot` | Running review or topic recommendation end to end with little supervision, a dry run of the cost, or resuming a run | Routes to a playbook (`status`, `topics`, `lineage`, `novelty`, `calculation`), stops at most at two checkpoints with the recommended option first (or takes it automatically under `checkpoints: auto-recommend`), keeps a token budget, logs `run.jsonl` |

The `calculation` playbook turns a card or a paper's method into a calculation plan; nothing is submitted without the user's go-ahead. Settings and the user profile (compute, data, direction, horizon, exclusions) live in `<research root>/research-pilot.md`.

## How a run works

1. **Search.** Native web/academic search finds candidates; queries and sources are logged. Every review except a quick search then runs `lineage expand` on 3–5 central seeds: one hop of their references and citing papers, ranked by how many seeds each connects to, so papers the search missed are screened too. The expansion is saved as a small corpus, so plain reviews also test their main queries for precision, recall on a frozen gold set, novelty and anchor blocks (`lineage query-test --drop-blocks`) and check the era balance of what was read (`evidence coverage`). Lineage runs collect the larger OpenAlex neighbourhood and do the same on it.
2. **Resolve versions.** `resolve <DOI>` gives the Crossref record, Unpaywall open copies and ranked reading routes. Journal version first; preprint only as a labelled fallback.
3. **Read.** Text first: `read_url` for open-access HTML (outline, then terms, then sections); `download_pdf` + `read_pdf` for paywalled papers, page citations or figures. More than ~15 papers go to parallel reader sub-agents whose briefs open with the byte-identical reader pack (`pack reader`); readers write records to files and return at most 10 lines (file handback).
4. **Evidence records.** One record per paper: `access` (`fulltext_pdf`, `fulltext_html`, `excerpts`, `secondary`, `abstract_only`, `unavailable`), version read, criteria with locators, and every reportable number in `results[]` (value, range, unit, condition, page; `source_file` for local PDFs).
5. **Lint and labels.** `evidence lint` must pass; `evidence labels` derives 본문 확인 / 발췌 확인 / 인용 맥락만 / 초록만 확인 / 미확인. `refs check` compares records with Crossref by DOI and flags retracted papers and unverified journals (OpenAlex).
6. **Report with citation keys.** The report cites `[@larkin2014, p.9]` or `[@liang2023#k350]`; rendering turns them into "(Larkin 외, 2014 [5], p.9)" and fills a reference table with the version read and the derived label.
7. **Trace and verify.** `report trace` flags unknown keys, missing locators, numbers not in the cited records and uncited numbers in the summary; `evidence verify --write` re-reads each result's PDF page and records `verified_by`.
8. **Figures planned per question.** For each section (reader question) decide figure, table or neither in `figs/figures.json`; write `figs/<name>.fig.json` specs whose rows name evidence records, and draw them with `viz figure`. Literal numbers and mixed units are rejected; read depth shows in the marks, the page in the tooltip.
9. **Render — one page per topic folder.** `report combine <Topic> --render` merges every report the run wrote (review, topic recommendations, novelty reports, calculation plans) into `<Topic>.md` and renders the one `<Topic>.html` the user receives (a lone review is rendered as it is; `render-report` / MCP `render_report_pdf` renders any single Markdown file); `![caption](figs/x.html)` embeds the flow map or a chart. Check `missing_glyphs` and `warnings`, then open it.

## CLI reference

All commands are `scholarly-access-agent <command>`; `<command> -h` lists options.

| Area | Command | Purpose |
| --- | --- | --- |
| Setup | `setup` | Install the skills for the current Codex and Claude Code user |
| | `doctor` | Runtime and session presence; `--probe <URL>` checks validity with one temporary download |
| | `mcp-server` | Start the MCP server (`snu-library`) over stdio |
| | `add-domain` | Add a domain to the SNU proxy list |
| Access & reading | `check-url`, `proxy-url`, `open-url` | Proxy support check, proxied URL, open in the persistent profile |
| | `resolve` | DOI → Crossref record, open copies, ranked reading routes |
| | `read-url` | Text-first reading of open repositories (arXiv, PMC, Europe PMC, chemRxiv, bioRxiv, medRxiv; engineering: engrXiv, HAL, OSTI, NASA NTRS, ACL Anthology, CVF) |
| | `discover-pdfs`, `download-pdf`, `download-many` | Find PDF links; download one, or a JSONL batch in one browser context |
| | `read-pdf` | Page-grounded excerpts by `terms` or by `pages` (never both) |
| | `pack reader` | Print the reader pack byte for byte (`--check`: hash and size) |
| Evidence & reports | `evidence lint` / `labels` / `verify` / `coverage` | Check records, derive read-depth labels, re-check results on the PDF page, summarise the measured search and the era balance of what was read |
| | `refs check` | Compare records with Crossref by DOI (only DOIs are sent) |
| | `report trace` | Trace citation keys and numbers back to records |
| | `report combine` | Merge a topic folder's reports (`README.md`, `ideas/README.md`, `ideas/novelty-*.md`, `ideas/calc-*.md`) into `<Topic>.md`; `--render` makes the single `<Topic>.html` the user receives |
| | `render-report` | Markdown report → standalone HTML (`--format pdf` adds an A4 PDF) |
| Lineage | `lineage init` | Create the topic folder (`--no-lineage` for a plain review) |
| | `lineage expand` | One-hop snowballing for a plain review: references and citing papers of a few seeds, ranked by seed links, screened papers hidden; saves them as `data/corpus.json` for query tests |
| | `lineage seed`, `collect`, `analyze` | Seed candidates, citation neighbourhood, RPYS / clusters / SPC main path |
| | `lineage keywords`, `query-test`, `gold`, `log-search`, `mentions`, `adoption` | Build and test search vocabulary, freeze a gold set, log outside searches, count mentions and forward-only adoption |
| | `lineage links`, `quality`, `check`, `page`, `report-section` | Journal-first links, source quality of the boxes (retracted, not peer-reviewed, unverified journal, off-field, where each was found), validation and layout warnings, interactive page (`--embed`), report chapter |
| Figures | `viz figure` | A figure from an agent-written spec; every number from evidence results |
| | `viz effects`, `adoption`, `timeline` | Forest plot of results, adoption share by year, citations and RPYS spectrum |
| Cost | `cost estimate`, `record`, `report` | Dry-run estimate under a cap, ledger of measured stages, estimate vs measured with calibration |

**MCP tools** (`snu-library`, same implementation as the CLI; downloads always run headless):

| Tool | Purpose |
| --- | --- |
| `doctor` | Installation and session presence; `probe_url` checks that the session serves one subscription PDF |
| `check_url`, `proxy_url` | Proxy support and `open_access_text`; proxied URL |
| `read_url` | Open-access HTML as outline, term excerpts or whole sections |
| `discover_pdfs`, `download_pdf` | PDF candidates; open-repository PDFs directly, publisher PDFs through the SNU session |
| `read_pdf` | Page-grounded text by `terms` or `pages` |
| `render_report_pdf` | Finished Markdown → HTML page (PDF on request); reads only local files in the report folder |
| `add_domain` | Proxy domain list; only on explicit user request |

Per-publisher retrieval routes: `skills/snu-library-scholarly-access/references/publisher-routes.md`. Report layout and checks: `references/report-pdf.md` in the same skill.

A spent OpenAlex daily quota stops a lineage command with exit code 3; caches are kept, so rerunning resumes.

## Evidence honesty rules

- **Journal first.** Read the version of record before the arXiv/preprint; label every record with the version actually read and why a preprint was used.
- **Never bypass bot checks.** Publisher challenges are reported as `status: "blocked"`, `reason: "bot_challenge"`, separately from `login_required`; they are never solved or bypassed. Unchecked PDF endpoints are still tried.
- **Subscription access is not AI permission.** Elsevier (ScienceDirect) and Springer Nature subscription text must not be sent to an external AI even when the SNU session serves it: use an open copy or report the limitation. See the [SNU TDM page](https://lib.snu.ac.kr/find/databases_openaccess/tdm/).
- **Labels are derived, not typed.** The read-depth label comes from `access` and `read_mode` via `evidence labels`. Introduction or reference-list mentions never establish that a study used a method; retrieval failure never implies irrelevance; model-written web summaries are locators, not evidence.
- **Source quality is visible.** Records carry `venue_type`, `indexing` and `evidence_role`; verdicts rest on peer-reviewed full text, and conference abstracts, preprints and abstract-only items are shown as preliminary evidence (예비 근거).
- **Korean settings.** Questions about Korea add a KCI / RISS / DBpia / ScienceON route, KCI-listed journals first; authors in Hangul with the paper's romanisation.
- Scanned PDFs need OCR or visual review. `pages_scanned` reports search coverage, not pages fully reviewed.

## Models and cost

Every sub-agent gets its role's model and effort explicitly, from `skills/snu-library-scholarly-access/references/research-models.md` (overridable in `research-pilot.md`).

| Role | Does | Claude Code | Effort (Default / Deep) |
| --- | --- | --- | --- |
| `main` | plan, screen, choose versions, gap matrix, synthesize | the session (Opus recommended) | `high` / `xhigh` |
| `reader` | Tier 2–3 full-text reading, closest prior work | `opus` | `high` / `high` |
| `judge` | cards, novelty verdicts, feasibility, critique, inclusion | `opus` | `high` / `high` |
| `writer` | report from checked records | `opus` | `medium` / `medium` |
| `locator` | find candidates, fetch pages, check empty cells | `sonnet` | `low` / `medium` |

Codex sets only `reasoning_effort` per role. Small fast models are never used for reading or judgments that enter a report.

**Cost.** `cost estimate` gives tokens per stage and role for a playbook and preset, with the reduced counts that fit a cap; `cost record` appends measured stage tokens to `<research root>/.cost/ledger.jsonl`; `cost report` compares estimate and measurement and shows the calibration later estimates use.

**Prompt caching.** Caching matches identical prefixes only, so every reader brief opens with the unchanged output of `pack reader`. Launch order is staggered: send the first batch, wait for its first tool call, then launch the rest so they read the cache. Results come back through files, not the main context. Because every main-agent call re-reads the whole session, start runs in a fresh session; the pilot offers a handoff when the context passes ~100k tokens.

## Verify

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m pip check
```

CI uses synthetic fixtures and needs no SNU credentials. Before a GitHub upload, inspect staged files and history; exclude sessions, credentials, PDFs, reports and generated packages. Runtime data stays local even when the source repository is private.

## Provenance and licence

Based on https://github.com/onetwothr1/SNU-library-scholarly-access-skill at `cad5e9a5e9ab259642b5dee13d6022427e56bd03`. The upstream README declares MIT. The original MIT notice, including its copyright attribution, is retained in `LICENSE`, recovered verbatim from upstream commit `b5d7927` (it was absent at the review revision). No ownership claim is made over upstream code.

Adapted designs (MIT):
- `research-topic-scout` card fields and the readiness-gate idea: Galaxy-Dawn/claude-scholar `research-ideation`.
- `research-pilot` structure (entry skill, playbooks ending in a required-reply list, shared worker rules, one model sheet): michael-denyer/pstack-claude.

Bot-check detection markers are adapted from SleepingDawn/paper_download.

Design references (consulted 2026-11-17):
- https://github.com/K-Dense-AI/scientific-agent-skills/tree/main/skills/literature-review
- https://github.com/K-Dense-AI/scientific-agent-skills/tree/main/skills/research-lookup
- https://liyux3.github.io/scholar-mcp/research-workflows/
- https://github.com/Future-House/paper-qa
- https://github.com/anthropics/skills/tree/main/skills/pdf (consulted 2026-11-18; reportlab Platypus rendering, sub/superscript markup rule)
- https://github.com/anthropics/skills/tree/main/skills/theme-factory (consulted 2026-11-18; one palette and font pairing, contrast first)

Their workflow and rendering patterns informed original code and instructions here; their code and text were not vendored.
