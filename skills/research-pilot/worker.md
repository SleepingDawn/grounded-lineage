# Research pilot — rules for every sub-agent

The general rules (access, tools, evidence record, output contract) are in the snu-library reader pack (`scholarly-access-agent pack reader`), which opens every brief. This file adds only what the pilot needs:

1. **Budget.** Your brief gives an allowance (papers, PDFs, search rounds) derived from the run's estimate. Stop when it is used up and say what is left; the lead re-plans within the cap.
2. **Run log.** Do not write `run.jsonl`; the lead logs stages and costs.
3. **Novelty searches** (topic-scout): keyword queries only; return candidates with identifiers and one line each, written to the file your brief names. Do not grade overlap.
