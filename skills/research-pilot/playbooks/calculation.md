### To calculation

**Turn a recommended card, or a paper's method, into a checkable calculation plan — prepared here, never submitted from here.**

Exit: a calculation plan the user can approve (`ideas/calc-<card>.md`, plus `.research/` artifacts when the project uses them), or a named blocker.

1. **Source.** A card from a topic report (its feasibility step already named the first step), or a paper the user names. Read the paper's Methods and SI with snu-library (journal version first) unless its evidence record already holds them. Start `run.jsonl` (playbook `calculation`).
2. **Extract** — with the field's extraction skill when one is installed (computational chemistry and materials: `literature-to-calculation`), otherwise by hand: source location, claim to compute, system, method parameters, required inputs and whether they exist, expected outputs, comparison target with units. Mark every parameter the source does not state as an assumption.
3. **Plan.** Route through the workflow skill for that kind of computation when one is installed (computational chemistry and materials: `comp-chem-workflow` with the code skill it names, `vasp`, `cp2k`, `lammps`, …; finite-element or CFD work: the solver workflow the user names, e.g. Abaqus, ANSYS, OpenFOAM; circuits: SPICE), with stages from input preparation through checks of settings to production and analysis. Estimate compute (core-hours or GPU-hours, wall time, storage) against the profile's resources, and list the smallest first calculation that tests the card's riskiest assumption. `research-orchestrator` only when the work is multi-stage and resumable; its `.research/` state then holds the plan.
4. **Checkpoint ①.** Show: the plan, assumptions, compute estimate against the profile, the first calculation. Option 1 (recommended): approve the plan as written. Alternatives: a cheaper first test; change the method level. Auto-recommend approves the *plan* only.
5. **Hand over.** Write the plan and inputs prepared so far. Submitting jobs (`hpc-submit`, schedulers, SSH) is outside this playbook: it uses allocations and outside machines, so it always waits for the user's explicit go-ahead in chat, also under auto-recommend. `run.jsonl` `event: done`.

Reply: what is computed and why (card or paper, with locator); system and method with assumptions marked; compute estimate and whether it fits the profile; the first calculation; what is prepared and where; what needs the user's go-ahead.
