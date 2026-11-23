# Research workflow
For a quick search, agree with the request's scope and use a small shortlist. For trends, distinguish established directions from recent individual claims. For systematic reviews, record database coverage, full queries, date, counts and exclusion reasons; ranked web search alone is not exhaustive.

Log each query, source, date, and candidate DOI/arXiv ID/URL. Normalize DOI case and resolver prefixes. Merge exact identifiers; title similarity alone needs author/year verification. Keep preprint versions and publication versions linked but separate; do not silently transfer page or section evidence between versions.

**Version priority (journal first).** If a peer-reviewed journal version exists, it is the version to read and cite: try PMC/Europe PMC (`read_url`), then the publisher page, open access or subscription (`download_pdf` → `read_pdf`), subject to access-and-auth.md; the per-publisher route is in publisher-routes.md. Fall back to the arXiv/preprint only when the journal version is unavailable, access-restricted, or retrieval fails, and record the reason (`access restriction` vs `tool error`). A preprint may still be read to supplement content missing from the journal version (e.g., an appendix); mark such evidence as preprint. Sub-agents must follow the same priority and report which version they read.

## Source quality

- **What carries a conclusion.** Summary bullets, verdicts and the current answers of a topic report rest on peer-reviewed items (`venue_type` journal or full conference paper in fields where proceedings are refereed), read in full text. Conference abstracts and talks, preprints, working papers, theses and anything read only as an abstract may appear, but only marked **예비 근거** (preliminary) in their own row or block, never alone behind a number in the summary.
- **Recent work.** Show the newest studies (last ~2 years) explicitly, because readers want them, in a "최신·예비 근거" block when they are not yet peer-reviewed or were read only as abstracts. Do not drop a strong recent journal article to make room for it, and do not promote an abstract to fill the "recent" slot.
- **Role.** Only `empirical`/`model`/`review` items answer a question. `context` items (governance, history, critique) go in a context paragraph, not in an evidence table.
- **Korean setting.** When the question concerns Korea (a Korean city, policy or dataset), search Korean sources as their own route: KCI (kci.go.kr), RISS, DBpia and ScienceON, with Korean keywords, and prefer KCI-listed (등재/등재후보) journal articles. A conference talk or proceedings abstract is used only when no journal article covers the point, marked 예비 근거. Write titles and authors as printed (Hangul) with the romanisation in parentheses.
- **Metadata check before delivery.** Run `scholarly-access-agent refs check <topic folder>/evidence` (Crossref by DOI): it compares title, year, first author, venue and item type with each record and suggests `venue_type`. Fix every mismatch; records without a DOI (many Korean items) are listed for a manual KCI/RISS check. It also asks OpenAlex about each DOI: a `retracted` record is not evidence (remove it, or say it was retracted where it must be mentioned), and a journal flagged with h-index < 10 and 2-year citedness < 0.5 needs a manual check of its indexing (Scopus/WoS) and editorial board before anything rests on it; young journals look like this too, so it is a prompt, not a verdict. Papers found only by web search get the same check; they are where predatory or hijacked journals most often come in.

## Tiers and budgets
State the budget at the start (which preset, with its numbers) and report what was actually spent.

| Tier | Purpose | Tool | Default (trend review) | Deep | Context cost |
| --- | --- | --- | --- | --- | --- |
| 1 Screen | relevance from metadata | native search, publisher/arXiv abstract pages | 50–100 candidates | 150–250 candidates | ~100–300 tokens each |
| 1b Expand | papers the search missed | `lineage expand` on central seeds | 3–5 seeds, top 40 | 5–8 seeds, top 80 | ~100–300 tokens each |
| 2 Text | locate and read evidence | `read_url` outline → `terms` → `sections` | 15–30 papers | 40–60 papers | ~1–4k tokens each |
| 3 PDF | paywalled, page citation, broken HTML | `download_pdf` → `read_pdf` | ≤ 10 papers | ≤ 30 papers | ~2–6k tokens each |
| 4 Figures | figure decides the claim | `image_url` / page image | ≤ 5 figures | ≤ 15 figures | ~1–2k tokens each |

**Choosing the preset.** Use **Deep** when the user asks for maximum or exhaustive effort in any wording ("최대로", "철저히", "깊게", "빠짐없이", "max effort", "thorough", "exhaustive"); otherwise **Default**. Numbers the user gives override either preset, tier by tier. Under Deep:
- Tier 2–3 reading always goes to sub-agents (below), whatever the count.
- Before recording a paper as `초록만 확인` or `미확인` after `blocked`, `login_required`, `no_pdf_found` or `unsupported_domain`, try every open-copy route in publisher-routes.md (PMC/Europe PMC, HAL, repository, arXiv/preprint).
- Stop on three, not two, successive query refinements without new relevant evidence (Searching and stopping).

**Citation expansion (Tier 1b).** Ranked web search misses central papers that use other wording and favours what is visible on the web. In every review except a quick search, once Tier 1 has a first shortlist, pick 3–5 seeds (Deep: 5–8): the most central peer-reviewed papers or reviews for the question, not simply the most cited. Run

`scholarly-access-agent lineage expand <seed DOIs> --known <topic>/evidence --since <first year in scope> --out <topic>/data/expansion.json` (add `--known` for any other file listing screened DOIs, `--top 80` under Deep)

It takes one hop: each seed's references and up to 40 of its citing papers (half most-cited, half newest), ranked by `score` = `links` (how many seeds a paper connects to) plus a small citations-per-year bonus; already screened papers (DOI, arXiv ID, OpenAlex ID or title) are hidden. Screen the new rows like other Tier 1 candidates: `links` ≥ 2 marks a paper several seeds depend on or build on; a high `cites_per_year` among citing papers marks recent follow-up work. Log the run as a query (source `OpenAlex expand`, seeds, date), and in the report say how many shortlisted papers came only from expansion. Skip it for a quick factual search; if OpenAlex is unavailable (exit code 3 = daily quota), say so and continue. Questions about origins and branches use `research-lineage`, which collects a much larger citation corpus.

Deep reads more of what is accessible; it never widens access. Bot checks, `login_required` and publisher AI-use restrictions (access-and-auth.md) apply unchanged.

Keep `max_chars` small (4–8k) for term searches and raise it only for the sections you must read whole. Prefer one `sections` call over repeated term calls once you know where the evidence is.

## Delegating reading to sub-agents
When the Tier 2–3 list exceeds about 15 papers, split it into batches of 4–6 papers per sub-agent. Before dispatching, run the session preflight (`doctor` with `probe_url`, publisher-routes.md) so subscription papers do not end at the abstract, and `scholarly-access-agent resolve <DOI>` for each paper so the brief carries its route instead of a locator agent finding it.

**Brief layout (prompt caching).** Caching matches identical prompt prefixes only, so every brief has the same opening bytes:
1. the output of `scholarly-access-agent pack reader`, unchanged (same text, same order, nothing inserted);
2. one fixed line of shared task context (question and criteria — identical across the batches of a run);
3. last, the part that differs: this batch's papers with their `resolve` routes, output folder, allowance.

Readers then need no other skill file, and every brief after the first reuses the cached prefix.

**Launch order.** A cache entry is readable only once the first request using it has started responding; briefs sent at the same moment all pay in full. Launch the first batch, wait until it has made its first tool call, then launch the rest together.

**Handback through files.** Readers write their evidence records into `<topic>/evidence/` and return at most 10 lines (paths, counts, blocked items). The main agent reads the records through `evidence lint`, `evidence labels` and `report trace`, not by pasting them into its context: everything in the main context is re-read on every later call. Sub-agents must not write the synthesis. The main agent merges records, resolves version conflicts, spot-checks the 3–5 numbers the conclusion rests on (`scholarly-access-agent evidence verify <topic folder> --write` for records with a local `source_file`; otherwise `read_url`/`read_pdf`, noted in the record's `verified_by`), then writes the synthesis with citation keys (report-pdf.md) and runs `report trace`. Sub-agents follow the same access rules; delegation never relaxes them.

## Models and reasoning effort
Sub-agent judgments (is this a method the study used, which version was read) become report evidence, and the main agent re-checks only a few numbers, so readers run as strong as the main agent.

Every agent's model and effort come from [research-models.md](research-models.md): the main agent is `main`, Tier 2–3 readers are `reader` (opus, `high`), and agents that only find candidates, resolve DOIs, find open copies or fetch pages are `locator` (sonnet, `medium`). Pass the row explicitly at every spawn.

## Searching and stopping
Search question variants and competing results. For trends use current-year/preprint coverage alongside recent peer-reviewed evidence. Screen titles/abstracts, then inspect the shortlist's main Methods/Results and relevant supplements. Record what was actually read. Term results are locators, not a quality score.

Stop at the requested scope/budget or when two successive query refinements (three under the Deep preset) yield no new relevant evidence. Keep plausible unread papers explicitly marked. Never equate inability to access with exclusion for scientific reasons.

Synthesize by supported theme, limitations and conflicting evidence. Link original sources and identify preprints. For comparisons hold question, cutoff date and candidate budget fixed; distinguish coverage, body support, corrections and runtime. A single comparison is not a general accuracy benchmark.
