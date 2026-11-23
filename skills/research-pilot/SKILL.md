---
name: research-pilot
description: Use when the user wants a literature review or research-topic recommendation run end to end with little supervision — "알아서 조사해줘", "현황 조사부터 주제 추천까지", "자동으로", "run the whole research pipeline", "추천대로 자동" — when they ask what a research run will cost before it starts (예행, dry run, 비용만 먼저), or when they ask to resume an interrupted research run.
---

# Research pilot

## Overview

One entry point that picks a playbook, runs the research skills in a fixed order, stops at most twice for the user (each stop with a recommended option first), and keeps every run inside a token budget it estimates, measures and learns from. The skills do the work; the pilot only routes, gates, budgets and logs.

**REQUIRED SUB-SKILLS:** snu-library-scholarly-access (all reading, access rules, reports) and, for topics, research-topic-scout. Models and efforts: snu-library `references/research-models.md`; the `<research root>/research-pilot.md` settings file overrides them.

## Route

| Request | Playbook |
| --- | --- |
| field status, trends, literature review, "what is known about X" | [playbooks/status.md](playbooks/status.md) |
| research topics, gaps, next project, "what should I work on" | [playbooks/topics.md](playbooks/topics.md) |
| resume, "이어서" | the playbook named in the topic folder's `run.jsonl`; continue after its last logged step (`event: done` means finished) |
| where a concept came from, how it branched, what is mainstream now | [playbooks/lineage.md](playbooks/lineage.md) |
| is this one idea new, has someone done X | [playbooks/novelty.md](playbooks/novelty.md) |
| turn a recommended topic or a paper's method into calculations | [playbooks/calculation.md](playbooks/calculation.md) |

Two readings both plausible and the choice is reversible: pick one, say which in one line, continue. Dry run (예행, "비용만", `--dry-run`): run the playbook to checkpoint ① and stop there; spend nothing on search or reading.

## Settings

`<research root>/research-pilot.md`, where the research root is `SNU_RESEARCH_ROOT` (default `~/Documents/research`). Create it when the user first answers a settings or profile question at checkpoint ①; until then, defaults apply:

```markdown
checkpoints: ask            # ask | auto-recommend
cap_pct: 30                 # optional per-run cap, % of the 5-hour plan limit
cap_tokens: 1500000         # optional per-run cap in tokens (works without get_usage)
roles:                      # optional overrides of research-models.md
  reader: opus @high
profile:                    # used by topics; reused every run
  compute: <clusters, GPUs, allocation>
  data: <datasets or results the user already has>
  direction: <advisor or group direction>
  horizon: <e.g. 6 months>
  exclude: <topics to avoid>
```

## Checkpoints

A playbook stops only at its checkpoints, never elsewhere: not for reversible choices, not for routine access failures (record them and move on). The exceptions are the access rules in snu-library (login renewal is the user's) and the budget stop in [references/cost.md](references/cost.md).

At a checkpoint, show what was decided and the numbers, then offer:
1. **추천대로 진행 (Recommended)** — the pilot's recommendation, stated concretely;
2. one or two real alternatives;
3. the user's own input (free text).

In Claude Code use AskUserQuestion with the recommendation first; elsewhere a numbered list where 1 is the recommendation.

**Auto-recommend.** When the settings say `checkpoints: auto-recommend`, or the user said "추천대로 자동", "끝까지 자동", "auto" for this run, take option 1 at every checkpoint without asking: post the checkpoint summary as a short status message (what was chosen, the numbers) and keep going, log it as `auto` in `run.jsonl`, and mark it in the final report's method note ("checkpoint ② auto-accepted: axes …"). When a run makes two reports (review + topics), the marks and the cost totals go in the last one.

## Run log

`<Topic>/run.jsonl`, one JSON object per line: `{"ts", "run", "playbook", "step", "event": "start|checkpoint|stage|degrade|stop|done", ...}`. Checkpoints record the options and the choice (`user` or `auto`); stages record the cost-ledger entry. A resumed run reads it to find its place. Run id: `<Topic>-YYYYMMDD-HHMM`.

## Sub-agents

Every sub-agent's brief begins: "Read <path>/worker.md before anything else.", where `<path>` is the absolute directory this SKILL.md was loaded from (the skill's base directory). Then the task, the role's model and effort (passed explicitly), file paths rather than pasted text, and the output shape. See [worker.md](worker.md).

## Budget

Estimate before spending, measure each stage, shrink before exceeding: [references/cost.md](references/cost.md). The estimate is shown at checkpoint ①; spent vs remaining at checkpoint ② and in the report.
