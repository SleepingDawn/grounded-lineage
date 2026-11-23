# Evidence record
Use a Markdown table for readers; keep JSON when reproducibility/export is requested. Minimal record:

```json
{"paper_id":"DOI/arXiv/URL", "title":"...", "version":"publisher/preprint/version/unknown", "discovered_by":[{"query":"...", "source":"...", "date":"YYYY-MM-DD"}], "access":"fulltext_pdf/fulltext_html/excerpts/secondary/abstract_only/unavailable", "read_via":"read_pdf/read_url/web_summary/citing_paper/manual/none", "journal_version":"DOI or none_found", "preprint_fallback_reason":"null/unavailable/access_restricted/tool_error/supplement",  "venue_type":"journal/conference_paper/conference_abstract/thesis/preprint/working_paper/report/book", "indexing":"SSCI/SCIE/KCI/Scopus/none/unknown", "evidence_role":"empirical/model/review/context", "criteria":[{"criterion":"...", "judgment":"met/not_met/unknown", "reason":"...", "evidence":[{"source_url":"...", "pdf_page":3, "section":"Methods", "read_mode":"pages/sections/terms/figure/caption/citing", "summary":"..."}]}], "limitations":[]}
```

**How much was read — `access` and `read_mode` decide the report label; never write the label by hand.**

| `access` | Meaning | Label (`scholarly-access-agent evidence labels`) |
|---|---|---|
| `fulltext_pdf` / `fulltext_html` with a locator read as `pages`, `sections` or `figure` | the passages behind each judgment were read whole | **본문 확인** |
| `excerpts` (or fulltext whose locators are only `terms`/`caption`) | only term-located passages or captions were read | **발췌 확인** |
| `secondary` | the paper itself was not read; its content comes from a paper that cites it (`read_via: citing_paper`, locator in the citing paper) | **인용 맥락만** |
| `abstract_only` | abstract or landing page only | **초록만 확인** |
| `unavailable` | nothing read | **미확인** |

`read_pdf(terms=…)` and `read_url(terms=…)` locate; they do not read a range. A judgment resting on them is `read_mode: terms` until the page or section is read whole. Run `scholarly-access-agent evidence lint <topic folder>` before writing the report: it rejects records whose access, locators, read_via and version disagree, and derives novelty verdicts (topic-scout) from the overlap grades.

**Numbers go in `results`.** Every number a report may cite is stored once, structured, where it was read:

```json
"source_file": "pdfs/PhysRevB.89.144303.pdf",
"results": [{"id": "gk300", "quantity": "kappa (Green-Kubo, classical)", "value": 2.1, "lo": 1.9, "hi": 2.3,
             "unit": "W/mK", "condition": "BKS, 300 K", "pdf_page": 9, "section": "Table II", "read_mode": "pages",
             "verified_by": null}]
```

`value` is the number as printed (a range may be a string, "14-24"); `lo`/`hi` an uncertainty or range when given; `condition` what the number depends on (temperature, size, method, sample). A number you computed from the paper's numbers (a ratio, a difference) is not a result of that paper: write it in the report as your own calculation with its inputs cited. `source_file` (path inside the topic folder) lets `scholarly-access-agent evidence verify <topic folder> --write` re-read the page and confirm each value is printed there; it records `verified_by`.

`venue_type` is what the item is, not where you read it (a journal article read on arXiv is still `journal` with `version: preprint`). `indexing` comes from the journal's listing (Web of Science, Scopus, KCI), checked once per journal; `unknown` when not checked. `evidence_role`: `empirical` measures or estimates the effect asked about, `model` derives it, `review` summarises others, `context` (history, governance, critique, commentary) explains the setting but is not evidence for an effect. Author names: as printed; Korean authors in Hangul with the romanised form the paper uses in parentheses, e.g. `이도경 (Lee, Dokyung)`.

PDF page means one-based file page, not printed journal pagination. For HTML full text cite the section name returned by `read_url` (and arXiv version). Mark `read_via: web_summary` when only a model-written page summary was seen; it is a locator, not body evidence. Record source version and exact file used. Cite only evidence actually read. Prefer concise paraphrases over long excerpts. A fulltext record may still have unknown criteria. Retrieval/term matches alone never set a criterion to met. Evidence in a preprint cannot be attributed to an unread publisher version.
