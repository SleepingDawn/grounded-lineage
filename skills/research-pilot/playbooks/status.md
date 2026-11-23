### Status review

**Find what is known, from full text, inside the budget.**

Exit: the report is rendered, or the budget stop fired (state saved for resume).

1. **Set up.** Topic folder name like the existing ones; `scholarly-access-agent lineage init <Topic> --no-lineage`. Start `run.jsonl` (`event: start`, playbook `status`). Check the session against `main` in research-models.md; say once if it differs.
2. **Plan and estimate.** Question, dates, inclusion criteria, preset (Default; Deep for "최대로", "철저히" and similar; user numbers override). Read plan limits (`get_usage` when available) and run `cost estimate --playbook status` with `--remaining-pct` (and `--cap-pct` from settings). Over the cap → the recommendation is the `reduced` budget.
3. **Checkpoint ①.** Show: question and criteria, preset and counts, token estimate by role (plan-% if calibrated), cap, model rows. Option 1 (recommended): the plan as estimated, or the reduced budget when over the cap. Alternatives: the other preset; a narrower question. Dry run ends here.
4. **Screen** (Tier 1, `main`): snu-library steps 1–2. Version lookups for the shortlist go to `locator` agents. Record the stage cost.
5. **Read** (Tier 2–3, `reader` agents in batches of 4–6, brief per snu-library "Delegating reading"): evidence records into `evidence/`. Record the stage cost after each batch; apply the budget rule in cost.md before starting the next batch.
6. **Synthesize** (`main`): merge records, resolve versions, spot-check the 3–5 numbers the conclusion rests on, write `README.md`; render with `render_report_pdf`; file papers in ReadCube; add the row to `<research root>/README.md`.
7. **Close.** `cost report --run <id>`; append estimated vs measured to the report's method note; `run.jsonl` `event: done`.

Reply: preset and counts actually spent; papers read in full text / abstract-only / unread; the main findings with reference numbers; estimated vs measured tokens; checkpoint choice (user or auto); report and PDF paths.
