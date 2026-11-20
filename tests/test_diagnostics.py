import unittest
from pathlib import Path

from scholarly_access_agent.runtime import diagnostics
from scholarly_access_agent.runtime.diagnostics import probe_session

URL = "https://www.sciencedirect.com/science/article/pii/S0017931024011219"


def fake(status):
    return lambda url: {"ok": status == "downloaded", "status": status}


class SessionProbeTests(unittest.TestCase):
    def test_login_wall_on_pdf_means_expired_session_with_renewal_advice(self):
        probe = probe_session(URL, fetch=fake("login_required"))
        self.assertIs(probe["session_valid"], False)
        self.assertIn("sign in again", probe["advice"])

    def test_bare_http_403_is_inconclusive_bot_check_or_expiry(self):
        probe = probe_session(URL, fetch=lambda u: {"ok": False, "status": "login_required",
                                                     "message": "HTTP 403 suggests login or access approval is required."})
        self.assertIsNone(probe["session_valid"])
        self.assertIn("Cloudflare", probe["advice"])

    def test_served_pdf_means_valid_session(self):
        self.assertIs(probe_session(URL, fetch=fake("downloaded"))["session_valid"], True)

    def test_other_failures_are_inconclusive_not_valid(self):
        for status in ("no_pdf_found", "download_failed"):
            self.assertIsNone(probe_session(URL, fetch=fake(status))["session_valid"])

    def test_unsupported_host_asks_for_a_subscription_article(self):
        probe = probe_session("https://example.org/a", fetch=fake("unsupported"))
        self.assertIsNone(probe["session_valid"])
        self.assertIn("ScienceDirect", probe["advice"])

    def test_default_fetch_downloads_into_a_folder_that_is_deleted(self):
        seen = {}

        def fake_download(url, download_dir):
            pdf = Path(download_dir) / "probe.pdf"
            pdf.write_bytes(b"%PDF-1.4")
            seen["dir"] = Path(download_dir)
            return {"ok": True, "status": "downloaded", "output_path": str(pdf)}

        import scholarly_access_agent.runtime.pdf as pdf_module
        original = pdf_module.download_pdf
        pdf_module.download_pdf = fake_download
        try:
            probe = probe_session(URL)
        finally:
            pdf_module.download_pdf = original
        self.assertIs(probe["session_valid"], True)
        self.assertFalse(seen["dir"].exists())  # nothing kept
        self.assertFalse(probe["kept_files"])


if __name__ == "__main__":
    unittest.main()
