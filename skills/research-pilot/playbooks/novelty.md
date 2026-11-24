### Novelty check

**Has someone already done this idea? Decide from the closest papers' full text.**

Exit: a verdict (`novel`, `reframe`, `not-novel` or `provisional`) with the overlap table, or the budget stop fired.

1. **Card.** Turn the user's idea into one question card (research-topic-scout `references/question-card.md`): question, system, method, and the keywords to search with. Use an existing card when the idea came from a topic report. Folder: the topic's review folder when one exists, else a new one as in status step 1; files go in `ideas/`. Start `run.jsonl` (playbook `novelty`).
2. **Estimate.** `scholarly-access-agent cost estimate --playbook topics --skip-status --records 0 --cells 0 --cards 1 --shortlist 1 --closest 3 …` (only `novelty_search`, `novelty_read` and `cards` matter; the other stages are near zero). Remaining limit and cap per [cost.md](../references/cost.md).
3. **Checkpoint ①.** Show: the card as understood (question / system / method), the keywords that will be searched — never the idea sentence — and the estimate. Option 1 (recommended): this card and these keywords. Alternatives: adjust the system or method; add keywords. Dry run ends here.
4. **Search, read, grade, verdict** — research-topic-scout step 4 and `references/novelty-check.md` (`locator` search, `reader` for the closest 2–3, `judge` verdict). `reframe` → propose the rewritten card and check it once more.
5. **Report and close.** `ideas/novelty-<card>.md` in the user's language: verdict, overlap table (paper, access, question/system/method match, grade, reason), queries and dates, and what would make it novel when it is not. When the user asked for a report, it joins the folder's single page: `scholarly-access-agent report combine <Topic> --render` (it picks up `ideas/novelty-*.md` with the other parts). `scholarly-access-agent cost report --run <id>`; `run.jsonl` `event: done`. Offer in one line: the weekly watch for this card (research-topic-scout "After the report").

Reply: verdict and confidence; closest papers with grade and the one-line reason; how it differs (or how to reframe); queries run; estimated vs measured tokens.
