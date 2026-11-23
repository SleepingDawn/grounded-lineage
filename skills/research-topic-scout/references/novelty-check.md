# Novelty check

Has someone already done this card's study? Decide from the closest papers' full text, not from abstracts or citation counts.

## Search (role `locator`)

- **Keywords only.** Build queries from technical terms (method names, material systems, properties, datasets). Never paste the card's question or hypothesis into a search engine: unpublished ideas should not leave the machine as sentences.
- **Three to five rounds**, each using a different strategy. Never stop before round three. From round three on, stop as soon as the last two rounds (rounds 2 and 3 count) added no candidate that, from its title and abstract, shares at least two of the card's question, system and method (the locator's own screen; the grading below is separate):
  1. exact technique or model name + system;
  2. the method's key component under other names (synonyms from the review's records);
  3. the application or property with any method;
  4. the method on the nearest neighbouring system;
  5. recent preprints: arXiv (and ChemRxiv where relevant) from the last three months.
- Sources: native academic web search, arXiv listings, publisher and OpenAlex search pages. Log each query, source and date in `novelty/<card>.json`.
- The locator returns candidates with identifiers and one line each; it does not grade overlap.

## Read and grade (roles `reader` → `judge`)

Take the 2–3 candidates that look closest. Read their Methods (and Results where the claim lives) with snu-library (`read_url` / `read_pdf`), journal version first. Grade each paper's overlap with the card on three parts — question, system, method:

| Grade | Overlap |
| --- | --- |
| Exact | same question, same system, same method |
| High | two parts the same and the third differs only trivially (a neighbouring system of the same class, a routine variant of the method) |
| Medium | two parts the same, the third differs substantively |
| Low | one part the same |
| None | nothing substantive in common |

## Verdict

- `not-novel` — any paper graded Exact.
- `reframe` — any paper graded High: rewrite the card once so it differs substantively (new system class, property or method), then check the rewritten card again. A second High makes it `not-novel`.
- `novel` — all closest papers Medium or lower after the minimum search.
- `provisional` — the closest paper could be read only as an abstract; say so and keep the card out of `recommended`.

The verdict follows from the grades and the access of the highest-graded papers; `scholarly-access-agent evidence lint <topic folder>` derives it and flags a stored verdict that differs. A Medium paper seen only as an abstract or web summary keeps the card `provisional` until it is read.

A combination of known techniques is novel only if the combination itself answers a question none of its parts could; a routine extension is High, not Medium.

## Record (`novelty/<card>.json`)

```json
{"card": "C3", "queries": [{"round": 1, "strategy": "exact", "query": "...", "source": "...", "date": "YYYY-MM-DD"}],
 "closest": [{"paper_id": "DOI", "access": "fulltext_pdf", "read_via": "read_pdf", "pages": [4, 5],
              "question": "same", "system": "neighbouring", "method": "different", "grade": "Medium",
              "reason": "..."}],
 "verdict": "novel", "confidence": "high | medium | low", "differentiation": "..."}
```
