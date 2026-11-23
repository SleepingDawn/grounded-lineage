# Search vocabulary and widening (step 5)

Part of research-lineage. Read this before building queries.

The seed's citation neighbourhood uses the seed camp's words. The same concept often has other names in older work, other fields and other camps, and those are exactly where missing branches live. So the vocabulary comes from reading, not only from tags.

1. **Concepts by what the work does, not by the topic's name.** Split the topic into 2–3 concepts that must co-occur, each described by its function: what is found, measured or computed, with what, for what. E.g. [genome editing without double-strand breaks] AND [single-base change] rather than only "base editing"; [rare-event discovery] AND [learned energy model] AND [long-time evolution] rather than only one method's name. A topic's name is the vocabulary of the camp that coined it; newer work and neighbouring communities often do the same thing without using it. Keep the name as one synonym inside its block, never as a block on its own.
   - Test the concepts **in pairs** as well as all together: work that does two of the three things is often where a new branch starts.
2. **Terms per concept**, from four sources; record each in `vocabulary` with its source:
   - (a) `scholarly-access-agent lineage keywords data '<context>' 15 5 '<focus regex>'`: OpenAlex tags ranked by field fit.
   - (b) Terms the reviews use in section titles and related-work paragraphs, and the terms in the titles of the newest papers you already hold.
   - (c) Abbreviations and their spelled-out forms (QEq / charge equilibration, DiD / difference-in-differences, ABE / adenine base editor).
   - (d) Older or other-field names found in the reviews' oldest references (electronegativity equalization; natural experiment).
   - Noise: senses of a term outside the topic, seen in test results (charge transfer → photovoltaic; "ART" → Art Nouveau; "editing" → copy editing). These go after NOT.
3. **Gold set**: the papers a good search must find, chosen **independently of the lineage you are building**, e.g. the papers on the topic cited by two independent reviews. Precursors from before the field are found through citations, not search; leave them out. Freeze it before testing queries: `scholarly-access-agent lineage gold freeze data --from-file gold.txt --note 'cited by Review A and Review B'` (one OpenAlex ID or DOI per line, `#` comments allowed; DOIs are resolved through OpenAlex and unresolved ones are listed). It writes `data/gold.json`, which `query-test` then uses by default and announces as `gold: independent (N)`; `--gold-file FILE` names another one. `--gold-from-lineage lineage.json` still works but prints `gold: from curated lineage (circular)`: recall on papers you chose yourself proves little. `--gold W1,W2,...` passes IDs directly. The gold source is logged with each query and named in the report's method section.
4. **Test** each concept-block query: `scholarly-access-agent lineage query-test data '(A1 OR A2 OR "a 3") AND (B1 OR B2) NOT (n1 OR n2)' --gold-from-lineage lineage.json --focus '<regex>' --label '<name>'`. It logs to `data/queries.json`, which the page shows. Test all concept-block variants in one call: pass several queries and one `--label` per query. They are fetched in parallel under a shared rate limit, then reported and logged in order, so strategy recall accumulates as if run one by one. A summary table closes the run.
   - Precision = share of the top 100 that cite a core paper of the field (`data/core.json`). Below ~60%: add NOT terms or narrow a block. Skim the listed titles too.
   - A missed gold paper flagged "has abstract": add the wording it uses. Flagged "no abstract": no query can reach it; rely on citations.
   - Novelty under 10% is flagged SATURATED: variations of this query add little. After every run, if no logged query is saturated, query-test prints `UNSATURATED: no query reached novelty < 10% (last query novelty X%)`; `lineage check` warns `unsaturated_search` and the report's method section states "검색은 포화에 이르지 않았다 (마지막 질의 신규 비율 X%)". Do not hide it: stopping at the query cap is a result to report.
   - **Anchor check**: add `--drop-blocks` (with `--focus '<topic regex>'`). Each query of two or more AND blocks is also run with one block dropped at a time; a block whose removal reveals many on-topic, in-field works not yet collected is flagged `ANCHOR` (logged to `data/anchor_checks.json`, not to `queries.json`). Read the listed examples: if they are the topic under other words, the block was one camp's name for the concept, so rewrite it by function and test again; if they are off-topic, the block defines the topic and stays. "Too broad without it" means the other blocks alone are too generic to judge; make them more specific first. In-field is decided by citations, so the check works in any field.
   - The gold covers certain years; when a quarter of the in-field results fall outside them, `query-test` says so (`gold era`). Recall then says nothing about those years: add their key papers to the gold.
5. **Stop** when strategy recall (union of all logged queries) covers ~80% of the gold set and the last query is saturated, or after ~6 queries (then the search is reported as unsaturated).
6. **Widen** with the queries whose precision passed: `scholarly-access-agent lineage collect data_x <SEED> --base data --query '<q1>' --query '<q2>' --per-keyword 60`, optionally `--ancestors 6 --focus '<regex>'`. Each `--query` takes its most relevant works plus `--recent` newest ones on top (default half of `--per-keyword`), so recent papers enter without pushing out the classical ones; other capped lists (`--keywords`, `--per-ancestor`) take half most-cited and half newest. Check the newest years in `analysis.txt` (forward by year). Then `scholarly-access-agent lineage analyze data_x` and set `meta.expanded_dir`.
7. **A route that needs no words**: run `lineage expand` on a recent key paper of each lane as well as on the seeds. Papers that cite them are found whatever vocabulary they use, which catches what every query missed.

Field fit cannot judge pre-field precursors or very new preprints whose reference lists OpenAlex has not filled; judge those by reading.

## Searches outside OpenAlex

Log every web, arXiv, Google Scholar or KCI search that a claim rests on, above all "no paper does X":
`scholarly-access-agent lineage log-search . --engine arXiv --query 'base editing off-target whole-genome sequencing in vivo' --date 2026-11-20 --hits 14 --kept 'arXiv:2501.01234,W4400201232' --note 'none measures off-target edits in vivo'`. Log each query on its own line; one entry that stands for "about 30 searches" cannot be reproduced or audited.
It appends to `data/searches.json` (ids `search#1`, ...); the report's method section and the page list engine, query, date, hits and what was kept (empty `--kept` = nothing relevant). `lineage check` warns `not_found_without_search_log` when the verdict or limits claim "찾지 못"/"not found" and no search is logged. OpenAlex records now also carry `language` (missing in older corpora).

## Mainstream share: `lineage adoption`

A "current mainstream" claim needs a share whose denominator was not chosen by our own search words:
`scholarly-access-agent lineage adoption data_x --scope '<object regex>' --method '<method regex>' --lineage lineage.json [--since 2018] [--list]`, e.g. `--scope 'minimum wage' --method 'difference.in.differences|synthetic control|(?-i:\bDiD\b)'` or `--scope 'silica|SiO2' --method 'machine.learn|neural network|(?-i:\bNEP\b|\bGAP\b|MLIP)'`.

- Denominator: **forward (citing) papers only** (`_role` contains `forward`) whose title + abstract match `--scope`; records that entered only through keyword/query or ancestor widening, and the founder works themselves, are excluded. Numerator: those also matching `--method`. Counts and shares per year; papers without an abstract match on the title only, so counts are lower bounds.
- Self-citation: share of numerator papers sharing an OpenAlex author ID with a founder work (`--founders W1,W2`, else `meta.seed_ids` of `--lineage`, else the corpus seeds).
- Matching is case-insensitive: write acronyms that are also words case-sensitively with `(?-i:...)` (`GAP` otherwise matches "band gap").
- Each run is appended to `adoption.json` in that data folder with its regexes, roles, counts and date, and printed as `adoption#n`; cite that id in the verdict ("2025년 3/13편, adoption#2"). The report's method section lists the logged runs.
- `lineage mentions` (field = forward + widened papers) also logs its regex and counts to `mentions.json` (`mentions#n`) and says when its denominator includes widened-only papers; do not use it for a mainstream share.

