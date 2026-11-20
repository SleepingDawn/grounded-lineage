# Retrieval routes by publisher

Pick the first route that applies instead of rediscovering it. Give this table to every reading sub-agent. Rows marked *observed* come from real retrievals (2026-11, a-SiO₂ κ lineage, 4 parallel readers); update them when a route changes.

**What `read_url` accepts.** Only the open-repository allow-list: arXiv, PMC (`pmc.ncbi.nlm.nih.gov`, `www.ncbi.nlm.nih.gov`), Europe PMC, chemRxiv, bioRxiv, medRxiv. Every publisher host (nature.com, frontiersin.org, aps.org, …) returns `not_open_access_host`, even for open-access articles. Fetch those with `download_pdf`, then `read_pdf`.

**Preflight once per investigation, before dispatching readers.** Call `doctor(probe_url=<one paywalled article URL from the reading list>)` (CLI: `scholarly-access-agent doctor --probe <URL>`), preferably a ScienceDirect article or one from the most common subscription publisher on the list. The probe fetches that PDF headlessly into a temporary folder and deletes it at once. `session_probe.session_valid` is `true` (PDF served), `false` (login required: ask the user to renew the SNU session per access-and-auth.md *before* starting the batches) or `null` (inconclusive: probe another article). Skipping the preflight lets every Elsevier paper in the batches end at the abstract, which costs both time and evidence level. A loaded article page is not proof of access: ScienceDirect landing pages load without a login wall while the PDF endpoint demands one (*observed*).

| Publisher (host) | Journal version route | When it fails | Notes |
|---|---|---|---|
| APS (journals.aps.org) | `download_pdf("https://journals.aps.org/<journal>/abstract/<DOI>")`; the tool derives `/<journal>/pdf/<DOI>` | Pass the `/<journal>/pdf/<DOI>` URL directly; then arXiv | *Observed*: abstract URL gave `no_pdf_found` before the derivation rule existed; the explicit `/pdf/` URL worked for PRB and PRL |
| Nature portfolio OA (nature.com: npj, Sci. Rep., Nat. Commun.) | `download_pdf(article URL)` → `read_pdf` | PMC copy via `read_url` | *Observed*: `read_url` refuses the host; `download_pdf` works. Supplementary PDFs via `discover_pdfs` |
| Frontiers (frontiersin.org) | `download_pdf(article URL)`; derives `/articles/<DOI>/pdf` | PMC via `read_url` | *Observed*: works |
| PNAS (pnas.org) | PMC via `read_url` (`PMC<id>`), with sections | arXiv for methods missing from the PMC page | *Observed*: pnas.org gave no PDF; PMC worked. PMC pages may omit SI and methods appendices |
| AIP (pubs.aip.org: JAP, JCP, APL) | Go to the arXiv version directly unless the page or figures are needed | `download_pdf` from the article page (often `no_pdf_found`) | *Observed*: `download_pdf` and `discover_pdfs` both gave `no_pdf_found` (not `login_required`); arXiv HTML worked. Record "AIP PDF 없음" as the fallback reason |
| ACS (pubs.acs.org: JCTC, JPC) | `download_pdf(article URL)` with SNU session | arXiv / ChemRxiv | *Observed*: HTTP 403 on JCTC once; arXiv used |
| Elsevier (sciencedirect.com) | `download_pdf(article URL)`; derives `/pii/<PII>/pdfft` | Author manuscript (HAL, institutional repository), then arXiv | *Observed*: `login_required` (HTTP 403) on every ScienceDirect URL when the session had expired: run the preflight. HAL is not on the allow-list; downloading from it needs the user's explicit permission or `add_domain` on request |
| Wiley, T&F, IEEE, SAGE, MDPI, PLOS, PeerJ | `download_pdf(article URL)`; the tool derives the byte-serving endpoint | arXiv / repository copy | Derivation rules are in `runtime/pdf.py` |
| Theses and institutional repositories (e.g. iris.sissa.it, hdl.handle.net) | Not reachable by the tools | Ask the user, or record `RETRIEVAL_FAILED (access restriction)` | *Observed*: HTTP 403 from the repository and its CORE mirror |
| `doi.org` links | Never pass a DOI resolver URL | Resolve to the publisher URL first (Crossref or the search result) | `download_pdf` rejects `doi.org` as unsupported |

Record the route actually used in the evidence record (`route`, `version`). A retrieval failure is an access fact, never a reason to exclude a paper.
