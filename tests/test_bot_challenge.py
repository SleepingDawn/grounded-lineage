import unittest
from pathlib import Path

from scholarly_access_agent.providers.snu.login import (
    PageSnapshot,
    detect_bot_challenge,
    detect_login_required,
    is_bot_challenge_response,
)
from scholarly_access_agent.runtime.diagnostics import probe_session

SD = "https://www.sciencedirect.com/science/article/pii/S0017931024011219"


class ChallengePageTests(unittest.TestCase):
    def test_cloudflare_token_in_url_is_a_challenge_not_a_login(self):
        # Observed 2026-11-20: open-url landed here and printed "opened"
        snap = PageSnapshot(url=SD + "?__cf_chl_rt_tk=abc", title="잠시만 기다리십시오…")
        result = detect_bot_challenge(snap)
        self.assertTrue(result.required)
        self.assertEqual(result.reason, "bot_challenge")
        self.assertFalse(detect_login_required(snap).required)

    def test_localized_and_english_interstitial_titles(self):
        for title in ("잠시만 기다리십시오…", "Just a moment...", "Attention Required! | Cloudflare"):
            self.assertTrue(detect_bot_challenge(PageSnapshot(url=SD, title=title)).required, title)

    def test_challenge_text(self):
        snap = PageSnapshot(url=SD, title="sciencedirect.com", body_text="Verify you are human by completing the action below.")
        self.assertTrue(detect_bot_challenge(snap).required)

    def test_article_page_mentioning_captcha_is_not_a_challenge(self):
        snap = PageSnapshot(url=SD, title="Refined prediction of thermal transport",
                            body_text="... unusual traffic ... we compare captcha-like models ...",
                            has_content_access=True)
        self.assertFalse(detect_bot_challenge(snap).required)

    def test_ordinary_article_page(self):
        snap = PageSnapshot(url=SD, title="Refined prediction of thermal transport performance in amorphous silica")
        self.assertFalse(detect_bot_challenge(snap).required)


class ChallengeResponseTests(unittest.TestCase):
    def test_cf_mitigated_header(self):
        self.assertTrue(is_bot_challenge_response(403, {"cf-mitigated": "challenge", "Server": "cloudflare"}))

    def test_cloudflare_403_with_challenge_markup(self):
        body = b"<html><title>Just a moment...</title><script src='/cdn-cgi/challenge-platform/x.js'>"
        self.assertTrue(is_bot_challenge_response(403, {"Server": "cloudflare"}, body))

    def test_plain_403_stays_an_access_denial(self):
        self.assertFalse(is_bot_challenge_response(403, {"Server": "nginx"}, b"Forbidden"))
        self.assertFalse(is_bot_challenge_response(403, {"Server": "cloudflare"}, b"<h1>Access denied</h1>"))


class ProbeTests(unittest.TestCase):
    def test_blocked_download_makes_probe_inconclusive(self):
        probe = probe_session(SD, fetch=lambda u: {"ok": False, "status": "blocked", "reason": "bot_challenge"})
        self.assertIsNone(probe["session_valid"])
        self.assertIn("bot protection", probe["advice"])



class _Resp:
    def __init__(self, url, status=200, headers=None, body=b""):
        self.url, self.status, self.headers, self._body = url, status, headers or {}, body
        self.ok = 200 <= status < 300

    def body(self):
        return self._body


class _Locator:
    def count(self):
        return 0


class _Page:
    """Article page that shows a bot check; the PDF endpoint is served by `pdf_responses`."""

    def __init__(self, url, title, text):
        self.url, self._title, self._text = url, title, text

    def set_default_timeout(self, _):
        pass

    def goto(self, url, **_):
        return _Resp(self.url, headers={"content-type": "text/html"})

    def wait_for_load_state(self, *a, **k):
        pass

    def wait_for_timeout(self, *_):
        pass

    def title(self):
        return self._title

    def text_content(self, *a, **k):
        return self._text

    def locator(self, *_):
        return _Locator()

    def eval_on_selector_all(self, *a, **k):
        return []

    def evaluate(self, *a, **k):
        return []

    def content(self):
        return f"<html><title>{self._title}</title><body>{self._text}</body></html>"


class _Context:
    def __init__(self, page, pdf_response):
        self.pages = [page]
        self.request = type("R", (), {"get": lambda _self, href, timeout=None: pdf_response})()

    def add_cookies(self, _):
        pass

    def close(self):
        pass


def _factory(page, pdf_response):
    import contextlib
    ctx = _Context(page, pdf_response)
    chromium = type("C", (), {"launch_persistent_context": lambda _self, **k: ctx})()
    return lambda: contextlib.nullcontext(type("P", (), {"chromium": chromium})())


class DownloadOnChallengePageTests(unittest.TestCase):
    APS = "https://journals.aps.org/prb/abstract/10.1103/PhysRevB.89.144303"

    def _run(self, pdf_response):
        import tempfile
        from scholarly_access_agent.providers.snu.proxy import SnuProxyProvider
        from scholarly_access_agent.runtime import pdf as pdf_mod
        page = _Page(self.APS, "Just a moment...", "Performing security verification")
        with tempfile.TemporaryDirectory() as d:
            result = pdf_mod._download_via_playwright(
                self.APS, self.APS, SnuProxyProvider(), Path(d), Path(d) / "profile",
                None, 5, True, _factory(page, pdf_response))
            return result.to_dict()

    def test_challenge_page_but_pdf_endpoint_serves_pdf_is_downloaded(self):
        # APS, observed 2026-11-20: the article page shows a check, /prb/pdf/<DOI> returns the PDF
        pdf = _Resp("https://journals.aps.org/prb/pdf/10.1103/PhysRevB.89.144303",
                    headers={"content-type": "application/pdf"}, body=b"%PDF-1.6\n" + b"0" * 2048)
        self.assertEqual(self._run(pdf)["status"], "downloaded")

    def test_challenge_page_and_cloudflare_block_is_reported_blocked_not_login(self):
        # ScienceDirect, observed 2026-11-20: 403 from Cloudflare with the 1000-series block box
        block = _Resp("https://journals.aps.org/prb/pdf/x", status=403, headers={"server": "cloudflare"},
                      body=b"<html>There was a problem providing the content ::CLOUDFLARE_ERROR_1000S_BOX::</html>")
        result = self._run(block)
        self.assertEqual((result["status"], result["reason"]), ("blocked", "bot_challenge"))


class CloudflareBlockBoxTests(unittest.TestCase):
    def test_sciencedirect_1000s_block_box(self):
        body = b"<title>ScienceDirect</title> There was a problem providing the content you requested ::CLOUDFLARE_ERROR_1000S_BOX::"
        self.assertTrue(is_bot_challenge_response(403, {"server": "cloudflare"}, body))

if __name__ == "__main__":
    unittest.main()
