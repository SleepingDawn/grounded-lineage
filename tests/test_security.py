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

# Windows has no POSIX permission bits: chmod only toggles read-only, so 0o600/0o700 cannot be
# observed there. The session folder then relies on the user profile's ACLs (owner + admins).
# The mode checks run on POSIX (CI: ubuntu); the rest of each test runs everywhere.
POSIX = os.name != "nt"


def assert_mode(test, path, mode):
    if POSIX:
        test.assertEqual(stat.S_IMODE(path.stat().st_mode), mode)


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
            assert_mode(self, session, 0o600)


class SessionSecurityTests(unittest.TestCase):
    def test_session_is_owner_only_even_with_permissive_umask(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "profile"
            old = os.umask(0)
            try:
                save_storage_state(profile, {"cookies": [{"name": "session", "value": "dummy"}]})
            finally:
                os.umask(old)
            assert_mode(self, profile, 0o700)
            assert_mode(self, profile / "storage-state.json", 0o600)
            self.assertEqual(load_saved_cookies(profile)[0]["value"], "dummy")

    def test_existing_session_permissions_are_tightened(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory)
            state = profile / "storage-state.json"
            state.write_text('{"cookies": []}')
            state.chmod(0o644)
            load_saved_cookies(profile)
            assert_mode(self, state, 0o600)

    def test_session_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.json"
            target.write_text('{"cookies": []}')
            profile = root / "profile"
            profile.mkdir()
            try:
                (profile / "storage-state.json").symlink_to(target)
            except OSError:  # Windows without Developer Mode or admin rights
                self.skipTest("creating symlinks needs extra privileges on this system")
            with self.assertRaises(ValueError):
                load_saved_cookies(profile)


if __name__ == "__main__":
    unittest.main()


class AddDomainLiveTests(unittest.TestCase):
    def test_provider_sees_domain_added_after_import(self):
        from unittest import mock
        from scholarly_access_agent.providers.snu import domains as dom
        from scholarly_access_agent.providers.snu.proxy import SnuProxyProvider
        with tempfile.TemporaryDirectory() as root:
            f = Path(root) / "journal_domains.json"
            f.write_text('{"domains": ["example.org"]}', encoding="utf-8")
            with mock.patch.object(dom, "_BUILTIN_DOMAINS_FILE", f):
                self.assertFalse(SnuProxyProvider().supports_url("https://repo.example.edu/x.pdf"))
                dom.add_domain("repo.example.edu")
                self.assertTrue(SnuProxyProvider().supports_url("https://repo.example.edu/x.pdf"))
