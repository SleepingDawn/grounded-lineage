from __future__ import annotations

import contextlib
import io
import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scholarly_access_agent.providers.snu.login import PageSnapshot, _is_snu_login_url
from scholarly_access_agent.runtime.browser import open_proxied_url
from scholarly_access_agent.runtime.storage import load_saved_cookies, save_storage_state


class LoginSecurityTests(unittest.TestCase):
    def test_only_exact_https_login_origins_are_trusted(self):
        self.assertTrue(_is_snu_login_url("https://lib.snu.ac.kr/login"))
        self.assertTrue(_is_snu_login_url("https://sso.snu.ac.kr:443/login"))
        for url in [
            "https://not-snu.ac.kr/login", "https://snu.ac.kr.evil.example/login",
            "http://lib.snu.ac.kr/login", "https://lib.snu.ac.kr:8443/login",
            "https://user@lib.snu.ac.kr/login", "https://lib.snu.ac.kr:bad/login",
            "https://www-nature-com-ssl.libproxy.snu.ac.kr/login",
        ]:
            with self.subTest(url=url):
                self.assertFalse(_is_snu_login_url(url))

    def test_credentials_are_not_entered_even_when_environment_is_set(self):
        with tempfile.TemporaryDirectory() as directory:
            page = SimpleNamespace(
                set_default_timeout=lambda _: None,
                goto=lambda *args, **kwargs: None,
            )
            context = SimpleNamespace(pages=[page], close=lambda: None)
            runtime = SimpleNamespace(chromium=SimpleNamespace(
                launch_persistent_context=lambda **kwargs: context,
            ))
            snapshot = PageSnapshot(
                url="https://outside.example/login",
                title="SNU login", body_text="SNU login password",
                has_password_field=True,
            )
            with patch.dict(os.environ, {
                "SAA_SNU_USERNAME": "DUMMY", "SAA_SNU_PASSWORD": "DUMMY",
            }), patch(
                "scholarly_access_agent.runtime.browser.capture_page_snapshot",
                return_value=snapshot,
            ):
                result = open_proxied_url(
                    "https://www.nature.com/", profile_dir=Path(directory),
                    playwright_factory=lambda: contextlib.nullcontext(runtime),
                )
            self.assertEqual(result.status, "login_required")
            self.assertFalse(result.ok)

    def test_manual_login_saves_session_only_after_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            completed = []
            page = SimpleNamespace(
                set_default_timeout=lambda _: None,
                goto=lambda *args, **kwargs: None,
                reload=lambda **kwargs: None,
            )
            state = {"cookies": [], "origins": []}
            context = SimpleNamespace(
                pages=[page], close=lambda: None, storage_state=lambda: state,
            )
            runtime = SimpleNamespace(chromium=SimpleNamespace(
                launch_persistent_context=lambda **kwargs: context,
            ))
            def snapshot(_):
                if completed:
                    return PageSnapshot(url="https://www.nature.com/", has_content_access=True)
                return PageSnapshot(url="https://lib.snu.ac.kr/login", has_password_field=True)
            with patch("scholarly_access_agent.runtime.browser.capture_page_snapshot", side_effect=snapshot):
                result = open_proxied_url(
                    "https://www.nature.com/", profile_dir=Path(directory),
                    wait_for_login=True, input_func=lambda _: completed.append(True),
                    stderr=io.StringIO(),
                    playwright_factory=lambda: contextlib.nullcontext(runtime),
                )
            self.assertTrue(result.ok)
            session = Path(directory) / "storage-state.json"
            self.assertTrue(session.is_file())
            self.assertEqual(stat.S_IMODE(session.stat().st_mode), 0o600)


class SessionSecurityTests(unittest.TestCase):
    def test_session_is_owner_only_even_with_permissive_umask(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "profile"
            old = os.umask(0)
            try:
                save_storage_state(profile, {"cookies": [{"name": "session", "value": "dummy"}]})
            finally:
                os.umask(old)
            self.assertEqual(stat.S_IMODE(profile.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((profile / "storage-state.json").stat().st_mode), 0o600)
            self.assertEqual(load_saved_cookies(profile)[0]["value"], "dummy")

    def test_existing_session_permissions_are_tightened(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory)
            state = profile / "storage-state.json"
            state.write_text('{"cookies": []}')
            state.chmod(0o644)
            load_saved_cookies(profile)
            self.assertEqual(stat.S_IMODE(state.stat().st_mode), 0o600)

    def test_session_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.json"
            target.write_text('{"cookies": []}')
            profile = root / "profile"
            profile.mkdir()
            (profile / "storage-state.json").symlink_to(target)
            with self.assertRaises(ValueError):
                load_saved_cookies(profile)


if __name__ == "__main__":
    unittest.main()
