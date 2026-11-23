### Topic recommendation

**Recommend topics the user can actually run, each backed by read evidence and a novelty check.**

Exit: the topic report is rendered with every card decided (recommended / read more / stop), or the budget stop fired (state saved for resume).

1. **Find or make the review.** A review folder for the topic with `evidence/` records not older than about six months → use it (`--skip-status` in the estimate). Otherwise the status playbook runs first, sharing this run's id, checkpoint ① and budget.
2. **Profile.** Load `profile` from `<research root>/research-pilot.md`; note what is missing.
3. **Estimate.** `cost estimate --playbook topics` (with `--skip-status` when the review exists, `--records <number of records>`), plan limits as in the status playbook.
4. **Checkpoint ①.** Show: review used or to be made, profile (missing items marked), estimate by role and stage, cap, model rows. Option 1 (recommended): proceed with the profile as is and the estimated or reduced budget. Alternatives: fill the missing profile items first; the review-only (status) playbook. Answers about the profile are saved to the settings file. Dry run ends here.
5. **Gap matrix and empty-cell check** — research-topic-scout steps 1–2. Record stage costs.
6. **Checkpoint ②.** Show: the axes, the matrix (compact), the 5–8 directions the cards would take, tokens spent vs estimate, remaining estimate. Option 1 (recommended): these axes and directions. Alternatives: different axes (name them), drop or add directions.
7. **Cards, novelty, feasibility, critique, gate** — research-topic-scout steps 3–7, top 3 for feasibility and critique. Apply the budget rule in cost.md between steps.
8. **Report** — research-topic-scout step 8. `cost report --run <id>`; `run.jsonl` `event: done`.

Reply: recommended topics, each with one line, novelty verdict and closest paper, first concrete step, main risk; `read more` topics with the missing item; review used; estimated vs measured tokens; checkpoint choices (user or auto); report and PDF paths.
