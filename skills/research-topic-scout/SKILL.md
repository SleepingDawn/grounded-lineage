---
name: research-topic-scout
description: Use when the user wants research topics, open problems or next projects recommended from a literature review that already exists (an snu-library review folder with evidence records), or asks 연구 주제 추천, 연구 공백, 다음 연구 방향, 새로운 주제인지 확인, novelty check, research gap, or "what should I work on next" in a field they have reviewed.
---

# Research topic scout

## Overview

A review says what is known; this skill finds what is not, and recommends what the user can do about it. Input is a review folder made by snu-library-scholarly-access (`<research root>/<Topic>/` with `evidence/` and `README.md`); the skill reads those records instead of re-reading papers, and reads new text only to check empty cells and closest prior work. Output: `<Topic>/ideas/` with the gap matrix, question cards, novelty and feasibility checks, and a recommendation report.

**REQUIRED SUB-SKILL:** snu-library-scholarly-access, for every paper read (access rules, version priority, evidence format) and the report (HTML via `render_report_pdf`). Models come from its `references/research-models.md`; roles are named below.

No review folder for the topic → run the review first (research-pilot `status` playbook or snu-library), then come back.

## Inputs

1. **Review folder.** Records in `evidence/` (evidence-format.md), the report `README.md`, and `lineage.json` if research-lineage ran.
2. **Profile.** The user's constraints from `<research root>/research-pilot.md` (section `profile`): compute (clusters, GPUs, allocation), data they already have, advisor or group direction, time horizon, topics to exclude. Missing items: ask once (research-pilot checkpoint ①), then save them there. Under auto-recommend, or when the user declines, proceed without them (no-profile rules in steps 3, 5 and 7).

## Workflow

| # | Step | Role | Output in `ideas/` |
|---|------|------|--------------------|
| 1 | Gap matrix | `main` | `matrix.md` |
| 2 | Check empty cells | `locator` (search) → `main` | cell states updated, queries logged |
| — | research-pilot checkpoint ② | — | — |
| 3 | Question cards | `judge` | `cards.md` (5–8 cards) |
| 4 | Novelty | `locator` (search), `reader` (closest papers), `judge` (verdict) | `novelty/<card>.json` |
| 5 | Feasibility | `judge` (+ literature-to-calculation) | in each card |
| 6 | Critique and pre-mortem | `judge` | in each card |
| 7 | Readiness gate | `main` | decision per card |
| 8 | Report | `writer` | `README.md`, HTML |

Record each stage's measured tokens with `scholarly-access-agent cost record` (research-pilot `references/cost.md`).

### 1. Gap matrix
Choose two or three axes the review supports (DFT/MLIP: material system × property × model type; others: population × outcome × method). Fill each cell from the records: paper numbers `[n]` and the strongest claim level (`speculative < observed < supported < strong`; abstract-only records count as `speculative` at most). Mark every cell as one of: `covered`, `contested` (records disagree), `thin` (one paper or only abstract-level), `empty-unsearched`, `empty-searched`. Also list each record's `limitations` and the review's stated open questions. Tag gaps by type: literature, methodological, application, interdisciplinary, temporal.

### 2. Check empty cells
An empty cell may only mean the review never looked there. For each `empty-unsearched` cell that could become a topic (cap: 10, or the budget), a `locator` runs 2–3 keyword searches and returns candidates with identifiers only. The main agent turns a cell into `empty-searched` (queries logged) or fills it from what was found, reading only abstracts at this step.

### 3. Question cards
From `empty-searched`, `contested` and `thin` cells, plus limitations several papers share, write 5–8 cards (fewer when the budget reduced `cards`, never under 3) with [references/question-card.md](references/question-card.md). Drop or rewrite cards that break the profile (compute, data, direction, exclusions) before spending on them. No profile: keep every card and note "profile 미입력" on each.

### 4. Novelty
Follow [references/novelty-check.md](references/novelty-check.md) for every card: at least three search rounds with keyword queries, the closest 2–3 papers read in full text (Methods), an overlap grade per paper and a verdict: `novel`, `reframe`, `not-novel` or `provisional`.

**Rank** (`main`) the surviving cards for steps 5–6, in this order: novelty verdict (`novel` before `provisional`), motivation strength (the strongest claim level behind the gap, then the number of full-text records), profile fit (fits, unknown, does not fit). Write one line per card saying why it ranks where it does. Only the top 3 (budget: fewer) go on, and a `provisional` card takes a slot only when fewer than three cards are `novel`; the rest get `read more (feasibility not checked)`.

### 5. Feasibility
For the top-ranked cards: name the first calculation or experiment concretely (system, method, code, size, estimated core-hours or GPU-hours) against the profile. No profile: state the resources the first step needs and mark the card "자원 미확인". DFT/MLIP/MD work: hand the card to `literature-to-calculation` for the task breakdown when it is installed. Infeasible with the user's resources → say what would make it feasible, or drop it.

### 6. Critique and pre-mortem
Per top card: the strongest reviewer objection (missing baseline, weak assumption, "already done"), and "this failed after six months — why?". Put the answers into the card's *falsified by* and *risks* fields. `general-peer-review` or ARS devil's advocate may do this with the `judge` row.

### 7. Readiness gate
A card is **recommended** only when all five hold; otherwise its decision is `read more` or `stop`, with the missing item named.
1. **Motivation:** the gap rests on ≥ 2 full-text records, or on an `empty-searched` cell with logged queries.
2. **Novelty:** verdict `novel` after the minimum search, no closest paper graded High or Exact, closest papers read in full text (abstract-only → verdict at most `provisional`).
3. **Feasibility:** a named first step that fits the profile's resources. No profile: a named first step with its resource estimate passes, and the card is recommended as "자원 미확인" (the report lists the missing profile items at the top).
4. **Falsifiable:** the card names a result that would refute it, and the strongest objection is answered or listed as a risk.
5. **Next action:** a concrete task (a paper, a calculation, a dataset), not "read more".

### 8. Report
`ideas/README.md` in the user's language: the matrix (compact), recommended cards first with evidence numbers `[n]` matching the review's reference list, then `read more` cards with what is missing, then dropped ideas with the reason. Include the overlap table per recommended card, the readiness checks, the model rows used, and estimated vs measured tokens. Render with `render_report_pdf` like the review (HTML by default). File the closest prior-work papers in ReadCube list `snu-research-agent/<Topic>` when its tools are available.

## Common mistakes

| Mistake | Instead |
|---------|---------|
| Treating an empty cell as a gap | Step 2 first; `empty-unsearched` is not evidence of a gap |
| Judging novelty from abstracts | Read the closest papers' Methods; otherwise the verdict is `provisional` |
| Sending the idea sentence to a search engine | Search with technical keywords only (novelty-check.md) |
| Scoring ideas 1–10 on gut feeling | Use the readiness gate; it names what is missing |
| Re-reading papers the review already read | Use the evidence records; read only new or closest papers |
| Recommending what the user cannot run | Apply the profile at step 3, check at step 5 |
