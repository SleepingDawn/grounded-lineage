"""Tell the user at once when the SNU session has expired, and recommend renewing it now.

An expired session does not stop a review: subscription papers quietly fall back to open copies
or end at the abstract, and the agent may carry on without saying so. So every tool result that
shows an expired session gets

* a desktop notification (Windows toast, macOS Notification Center, Linux notify-send), shown at
  most once per interval (default 30 min; ``SNU_LOGIN_ALERT_INTERVAL`` seconds; ``SNU_LOGIN_ALERT=0``
  turns it off), and
* ``user_action_required`` (Korean, for the user) plus ``login_alert`` (the re-login command and an
  instruction for the agent to pass it on now) added to the result.

A bare HTTP 403 is not treated as expiry: ScienceDirect's Cloudflare check answers 403 too, and
``diagnostics.probe_session`` calls that inconclusive. Notification failures never change the
tool result.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

STATE_FILE = Path.home() / ".local" / "share" / "snu-library-scholarly-access" / "login-alert.json"
DEFAULT_INTERVAL_S = 1800
DEFAULT_ARTICLE_URL = "https://www.sciencedirect.com/science/article/pii/S0017931024011219"

TITLE = "SNU 도서관 로그인 만료"
TOAST_BODY = "구독 논문을 받으려면 지금 다시 로그인하세요. 실행할 명령은 Claude 대화에 표시됩니다."
AGENT_INSTRUCTION = (
    "Tell the user now, in one line, that the SNU library login has expired and recommend renewing it now: "
    "they run relogin_command in a terminal they can type into, sign in in the browser window that opens, "
    "then press Enter in that terminal. Do not wait for a checkpoint or the end of the run. Meanwhile continue "
    "with open copies; retry the subscription papers once after the user confirms the renewal."
)


def is_session_expired(result: Any) -> bool:
    """True when a tool result shows an expired or missing SNU session."""
    if not isinstance(result, dict):
        return False
    if result.get("session_validity") == "expired":  # doctor(probe_url=...)
        return True
    if result.get("login_required") is True:  # download-many summary
        return True
    if result.get("status") == "login_required":
        return "403" not in str(result.get("message", ""))
    return False


def _executable() -> str:
    """The scholarly-access-agent command as the user can type it in a terminal."""
    scripts = Path(sys.executable).parent
    for name in ("scholarly-access-agent.exe", "scholarly-access-agent"):
        candidate = scripts / name
        if candidate.is_file():
            return str(candidate)
    return "scholarly-access-agent"


def relogin_command(url: str | None) -> str:
    """One terminal command that opens a visible browser for the user's SNU sign-in."""
    target = url or DEFAULT_ARTICLE_URL
    exe = _executable()
    args = f'open-url "{target}" --wait-for-login --headless false'
    if sys.platform.startswith("win"):
        # Playwright's bundled headed Chromium fails on some Windows installs; installed Chrome works.
        return f'$env:PYTHONUTF8=1; & "{exe}" {args} --browser-channel chrome'
    return f'"{exe}" {args}' if " " in exe else f"{exe} {args}"


def desktop_notify(title: str, body: str) -> str:
    """Send one desktop notification without blocking. Returns 'sent' or 'unavailable'."""
    env = dict(os.environ, GL_ALERT_TITLE=title, GL_ALERT_BODY=body)
    if sys.platform.startswith("win"):
        script = (
            "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null;"
            "$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
            "[Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
            "$x = $t.GetElementsByTagName('text');"
            "$x.Item(0).AppendChild($t.CreateTextNode($env:GL_ALERT_TITLE)) > $null;"
            "$x.Item(1).AppendChild($t.CreateTextNode($env:GL_ALERT_BODY)) > $null;"
            "$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe';"
            "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show("
            "[Windows.UI.Notifications.ToastNotification]::new($t))"
        )
        command = ["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", script]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    elif sys.platform == "darwin":
        command = ["osascript", "-e",
                   'display notification (system attribute "GL_ALERT_BODY") '
                   'with title (system attribute "GL_ALERT_TITLE") sound name "Glass"']
        flags = 0
    elif shutil.which("notify-send"):
        command = ["notify-send", "--urgency=critical", title, body]
        flags = 0
    else:
        return "unavailable"
    try:
        subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=flags)
    except OSError:
        return "unavailable"
    return "sent"


def _interval() -> float:
    try:
        return float(os.environ.get("SNU_LOGIN_ALERT_INTERVAL", DEFAULT_INTERVAL_S))
    except ValueError:
        return float(DEFAULT_INTERVAL_S)


def _last_alert(state_file: Path) -> float | None:
    try:
        return float(json.loads(state_file.read_text(encoding="utf-8"))["last_alert"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _remember(state_file: Path, now: float) -> None:
    try:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps({"last_alert": now}), encoding="utf-8")
    except OSError:
        pass


def attach_login_alert(result: Any, url: str | None = None,
                       notifier: Callable[[str, str], str] | None = None,
                       state_file: Path | None = None, now: float | None = None) -> Any:
    """Return the result unchanged unless it shows an expired session; then notify and annotate it."""
    if not is_session_expired(result):
        return result
    notifier = notifier or desktop_notify
    state_file = state_file or STATE_FILE
    now = time.time() if now is None else now
    command = relogin_command(url or result.get("probe_url") or result.get("source_url")
                              or (result.get("session_probe") or {}).get("probe_url"))
    if os.environ.get("SNU_LOGIN_ALERT", "1").strip().lower() in ("0", "false", "off", "no"):
        shown = "disabled"
    else:
        last = _last_alert(state_file)
        if last is not None and 0 <= now - last < _interval():
            shown = "suppressed_recent"
        else:
            try:
                shown = notifier(TITLE, TOAST_BODY)
            except Exception:  # a broken notifier must never break the tool result
                shown = "unavailable"
            _remember(state_file, now)
    annotated = dict(result)
    annotated["user_action_required"] = (
        "SNU 도서관 로그인이 만료되었습니다. 구독 논문(Elsevier·APS·ACS 등)을 받으려면 지금 다시 로그인하세요. "
        f"터미널에서 실행: {command}  — 열린 브라우저에서 로그인한 뒤 그 터미널에서 Enter."
    )
    annotated["login_alert"] = {"session_expired": True, "desktop_notification": shown,
                                "relogin_command": command, "agent_instruction": AGENT_INSTRUCTION}
    try:
        print(f"[snu-library] {TITLE}: {command}", file=sys.stderr)
    except Exception:
        pass
    return annotated
