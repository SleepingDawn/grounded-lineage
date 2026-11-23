# Research workflow
For a quick search, agree with the request's scope and use a small shortlist. For trends, distinguish established directions from recent individual claims. For systematic reviews, record database coverage, full queries, date, counts and exclusion reasons; ranked web search alone is not exhaustive.

Log each query, source, date, and candidate DOI/arXiv ID/URL. Normalize DOI case and resolver prefixes. Merge exact identifiers; title similarity alone needs author/year verification. Keep preprint versions and publication versions linked but separate; do not silently transfer page or section evidence between versions.

**Version priority (journal first).** If a peer-reviewed journal version exists, it is the version to read and cite: try PMC/Europe PMC (`read_url`), then the publisher page, open access or subscription (`download_pdf` → `read_pdf`), subject to access-and-auth.md; the per-publisher route is in publisher-routes.md. Fall back to the arXiv/preprint only when the journal version is unavailable, access-restricted, or retrieval fails, and record the reason (`access restriction` vs `tool error`). A preprint may still be read to supplement content missing from the journal version (e.g., an appendix); mark such evidence as preprint. Sub-agents must follow the same priority and report which version they read.

## Tiers and budgets
State the budget at the start (which preset, with its numbers) and report what was actually spent.

| Tier | Purpose | Tool | Default (trend review) | Deep | Context cost |
| --- | --- | --- | --- | --- | --- |
| 1 Screen | relevance from metadata | native search, publisher/arXiv abstract pages | 50–100 candidates | 150–250 candidates | ~100–300 tokens each |
| 2 Text | locate and read evidence | `read_url` outline → `terms` → `sections` | 15–30 papers | 40–60 papers | ~1–4k tokens each |
| 3 PDF | paywalled, page citation, broken HTML | `download_pdf` → `read_pdf` | ≤ 10 papers | ≤ 30 papers | ~2–6k tokens each |
| 4 Figures | figure decides the claim | `image_url` / page image | ≤ 5 figures | ≤ 15 figures | ~1–2k tokens each |

**Choosing the preset.** Use **Deep** when the user asks for maximum or exhaustive effort in any wording ("최대로", "철저히", "깊게", "빠짐없이", "max effort", "thorough", "exhaustive"); otherwise **Default**. Numbers the user gives override either preset, tier by tier. Under Deep:
- Tier 2–3 reading always goes to sub-agents (below), whatever the count.
- Before recording a paper as `초록만 확인` or `미확인` after `blocked`, `login_required`, `no_pdf_found` or `unsupported_domain`, try every open-copy route in publisher-routes.md (PMC/Europe PMC, HAL, repository, arXiv/preprint).
- Stop on three, not two, successive query refinements without new relevant evidence (Searching and stopping).

Deep reads more of what is accessible; it never widens access. Bot checks, `login_required` and publisher AI-use restrictions (access-and-auth.md) apply unchanged.

Keep `max_chars` small (4–8k) for term searches and raise it only for the sections you must read whole. Prefer one `sections` call over repeated term calls once you know where the evidence is.

## Delegating reading to sub-agents
When the Tier 2–3 list exceeds about 15 papers, split it into batches of 4–6 papers per sub-agent and run batches in parallel. Before dispatching, run the session preflight (`doctor` with `probe_url`, publisher-routes.md) so subscription papers do not end at the abstract. Give each sub-agent: the question, the criteria from dft-mlip.md (or the task's own), the paper identifiers and the route from publisher-routes.md for each, the tier rules above, and the instruction to return only evidence records in evidence-format.md (JSON, ≤ 300 words per paper) with section names or PDF pages. Sub-agents must not write the synthesis. The main agent merges records, resolves version conflicts, spot-checks the 3–5 numbers the conclusion rests on with `read_url`/`read_pdf`, then writes the synthesis. Sub-agents follow the same access rules; delegation never relaxes them.

## Models and reasoning effort
Sub-agent judgments (is this a method the study used, which version was read) become report evidence, and the main agent re-checks only a few numbers, so readers run as strong as the main agent.

| Role | Claude Code | Codex | Effort: Default / Deep |
| --- | --- | --- | --- |
| Main agent (plan, screen, resolve versions, synthesize) | Opus | the session model | `high` / `xhigh` |
| Reading sub-agents (Tier 2–3) | Agent tool `model: "opus"`, `effort: "high"` | `spawn_agent` with `reasoning_effort: "high"`, no model override | `high` / `high` |

- Pass the sub-agent values explicitly at every spawn; never rely on the client default. Never use small fast models (Haiku, `*-luna` and similar) for Tier 2–3 reading.
- The main agent cannot change its own model or effort. If the session runs below its row (for example Deep on `medium`), say so once at the start, with the recommended setting, and continue.

## Searching and stopping
Search question variants and competing results. For trends use current-year/preprint coverage alongside recent peer-reviewed evidence. Screen titles/abstracts, then inspect the shortlist's main Methods/Results and relevant supplements. Record what was actually read. Term results are locators, not a quality score.

Stop at the requested scope/budget or when two successive query refinements (three under the Deep preset) yield no new relevant evidence. Keep plausible unread papers explicitly marked. Never equate inability to access with exclusion for scientific reasons.

Synthesize by supported theme, limitations and conflicting evidence. Link original sources and identify preprints. For comparisons hold question, cutoff date and candidate budget fixed; distinguish coverage, body support, corrections and runtime. A single comparison is not a general accuracy benchmark.
