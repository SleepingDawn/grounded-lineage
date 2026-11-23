# Budget: estimate, measure, shrink, learn

Tokens are the unit. Plan-limit percent is a rough side number: other sessions on the same account move it too, and only the Claude desktop app can read it.

## Before spending

1. **Remaining limit.** When `get_usage` is available, read the 5-hour window's `percentUsed`; remaining = 100 − it. Unavailable (CLI, Codex, claude.ai) → no plan-% numbers; say so once.
2. **Estimate.** `scholarly-access-agent cost estimate --playbook <status|topics> [--preset deep] [--skip-status --records N] [--remaining-pct R] [--cap-pct C]`. The cap is the smaller of the settings' `cap_pct` and half of what remains; `--cap-tokens` sets it directly. The output gives tokens per stage and role, `calibrated_stages` (how many stages have learned factors), `plan_pct_estimate` once calibrated, and `reduced` counts when the run does not fit.
3. **Show it at checkpoint ①**, with "보정 중 (n/m 단계)" while few runs are recorded. When it does not fit, the recommended option is the reduced budget.

## While running

- **Measure each stage.** Sub-agent tokens come back with each Agent result (`subagent_tokens`): sum them per stage. Main-agent stages: the growth of the session context (`get_usage` → `context.tokensUsed`) over the stage, noted `context-delta`. Plan-% change over the stage, when readable.
- **Record it:** `cost record --run <id> --stage <stage> --tokens <n> --estimated <stage estimate> [--model opus] [--plan-pct <delta>] [--note context-delta]`. Stage names: `plan_screen`, `locate`, `read`, `synthesize`, `matrix`, `gap_check`, `cards`, `novelty_search`, `novelty_read`, `feasibility`, `critique`, `report`.
- **Budget rule, before each batch or stage:** if measured so far + the remaining stages' estimate exceeds the cap, re-run `cost estimate` with the remaining counts and `--cap-tokens <cap − spent>` and continue with its `reduced` counts (figures first, then PDFs, then papers read, then screened). Log `event: degrade` with the old and new counts.
- **Stop rule:** when the 5-hour window has under 10% left, or the reduced budget falls below its floors (5 papers read, 20 screened): finish the current batch, write what exists, log `event: stop` with the next step, and tell the user how to resume ("research-pilot 이어서 <Topic>").

## After the run

`cost report --run <id>` prints estimated vs measured per stage and the calibration the next estimate will use (median measured/estimated per stage over the last 10 runs). Put the totals in the report's method note.

Ledger: `<research root>/.cost/ledger.jsonl`, shared by all topics so every run improves the next estimate.
