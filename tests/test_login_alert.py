import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scholarly_access_agent.runtime import login_alert
from scholarly_access_agent.runtime.login_alert import attach_login_alert, is_session_expired, relogin_command

URL = "https://journals.aps.org/prmaterials/abstract/10.1103/sbz6-btz8"


class ExpiryDetectionTests(unittest.TestCase):
    def test_login_wall_is_expiry(self):
        self.assertTrue(is_session_expired({"ok": False, "status": "login_required", "reason": "login_required"}))

    def test_bare_http_403_is_not_treated_as_expiry(self):
        # ScienceDirect's Cloudflare check also answers 403; diagnostics calls that inconclusive.
        self.assertFalse(is_session_expired({"ok": False, "status": "login_required",
                                             "message": "HTTP 403 suggests login or access approval is required."}))

    def test_doctor_probe_expired(self):
        self.assertTrue(is_session_expired({"ok": False, "session_validity": "expired"}))
        self.assertFalse(is_session_expired({"ok": True, "session_validity": "valid"}))
        self.assertFalse(is_session_expired({"ok": True, "session_validity": "inconclusive"}))

    def test_batch_summary_with_login_required(self):
        self.assertTrue(is_session_expired({"login_required": True, "failed": 3}))
        self.assertFalse(is_session_expired({"login_required": False, "failed": 0}))

    def test_other_results_are_not_expiry(self):
        for result in ({"ok": True, "status": "downloaded"}, {"ok": False, "status": "blocked", "reason": "bot_challenge"},
                       {"ok": False, "status": "runtime_error"}, None, "text"):
            self.assertFalse(is_session_expired(result))


class ReloginCommandTests(unittest.TestCase):
    def test_command_waits_for_login_in_a_visible_browser(self):
        command = relogin_command(URL)
        self.assertIn("open-url", command)
        self.assertIn(URL, command)
        self.assertIn("--wait-for-login", command)
        self.assertIn("--headless false", command)

    def test_windows_command_uses_installed_chrome(self):
        with mock.patch.object(login_alert.sys, "platform", "win32"):
            self.assertIn("--browser-channel chrome", relogin_command(URL))
        with mock.patch.object(login_alert.sys, "platform", "darwin"):
            self.assertNotIn("--browser-channel", relogin_command(URL))

    def test_without_url_uses_a_subscription_article(self):
        self.assertIn("https://", relogin_command(None))


class AttachAlertTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "login-alert.json"
        self.calls = []
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        os.environ.pop("SNU_LOGIN_ALERT", None)
        os.environ.pop("SNU_LOGIN_ALERT_INTERVAL", None)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def notifier(self, title, body):
        self.calls.append((title, body))
        return "shown"

    def attach(self, result, now=1000.0):
        return attach_login_alert(result, url=URL, notifier=self.notifier, state_file=self.state, now=now)

    def test_valid_result_is_returned_unchanged(self):
        result = {"ok": True, "status": "downloaded"}
        self.assertEqual(self.attach(dict(result)), result)
        self.assertEqual(self.calls, [])

    def test_expired_session_notifies_and_tells_the_agent_to_ask_now(self):
        out = self.attach({"ok": False, "status": "login_required"})
        self.assertEqual(len(self.calls), 1)
        self.assertIn("로그인", self.calls[0][0] + self.calls[0][1])
        alert = out["login_alert"]
        self.assertTrue(alert["session_expired"])
        self.assertEqual(alert["desktop_notification"], "shown")
        self.assertIn("--wait-for-login", alert["relogin_command"])
        self.assertIn("now", alert["agent_instruction"].lower())
        self.assertIn("지금", out["user_action_required"])
        self.assertEqual(out["status"], "login_required")  # original fields untouched

    def test_repeat_within_interval_is_not_shown_again_but_still_reported(self):
        self.attach({"ok": False, "status": "login_required"}, now=1000.0)
        out = self.attach({"ok": False, "status": "login_required"}, now=1000.0 + 600)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(out["login_alert"]["desktop_notification"], "suppressed_recent")
        self.assertIn("user_action_required", out)

    def test_shown_again_after_interval(self):
        self.attach({"ok": False, "status": "login_required"}, now=1000.0)
        self.attach({"ok": False, "status": "login_required"}, now=1000.0 + 1801)
        self.assertEqual(len(self.calls), 2)

    def test_interval_and_disable_from_environment(self):
        os.environ["SNU_LOGIN_ALERT_INTERVAL"] = "60"
        self.attach({"ok": False, "status": "login_required"}, now=1000.0)
        self.attach({"ok": False, "status": "login_required"}, now=1061.0)
        self.assertEqual(len(self.calls), 2)
        os.environ["SNU_LOGIN_ALERT"] = "0"
        out = self.attach({"ok": False, "status": "login_required"}, now=5000.0)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(out["login_alert"]["desktop_notification"], "disabled")
        self.assertIn("user_action_required", out)

    def test_notifier_failure_never_breaks_the_tool_result(self):
        def broken(title, body):
            raise OSError("no notification service")
        out = attach_login_alert({"ok": False, "status": "login_required"}, url=URL, notifier=broken,
                                 state_file=self.state, now=1000.0)
        self.assertEqual(out["login_alert"]["desktop_notification"], "unavailable")
        self.assertEqual(out["status"], "login_required")

    def test_unwritable_state_file_still_notifies(self):
        out = attach_login_alert({"ok": False, "status": "login_required"}, url=URL, notifier=self.notifier,
                                 state_file=Path(self.tmp.name) / "missing-dir" / "x" / "state.json", now=1000.0)
        self.assertEqual(out["login_alert"]["desktop_notification"], "shown")


if __name__ == "__main__":
    unittest.main()
