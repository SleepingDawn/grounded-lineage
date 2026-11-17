# Evidence record
Use a Markdown table for readers; keep JSON when reproducibility/export is requested. Minimal record:

```json
{"paper_id":"DOI/arXiv/URL", "title":"...", "version":"publisher/preprint/version/unknown", "discovered_by":[{"query":"...", "source":"...", "date":"YYYY-MM-DD"}], "access":"fulltext/abstract_only/unavailable", "criteria":[{"criterion":"...", "judgment":"met/not_met/unknown", "reason":"...", "evidence":[{"source_url":"...", "pdf_page":3, "section":"Methods", "summary":"..."}]}], "limitations":[]}
```

PDF page means one-based file page, not printed journal pagination. Record source version and exact file used. Cite only evidence actually read. Prefer concise paraphrases over long excerpts. A fulltext record may still have unknown criteria. Retrieval/term matches alone never set a criterion to met. Evidence in a preprint cannot be attributed to an unread publisher version.
