# Research models (one sheet for every research agent)

Pick each agent's row by what its output becomes: a judgment that enters the report as evidence gets a strong row; mechanical work the main agent checks gets the cheap one. Pass the row's model and effort explicitly at every spawn; never rely on the client default or the parent's model (plugin agents with `model: inherit` would otherwise run on the session model). The Agent tool's `model` overrides an agent's own frontmatter.

| Role | Does | Claude Code (Agent tool) | Codex (`spawn_agent`) | Effort: Default / Deep |
| --- | --- | --- | --- | --- |
| `main` | plan, screen, decide which version counts, gap matrix, synthesize | the session (recommend Opus) | the session model | `high` / `xhigh` |
| `reader` | Tier 2–3 full-text reading; closest-prior-work reading for novelty | `model: "opus"`, `effort: "high"` | `reasoning_effort: "high"` | `high` / `high` |
| `judge` | question cards, novelty verdicts, feasibility, critique, inclusion decisions | `model: "opus"`, `effort: "high"` | `reasoning_effort: "high"` | `high` / `high` |
| `writer` | report or draft from already-checked records | `model: "opus"`, `effort: "medium"` | `reasoning_effort: "medium"` | `medium` / `medium` |
| `locator` | find candidates, resolve DOIs and journal versions, find open copies, fetch pages, check that cells are empty; no inclusion or evidence judgments | `model: "sonnet"`, `effort: "medium"` | `reasoning_effort: "medium"` | `medium` / `medium` |

Codex: no model override; the role sets only `reasoning_effort`.

- Never use small fast models (Haiku, `*-luna` and similar) for `reader`, `judge` or any decision that enters a report.
- Use Fable (or any model above Opus) for an agent only when the user asks for it.
- The main agent cannot change its own model or effort. If the session runs on a different row than `main` — below it (Deep on `medium`) or above it (Fable costs more for the same workflow) — say so once at the start with the recommended setting, and continue.
- Outside Claude Code (claude.ai chat) there is no per-agent model: everything runs on the chat's model; say so once at the start when that model is above Opus.
- ARS agents and role prompts map the same way: reviewers, EIC, integrity and claim–reference audits, synthesis, research architect, argument builder → `judge`; report compiler, draft writer, abstracts, editorial synthesis, revision coach → `writer`; formatter, citation-format compliance, bibliography, state tracking, visualization → `locator`. An agent not listed takes the row its output fits; when unsure, `judge`.

**User override.** `<research root>/research-pilot.md` may set any role's model and effort (e.g. `reader: sonnet @high`); its values win over this sheet. Report the rows actually used in the run log.
