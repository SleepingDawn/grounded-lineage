# SNU Library Scholarly Access — CLI Skill

CLI tool that uses a Seoul National University library account to access paywalled scholarly journals and download PDFs.

- Headless automatic SNU library login (using Playwright)
- Proxy URL generation for affiliated publisher sites
- PDF link discovery on article pages (distinguishes full-text from supplementary files)
- PDF download

## Supported Publishers

Nature, Science, and other publishers affiliated with the SNU library. See [journal_domain.json](src/scholarly_access_agent/data/journal_domains.json) for the full domain list.

---

## Setup

### Requirements

- Python 3.10 or later
- A Seoul National University library account

### 1. Install

Run the following commands in your terminal:

```bash
git clone https://github.com/onetwothr1/SNU-library-scholarly-access-skill.git $HOME/.claude/skills/SNU-library-scholarly-access
cd ~/.claude/skills/SNU-library-scholarly-access

python -m venv .venv
.venv\Scripts\Activate.ps1        # Windows (PowerShell)
# source .venv/bin/activate       # macOS/Linux

pip install -e .
playwright install chromium

scholarly-access-agent setup
```

### 2. Set credentials

Create a `.env` file in the skill directory:

```
SAA_SNU_USERNAME=your_snu_library_id
SAA_SNU_PASSWORD=your_snu_library_password
```

---

## CLI Usage

```bash
# Check if a URL is supported
scholarly-access-agent check-url https://www.nature.com/articles/s41586-026-10669-3

# Generate a proxy URL
scholarly-access-agent proxy-url https://www.nature.com/articles/s41586-026-10669-3

# Discover PDF links on an article page
scholarly-access-agent discover-pdfs https://www.nature.com/articles/s41586-026-10669-3

# Download a PDF (auto-discover)
scholarly-access-agent download-pdf https://www.nature.com/articles/s41586-026-10669-3 --download-dir C:/path/to/download

# Download a PDF with explicit PDF URL (skip discovery)
scholarly-access-agent download-pdf https://www.nature.com/articles/s41586-026-10669-3 --pdf-url "https://www.nature.com/.../article.pdf" --download-dir C:/path/to/download

# Open a proxied URL in a browser (for manual login or inspection)
scholarly-access-agent open-url https://www.nature.com/articles/s41586-026-10669-3

# Add a domain to the proxy list
scholarly-access-agent add-domain publisher.com
```

### Common Options

| Flag | Description |
|------|-------------|
| `--headless false` | Show browser window (for manual login intervention) |
| `--browser-channel chrome` | Use system Chrome instead of bundled Chromium |
| `--profile-dir <path>` | Persistent browser profile (preserves login state) |
| `--timeout-seconds <N>` | Network timeout in seconds (default: 30) |
| `--download-dir <path>` | Where to save downloaded PDFs |

### Output

All commands print JSON to stdout:
```json
{"ok": true, "output_path": "C:/Users/kimde/Desktop/article.pdf"}
```

Parse in scripts with `python -c "import sys,json; ..."` or `jq`.

---

## MCP Server (Optional)

An MCP server mode is available but not required for use with Claude Code. The skill works fully via CLI commands.

To use the MCP server, register it in `~/.claude.json` or `.mcp.json` (see [Claude Code MCP installation docs](https://code.claude.com/docs/en/mcp#mcp-installation-scopes)):

```json
{
  "mcpServers": {
    "snu-library-scholarly-access": {
      "command": "C:/path/to/SNU-library-scholarly-access-skill/.venv/Scripts/scholarly-access-agent.exe",
      "args": ["mcp-server"],
      "env": {
        "SAA_SNU_USERNAME": "your_snu_library_id",
        "SAA_SNU_PASSWORD": "your_snu_library_password"
      }
    }
  }
}
```

MCP tools: `check_url`, `proxy_url`, `discover_pdfs`, `download_pdf`, `add_domain`
(These mirror the CLI commands — same functionality, different interface.)

---

## Update Log

### 2026-07-21

Four bug fixes to proxy access and PDF discovery.

**Fixed**

1. **False login-wall detection.** The proxy injects the institution name into every page it relays, and publisher headers/footers almost always carry Login/Sign in links plus a collapsed login form. The "SNU + login + password" word heuristic therefore flagged successfully accessed article pages as paywalled. `PageSnapshot` now carries a `has_content_access` field — if the page exposes a way into the full text (a PDF link), that takes precedence over the word heuristic.
2. **Substring false positives in URL checks.** Because the proxy rewrites every publisher host to `<publisher>-ssl.libproxy.snu.ac.kr`, *every* proxied URL contains `snu.ac.kr`. Matching `login`/`auth`/`sso` anywhere in the URL misclassified article URLs whose paths contained those strings, and made `attempt_auto_login` report successful logins as failures. Added `_is_snu_login_url()`, which excludes rewritten publisher hosts (`*.libproxy.snu.ac.kr`) and matches markers only in the host and path.
3. **Missed PDF links and wrong candidate choice.** Detection relied mainly on `href.endsWith('.pdf')`, but most publisher PDF endpoints do not end in `.pdf` (Wiley `/doi/pdfdirect/`, Elsevier `/pdfft`, Springer `/content/pdf/`, IEEE `/stamp/stamp.jsp`, RSC `/articlepdf/`, OUP `/article-pdf/`, PLOS `type=printable`). Only the first candidate was tried, so Wiley's `/doi/pdf/` — an HTML viewer wrapper — always failed. Added `looks_like_pdf_url()` and `pdf_url_rank()` in `core/urls.py` (0 = serves bytes, 1 = ambiguous, 2 = viewer wrapper); candidates are now ranked and up to four are tried, supplementary files are deprioritized, direct URLs are derived from viewer URLs, and PDF endpoints are synthesized from the article URL on platforms that expose no DOM link.
4. **`--pdf-url` ignored the browser profile.** `_download_pdf_direct_playwright` opened a context without `user_data_dir`, so it always connected anonymously and received paywall HTML even though the proxy session cookies live in the profile. It now uses the profile directory.

Also added a direct-access fallback (`_try_direct_access`) for fully open-access publishers, which have no SNU proxy entry and get bounced to a login page when routed through it, and added `academic.oup.com`, `psycnet.apa.org`, `www.frontiersin.org`, `www.mdpi.com`, `peerj.com`, `www.hindawi.com`, and `journals.plos.org` to the domain list.

**Newly working**

Wiley, SAGE, Taylor & Francis, OUP, APS, BMJ, PLOS, Frontiers, Hindawi.

No regressions — ACM, Springer, CUP, ACS, RSC, and AAAS were re-verified against real articles. Over the same article list, publisher PDF collection went from 18 to 40 papers across 7 to 15 publishers.

**Known issues**

| Publisher | Status |
|-----------|--------|
| Elsevier (ScienceDirect) | `login_required`. The PDF sits behind a JS-rendered viewer and the proxied direct link is blocked. |
| IEEE | Reaches the derived `/stamp/stamp.jsp?arnumber=` URL but no PDF bytes are returned. |
| MDPI, PeerJ | Cloudflare bot challenge under a headless browser. `--headless false` may work; untested. |
| JSTOR | PDF link detection fails. |
| Karger | Login does not complete. |

The proxy portal session expires. Use `--profile-dir` for a persistent profile and, when needed, `--headless false` once to log in manually.

---

## Contributing

If the agent malfunctions on an affiliated publisher please open an Issue or PR.


## License

MIT License
