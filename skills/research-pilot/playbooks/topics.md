### Topic recommendation

**Recommend topics the user can actually run, each backed by read evidence and a novelty check.**

Exit: the topic report is rendered with every card decided (recommended / read more / stop), or the budget stop fired (state saved for resume).

One run, one `run.jsonl` (playbook `topics`), one estimate, one checkpoint ①. Steps are logged as `topics.N`; review steps run inside it are logged as `status.N`.

1. **Find the review.** A review folder for the topic with `evidence/` records not older than about six months → use it (with its `lineage.json` when research-lineage ran there). None → this run also does the review: status playbook steps 4–6, after checkpoint ① below. Set up the folder as in status step 1 either way.
2. **Profile.** Load `profile` from `<research root>/research-pilot.md`; list what is missing.
3. **Estimate.** Review exists: `scholarly-access-agent cost estimate --playbook topics --skip-status --records <evidence-record count> …`. No review: `scholarly-access-agent cost estimate --playbook topics [--preset deep] …` (it includes the review stages). Remaining limit and cap per [cost.md](../references/cost.md).
4. **Checkpoint ①.** Show: review used or to be made (question, preset, counts), profile with missing items marked, estimate by stage and role, cap, model rows. Option 1 (recommended): proceed with the profile as is and the estimated or reduced budget. Alternatives: fill the missing profile items first; review only (status playbook); the other preset. Profile answers are saved to the settings file (created then). Dry run ends here.
5. **Review** when there was none: status steps 4–6 (its report renders as `<Topic>/README.md`).
6. **Gap matrix and empty-cell check** — research-topic-scout steps 1–2.
7. **Checkpoint ②.** Show: the axes, the matrix (compact), the directions the cards would take (5–8, or the reduced count), tokens spent vs estimate, remaining estimate. Option 1 (recommended): these axes and directions. Alternatives: different axes (name them), drop or add directions.
8. **Cards, novelty, ranking, feasibility, critique, gate** — research-topic-scout steps 3–7. Apply the budget rule between steps.
9. **Report and close** — research-topic-scout step 8, then one HTML page for the folder: write an overall summary file (4–6 cited bullets covering review and topics) and run `scholarly-access-agent report combine <Topic> --render --summary <file>`; deliver only `<Topic>.html`. `scholarly-access-agent cost report --run <id>`; `run.jsonl` `event: done`. Then offer, one line each, the scout's after-report options: refine one card with ARS socratic; a weekly watch for competing work (needs the user's yes, also under auto-recommend).

Missing profile under auto-recommend: do not ask; proceed, list the missing items at the top of the topic report, and apply research-topic-scout's no-profile rules. Do not create the settings file from nothing.

Reply: recommended topics, each with one line, novelty verdict and closest paper, first concrete step, main risk; `read more` topics with the missing item; review used or made; profile items missing; estimated vs measured tokens; checkpoint choices (user or auto); report paths.
