# Budget: estimate, measure, shrink, learn

Tokens are the unit of the estimate. Plan-limit percent is what the user actually runs out of, so the cap is in percent once a conversion is known; other sessions on the same account also move the percent, and only the Claude desktop app can read it (`get_usage`).

All commands are `scholarly-access-agent cost …` (executable path in this skill's `references/local-runtime.md` when installed).

## Before spending

1. **Remaining limit.** With `get_usage`: remaining = 100 − the 5-hour window's `percentUsed`; note the weekly windows too. Without it (CLI, Codex, claude.ai): no plan-% numbers; say so once; only a token cap from the settings (`cap_tokens`) applies.
2. **Estimate, one per run.** `scholarly-access-agent cost estimate --playbook <status|topics> [--preset deep] [--remaining-pct R] [--cap-pct C] [--cap-tokens T]`. The topics estimate includes the review stages unless `--skip-status` is given; `--records N` (the review's evidence-record count) goes with `--skip-status` only.
3. **The cap.** Fixed once, at the start of the run, for the whole run: the smallest of the settings' `cap_tokens`, the settings' `cap_pct`, and half of the 5-hour limit remaining at the start. Spent-so-far is always counted from the start against this same cap; later readings only convert it, never reset it. Percent caps convert to tokens only with a known rate (`plan_pct_per_mtok`, learned from the ledger). With an empty ledger the output has no rate and says so in `cap_note`: then the run starts without a token cap, and the rate is learned from this run's first recorded stage (below).
4. **Show it at checkpoint ①:** tokens by stage and role, "보정 중 (n/m 단계)" while stages are uncalibrated, the cap and how it was set, and the `reduced` counts when the estimate does not fit (then the reduced budget is the recommended option).

## While running

- **Measure each stage.** Sub-agent stages: sum `subagent_tokens` from the Agent results. Main-agent stages: the growth of `get_usage` → `context.tokensUsed` over the stage, with `--note context-delta`. It is a lower bound (each turn re-sends the context); calibration absorbs that as long as the same stage is always measured the same way. A negative delta (compaction) is recorded as 0 with `--note compacted`. Plan-% change over the stage when readable.
- **Record it:** `scholarly-access-agent cost record --run <id> --stage <stage> --tokens <n> --estimated <stage estimate> --model <model actually used, e.g. fable for a Fable main session> [--plan-pct <delta>] [--note …]`. One record per stage: a stage with both a sub-agent and main-agent part (e.g. `gap_check`) records their sum. Stages: `plan_screen`, `locate`, `read`, `synthesize`, `matrix`, `gap_check`, `cards`, `novelty_search`, `novelty_read`, `feasibility`, `critique`, `report`; setup, the estimate and checkpoint ① are counted in `plan_screen` (or `matrix` when the review already exists); checkpoint ② in `gap_check`; ranking and the readiness gate in `critique`.
- **Learn the rate in-run.** After the first stage recorded with `--plan-pct` (prefer a sub-agent stage such as `locate` or `read`, whose model mix resembles the rest of the run), `cost estimate` returns a rate; convert the run's percent cap to tokens with it by re-running with `--cap-pct <the run's cap %>` (not `--remaining-pct`). The rate is the median over all recorded stages, so it improves as stages are recorded.
- **Budget rule, before each batch or stage:** if spent so far + the remaining stages' estimate exceeds the cap, re-run `cost estimate` with the remaining counts and `--cap-tokens <cap − spent>`, continue with its `reduced` counts (order: figures, PDFs, empty cells checked, cards, shortlist, papers read, screened; novelty search rounds never drop below three; a reduced card count overrides research-topic-scout's 5–8), and log `event: degrade` with old and new counts.
- **Allowances in briefs.** Split the current (possibly reduced) counts evenly across the reader batches: each brief names its papers and its share of PDFs and figures. Locators get fixed allowances: 2–3 searches per empty cell; 3–5 novelty rounds per card.
- **Stop rule:** when the 5-hour window has under 10% left, any weekly window over 95%, or `reduced` cannot fit at its floors (5 papers read, 20 screened, 3 cards, 3 cells): finish the current batch, write what exists, log `event: stop` with the next step, and tell the user how to resume ("research-pilot 이어서 <Topic>"). If the 5-hour window resets during a run, the cap stays as set at the start; only the stop rule reads the new window.

## After the run

`scholarly-access-agent cost report --run <id>` prints estimated vs measured per stage and the calibration the next estimate will use (median measured/estimated per stage over the last 10 runs). Put the totals in the final report's method note.

Ledger: `<research root>/.cost/ledger.jsonl`, shared by all topics so every run improves the next estimate.
