from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


STORAGE_STATE_FILENAME = "storage-state.json"


def ensure_private_profile(profile_dir: Path) -> None:
    profile_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    profile_dir.chmod(0o700)


def save_storage_state(profile_dir: Path, state: dict[str, Any]) -> None:
    """Keep session secrets outside shared folders, with owner-only access."""
    ensure_private_profile(profile_dir)
    fd, temporary = tempfile.mkstemp(prefix=".session-", dir=profile_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle)
        os.replace(temporary, profile_dir / STORAGE_STATE_FILENAME)
    finally:
        Path(temporary).unlink(missing_ok=True)


def load_saved_cookies(profile_dir: Path) -> list[dict[str, Any]]:
    """Load session cookies exported by a user-assisted Playwright login.

    Chromium does not reliably restore session-only cookies after a persistent
    context closes. A companion storage-state file preserves those cookies
    without changing the existing profile-dir CLI contract.
    """
    state_file = profile_dir / STORAGE_STATE_FILENAME
    if state_file.is_symlink():
        raise ValueError("Session state must not be a symbolic link.")
    if not state_file.is_file():
        return []
    ensure_private_profile(profile_dir)
    state_file.chmod(0o600)
    payload = json.loads(state_file.read_text(encoding="utf-8"))
    cookies = payload.get("cookies", [])
    if not isinstance(cookies, list) or not all(
        isinstance(cookie, dict) for cookie in cookies
    ):
        raise ValueError(f"Invalid Playwright storage state: {state_file}")
    return cookies

