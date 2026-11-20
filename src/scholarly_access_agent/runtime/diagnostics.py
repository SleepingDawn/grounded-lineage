import tempfile
from importlib.metadata import version
from pathlib import Path
from scholarly_access_agent.runtime.browser import DEFAULT_PROFILE_DIR

RENEW_ADVICE = ("SNU session expired or missing: ask the user to sign in again (scripts/서울대 로그인.command or "
                "`scholarly-access-agent open-url <ARTICLE_URL> --wait-for-login --headless false`) before "
                "dispatching reading batches, or subscription papers will end at the abstract.")
BLOCKED_ADVICE = ("Publisher answered HTTP 403: either the SNU session expired or the publisher's bot protection "
                  "(ScienceDirect's Cloudflare check) blocks automated downloads. Renewing the login does not "
                  "help against the latter; use the open-copy fallbacks in publisher-routes.md (HAL / author "
                  "manuscript, arXiv) and probe another subscription publisher to test the session itself.")


def probe_session(url: str, fetch=None) -> dict:
    """Check that the saved SNU session actually serves one subscription PDF.

    The article page alone is not enough: ScienceDirect landing pages load without a login wall
    even when the PDF endpoint demands one (observed 2026-11-20). So the probe fetches the PDF
    headlessly into a temporary folder and deletes it at once; nothing is kept.
    session_valid: True = PDF served, False = login required, None = inconclusive.
    """
    with tempfile.TemporaryDirectory(prefix="snu-probe-") as tmp:
        if fetch is None:
            from scholarly_access_agent.runtime.pdf import download_pdf

            def fetch(u):
                return download_pdf(u, download_dir=Path(tmp))
        result = fetch(url)
        data = result.to_dict() if hasattr(result, "to_dict") else dict(result)
    # the temporary folder (and any probe PDF) is gone here
    status = data.get("status")
    probe = {"probe_url": url, "status": status, "kept_files": False}
    if status == "blocked" or data.get("reason") == "bot_challenge":
        probe.update(session_valid=None, advice=BLOCKED_ADVICE)
    elif status == "login_required" and "403" in str(data.get("message", "")):
        # The downloader infers login_required from a bare HTTP 403. On ScienceDirect that 403 also
        # comes from its Cloudflare bot check (observed 2026-11-20), so the session may be fine.
        probe.update(session_valid=None, advice=BLOCKED_ADVICE)
    elif status == "login_required":
        probe.update(session_valid=False, advice=RENEW_ADVICE)
    elif status == "downloaded":
        probe.update(session_valid=True, advice="Session serves subscription PDFs; dispatch reading batches.")
    elif status == "unsupported":
        probe.update(session_valid=None, advice="Probe URL host is not a configured SNU proxy domain; "
                                                "probe with a ScienceDirect (or other subscribed publisher) article URL.")
    else:
        probe.update(session_valid=None, advice=f"Inconclusive ({status}): probe another paywalled article "
                                                "from the reading list, ideally on ScienceDirect.")
    return probe


def diagnose(probe_url: str | None = None, fetch=None) -> dict:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser_installed = Path(pw.chromium.executable_path).is_file()
    result = {"ok": browser_installed, "browser_installed": browser_installed,
              "session_present": (DEFAULT_PROFILE_DIR / "storage-state.json").is_file(),
              "session_validity": "not_checked", "mcp_version": version("mcp"),
              "visible_browser": False}
    if probe_url:
        probe = probe_session(probe_url, fetch=fetch)
        result["session_probe"] = probe
        result["session_validity"] = {True: "valid", False: "expired", None: "inconclusive"}[probe["session_valid"]]
        result["ok"] = result["ok"] and probe["session_valid"] is not False
    return result
