# Search vocabulary and widening (step 5)

Part of research-lineage. Read this before building queries.

The seed's citation neighbourhood uses the seed camp's words. The same concept often has other names in older work, other fields and other camps, and those are exactly where missing branches live. So the vocabulary comes from reading, not only from tags.

1. **Concepts.** Split the topic into 2–3 concepts that must co-occur, e.g. [long-range electrostatics] AND [machine-learned potential].
2. **Terms per concept**, from four sources; record each in `vocabulary` with its source:
   - (a) `scholarly-access-agent lineage keywords data '<context>' 15 5 '<focus regex>'`: OpenAlex tags ranked by field fit.
   - (b) Terms the reviews use in section titles and related-work paragraphs.
   - (c) Abbreviations and their spelled-out forms (QEq / charge equilibration).
   - (d) Older or other-field names found in the reviews' oldest references (electronegativity equalization, fluctuating charge).
   - Noise: senses of a term outside the topic, seen in test results (charge transfer → photovoltaic, battery). These go after NOT.
3. **Gold set**: the papers a good search must find, chosen **independently of the lineage you are building**, e.g. the papers on the topic cited by two independent reviews. Precursors from before the field are found through citations, not search; leave them out. Freeze it before testing queries: `scholarly-access-agent lineage gold freeze data --from-file gold.txt --note 'cited by Review A and Review B'` (one OpenAlex ID or DOI per line, `#` comments allowed; DOIs are resolved through OpenAlex and unresolved ones are listed). It writes `data/gold.json`, which `query-test` then uses by default and announces as `gold: independent (N)`; `--gold-file FILE` names another one. `--gold-from-lineage lineage.json` still works but prints `gold: from curated lineage (circular)`: recall on papers you chose yourself proves little. `--gold W1,W2,...` passes IDs directly. The gold source is logged with each query and named in the report's method section.
4. **Test** each concept-block query: `scholarly-access-agent lineage query-test data '(A1 OR A2 OR "a 3") AND (B1 OR B2) NOT (n1 OR n2)' --gold-from-lineage lineage.json --focus '<regex>' --label '<name>'`. It logs to `data/queries.json`, which the page shows. Test all concept-block variants in one call: pass several queries and one `--label` per query. They are fetched in parallel under a shared rate limit, then reported and logged in order, so strategy recall accumulates as if run one by one. A summary table closes the run.
   - Precision = share of the top 100 that cite a core paper of the field (`data/core.json`). Below ~60%: add NOT terms or narrow a block. Skim the listed titles too.
   - A missed gold paper flagged "has abstract": add the wording it uses. Flagged "no abstract": no query can reach it; rely on citations.
   - Novelty under 10% is flagged SATURATED: variations of this query add little. After every run, if no logged query is saturated, query-test prints `UNSATURATED: no query reached novelty < 10% (last query novelty X%)`; `lineage check` warns `unsaturated_search` and the report's method section states "검색은 포화에 이르지 않았다 (마지막 질의 신규 비율 X%)". Do not hide it: stopping at the query cap is a result to report.
5. **Stop** when strategy recall (union of all logged queries) covers ~80% of the gold set and the last query is saturated, or after ~6 queries (then the search is reported as unsaturated).
6. **Widen** with the queries whose precision passed: `scholarly-access-agent lineage collect data_x <SEED> --base data --query '<q1>' --query '<q2>' --per-keyword 60`, optionally `--ancestors 6 --focus '<regex>'`. Capped lists (`--keywords`, `--per-ancestor`, relevance fallback) take half most-cited and half newest, so recent papers that do not cite the seed still enter; check the newest years in `analysis.txt` (forward by year). Then `scholarly-access-agent lineage analyze data_x 2` and set `meta.expanded_dir`.

Field fit cannot judge pre-field precursors or very new preprints whose reference lists OpenAlex has not filled; judge those by reading.

## Searches outside OpenAlex

Log every web, arXiv, Google Scholar or KCI search that a claim rests on, above all "no paper does X":
`scholarly-access-agent lineage log-search . --engine arXiv --query 'amorphous silica thermal conductivity MACE' --date 2026-11-20 --hits 14 --kept 'arXiv:2501.01234,W4400201232' --note 'none uses a universal MLIP for a-SiO2'`.
It appends to `data/searches.json` (ids `search#1`, ...); the report's method section and the page list engine, query, date, hits and what was kept (empty `--kept` = nothing relevant). `lineage check` warns `not_found_without_search_log` when the verdict or limits claim "찾지 못"/"not found" and no search is logged. OpenAlex records now also carry `language` (missing in older corpora).

## Mainstream share: `lineage adoption`

A "current mainstream" claim needs a share whose denominator was not chosen by our own search words:
`scholarly-access-agent lineage adoption data_x --scope 'silica|SiO2' --method 'machine.learn|neural network|DeePMD|(?-i:\bNEP\b|\bGAP\b|MLIP)' --lineage lineage.json [--since 2018] [--list]`.

- Denominator: **forward (citing) papers only** (`_role` contains `forward`) whose title + abstract match `--scope`; records that entered only through keyword/query or ancestor widening, and the founder works themselves, are excluded. Numerator: those also matching `--method`. Counts and shares per year; papers without an abstract match on the title only, so counts are lower bounds.
- Self-citation: share of numerator papers sharing an OpenAlex author ID with a founder work (`--founders W1,W2`, else `meta.seed_ids` of `--lineage`, else the corpus seeds).
- Matching is case-insensitive: write acronyms that are also words case-sensitively with `(?-i:...)` (`GAP` otherwise matches "band gap").
- Each run is appended to `adoption.json` in that data folder with its regexes, roles, counts and date, and printed as `adoption#n`; cite that id in the verdict ("2025년 3/13편, adoption#2"). The report's method section lists the logged runs.
- `lineage mentions` (field = forward + widened papers) also logs its regex and counts to `mentions.json` (`mentions#n`) and says when its denominator includes widened-only papers; do not use it for a mainstream share.

