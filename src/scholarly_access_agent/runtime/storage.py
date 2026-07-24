from __future__ import annotations

import json
from pathlib import Path
from typing import Any


STORAGE_STATE_FILENAME = "storage-state.json"


def load_saved_cookies(profile_dir: Path) -> list[dict[str, Any]]:
    """Load session cookies exported by a user-assisted Playwright login.

    Chromium does not reliably restore session-only cookies after a persistent
    context closes. A companion storage-state file preserves those cookies
    without changing the existing profile-dir CLI contract.
    """
    state_file = profile_dir / STORAGE_STATE_FILENAME
    if not state_file.is_file():
        return []
    payload = json.loads(state_file.read_text(encoding="utf-8"))
    cookies = payload.get("cookies", [])
    if not isinstance(cookies, list) or not all(
        isinstance(cookie, dict) for cookie in cookies
    ):
        raise ValueError(f"Invalid Playwright storage state: {state_file}")
    return cookies

