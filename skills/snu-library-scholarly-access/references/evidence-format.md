# Evidence record
Use a Markdown table for readers; keep JSON when reproducibility/export is requested. Minimal record:

```json
{"paper_id":"DOI/arXiv/URL", "title":"...", "version":"publisher/preprint/version/unknown", "discovered_by":[{"query":"...", "source":"...", "date":"YYYY-MM-DD"}], "access":"fulltext_html/fulltext_pdf/abstract_only/unavailable", "read_via":"read_url/read_pdf/web_summary", "journal_version":"DOI or none_found", "preprint_fallback_reason":"null/unavailable/access_restricted/tool_error/supplement", "criteria":[{"criterion":"...", "judgment":"met/not_met/unknown", "reason":"...", "evidence":[{"source_url":"...", "pdf_page":3, "section":"Methods", "summary":"..."}]}], "limitations":[]}
```

PDF page means one-based file page, not printed journal pagination. For HTML full text cite the section name returned by `read_url` (and arXiv version). Mark `read_via: web_summary` when only a model-written page summary was seen; it is a locator, not body evidence. Record source version and exact file used. Cite only evidence actually read. Prefer concise paraphrases over long excerpts. A fulltext record may still have unknown criteria. Retrieval/term matches alone never set a criterion to met. Evidence in a preprint cannot be attributed to an unread publisher version.
