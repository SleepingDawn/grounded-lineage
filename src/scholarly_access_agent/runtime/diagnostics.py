from importlib.metadata import version
from pathlib import Path
from scholarly_access_agent.runtime.browser import DEFAULT_PROFILE_DIR

def diagnose() -> dict:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser_installed = Path(pw.chromium.executable_path).is_file()
    return {"ok": browser_installed, "browser_installed": browser_installed,
            "session_present": (DEFAULT_PROFILE_DIR / "storage-state.json").is_file(),
            "session_validity": "not_checked", "mcp_version": version("mcp"),
            "visible_browser": False}
