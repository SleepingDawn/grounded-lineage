### Status review

**Find what is known, from full text, inside the budget.**

Exit: the report is rendered, or the budget stop fired (state saved for resume).

When the topics playbook runs this one as its first part, it owns steps 1–3 and 7 (one run, one log, one estimate, one checkpoint ①); run only steps 4–6 here and log them as `status.4`–`status.6`.

1. **Set up.** Research root: `SNU_RESEARCH_ROOT` (default `~/Documents/research`). Topic folder: short English words joined by hyphens (e.g. `MLIP-trends-2026`). A folder of that name already exists → reuse it and move its old `README.md` into `archive/` before writing a new one. `scholarly-access-agent lineage init <Topic> --no-lineage`. Start `<Topic>/run.jsonl` (`event: start`, playbook `status`). Check the session against `main` in research-models.md; say once if it differs.
2. **Plan and estimate.** Question, dates, inclusion criteria, preset (Default; Deep for "최대로", "철저히" and similar; user numbers override). Remaining limit and `scholarly-access-agent cost estimate --playbook status …` per [cost.md](../references/cost.md).
3. **Checkpoint ①.** Show: question and criteria, the report outline (topic request: the 3–5 reader questions that will be the sections, per report-pdf.md; method request: the lineage or trend structure), preset and counts, estimate by role, cap, model rows. Option 1 (recommended): the plan as estimated, or the reduced budget when over the cap. Alternatives: the other preset; a narrower question. Dry run ends here.
4. **Screen** (Tier 1, `main`): snu-library steps 1–2. `locator` agents look up journal versions and identifiers for the shortlist; `main` decides which version counts. Record the stage cost.
5. **Read** (Tier 2–3, `reader` agents in batches of 4–6, brief per snu-library "Delegating reading"; each brief names its papers, its PDF allowance and its route). Evidence records go into `evidence/`. Record the stage cost after each batch; apply the budget rule before the next batch.
6. **Synthesize** (`main`): merge records, resolve versions, spot-check the 3–5 numbers the conclusion rests on, plan the figures per question (`figs/figures.json`, report-pdf.md) and draw them with `viz figure`, write `README.md` in the user's language; render with `render_report_pdf` (HTML by default); file papers in ReadCube; add the row to `<research root>/README.md`.
7. **Close.** `scholarly-access-agent cost report --run <id>`; put estimated vs measured and the checkpoint choice (user or auto) in the report's method note; `run.jsonl` `event: done`.

Reply: preset and counts actually spent; papers read in full text / abstract-only / unread; the main findings with reference numbers; estimated vs measured tokens; checkpoint choice (user or auto); report path.
