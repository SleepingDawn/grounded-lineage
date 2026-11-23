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
3. **Gold set**: the papers a good search must find: field method papers named as key by the reviews. Precursors from before the field are found through citations, not search; leave them out. Before `lineage.json` exists, pass IDs with `--gold W1,W2,...`.
4. **Test** each concept-block query: `scholarly-access-agent lineage query-test data '(A1 OR A2 OR "a 3") AND (B1 OR B2) NOT (n1 OR n2)' --gold-from-lineage lineage.json --focus '<regex>' --label '<name>'`. It logs to `data/queries.json`, which the page shows. Test all concept-block variants in one call: pass several queries and one `--label` per query. They are fetched in parallel under a shared rate limit, then reported and logged in order, so strategy recall accumulates as if run one by one. A summary table closes the run.
   - Precision = share of the top 100 that cite a core paper of the field (`data/core.json`). Below ~60%: add NOT terms or narrow a block. Skim the listed titles too.
   - A missed gold paper flagged "has abstract": add the wording it uses. Flagged "no abstract": no query can reach it; rely on citations.
   - Novelty under 10% is flagged SATURATED: variations of this query add little.
5. **Stop** when strategy recall (union of all logged queries) covers ~80% of the gold set and the last query is saturated, or after ~6 queries.
6. **Widen** with the queries whose precision passed: `scholarly-access-agent lineage collect data_x <SEED> --base data --query '<q1>' --query '<q2>' --per-keyword 60`, optionally `--ancestors 6 --focus '<regex>'`. Capped lists (`--keywords`, `--per-ancestor`, relevance fallback) take half most-cited and half newest, so recent papers that do not cite the seed still enter; check the newest years in `analysis.txt` (forward by year). Then `scholarly-access-agent lineage analyze data_x 2` and set `meta.expanded_dir`.

Field fit cannot judge pre-field precursors or very new preprints whose reference lists OpenAlex has not filled; judge those by reading.
