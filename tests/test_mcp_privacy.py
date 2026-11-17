import unittest
from scholarly_access_agent.mcp.server import _private_call
class PrivacyTests(unittest.TestCase):
    def test_browser_exception_does_not_return_headers(self):
        def failing(_):
            raise RuntimeError('cookie: SECRET_SESSION; authorization: Bearer SECRET')
        result = _private_call(failing, {})
        self.assertFalse(result['ok'])
        self.assertNotIn('SECRET', str(result))

    def test_main_download_cannot_fall_back_to_supplement(self):
        from scholarly_access_agent.runtime.pdf import PdfCandidate, _main_candidates
        main = PdfCandidate('https://example.com/article.pdf', 'Download PDF')
        supplement = PdfCandidate('https://example.com/supplement.pdf', 'Supplementary information')
        self.assertEqual(_main_candidates([supplement, main]), [main])
        self.assertEqual(_main_candidates([supplement]), [])
