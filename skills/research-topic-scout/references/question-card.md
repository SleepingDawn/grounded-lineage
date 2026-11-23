# Question card

One card per candidate topic, in `ideas/cards.md`. Card fields, the claim-strength ladder and the readiness-gate idea are adapted from the `research-ideation` skill of [Galaxy-Dawn/claude-scholar](https://github.com/Galaxy-Dawn/claude-scholar) (MIT License); the concrete gate criteria and the novelty, feasibility and profile fields are this skill's own.

```markdown
## C3 — <one-line question>
- **Type:** exploratory | confirmatory | applied
- **Gap:** matrix cell <axis values> (`empty-searched` | `contested` | `thin`), gap type <literature | methodological | application | interdisciplinary | temporal>
- **Hypothesis:** <what you expect and why>
- **Why it matters:** <who needs the answer; what changes if it is known>
- **Current evidence:** [4] Methods §2.3 (supported), [11] p. 6 (observed), ...
- **Missing evidence:** <what no record shows>
- **Supported by:** <result that would support it>
- **Falsified by:** <result that would refute it> (filled again after critique)
- **Novelty:** novel | reframe | not-novel | provisional — closest: [n] High/Medium/..., see novelty/C3.json
- **Feasibility:** first step <system, method, code, size>, ≈ <core-h / GPU-h>; fits profile: yes/no (why)
- **Risks:** <strongest objection and the pre-mortem answer>
- **Next action:** <one concrete task>
- **Decision:** recommended | read more (<missing gate item>) | stop (<reason>)
```

Claim strength for `Current evidence`: `speculative` (abstract-only, web summary, or a paper's own outlook) < `observed` (one full-text result) < `supported` (several full-text results agree) < `strong` (several independent groups, or a decisive benchmark). Name the record when raising a level; never raise it silently.
