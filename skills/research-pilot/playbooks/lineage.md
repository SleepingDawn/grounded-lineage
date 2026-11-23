### Lineage

**Trace where a concept came from, how it branched and what is mainstream now — citation data finds candidates, reading decides.**

Exit: the lineage chapter and page are rendered (and, when asked, merged into a review report), or the budget stop fired (state saved for resume).

1. **Set up.** Topic folder as in status step 1, but with `scholarly-access-agent lineage init <Topic>` (keeps `data/` and `lineage.json`). Start `run.jsonl` (playbook `lineage`). Check the session against `main`.
2. **Seed and plan.** research-lineage step 1 (seed: the paper that defined the concept, journal record first). Reading budget from research-lineage "Reading plan" (standard unless the user said otherwise); a lineage that is a chapter of a review uses the review's preset.
3. **Estimate.** OpenAlex steps cost no model tokens; reading does. `scholarly-access-agent cost estimate --playbook status --screened 0 --read <planned papers> --pdf <planned PDFs> --figures 0 …` with the remaining limit and cap per [cost.md](../references/cost.md). Record OpenAlex-only steps under `plan_screen` (context-delta).
4. **Checkpoint ①.** Show: seed(s) with why, reading plan and budget, estimate, cap, model rows. Option 1 (recommended): this seed and plan (or the reduced reading list when over the cap). Alternatives: another seed candidate from `lineage seed`; a narrower concept. Dry run ends here.
5. **Collect, analyze, read, widen, read again, curate, links, deliver** — research-lineage steps 2–10, readers with the `reader` row, overlapping the steps as that skill's "Keeping it fast" says. Record stage costs (`read` per batch; `synthesize` for curation and delivery); apply the budget rule before each reading batch.
6. **Close.** `scholarly-access-agent cost report --run <id>`; method note with estimated vs measured and the checkpoint choice; `run.jsonl` `event: done`. Offer in one line: topic recommendation from this lineage (topics playbook; the lineage feeds its gap matrix).

Reply: seed(s); lanes and the current default in one line each; papers read in full text / abstract-only; contested claims and both sides; estimated vs measured tokens; checkpoint choice; chapter, page and report paths.
