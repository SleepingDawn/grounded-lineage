from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scholarly_access_agent.mcp import server
from scholarly_access_agent.runtime.reader import read_pdf
from test_reader import make_pdf


class TermsDefaultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "many.pdf"
        # Ten pages each with a long matching passage: more than 4000 chars of hits.
        make_pdf(self.path, [("DFT phonon energy result " * 60) for _ in range(10)])

    def test_terms_default_is_4000_chars_and_8_excerpts(self):
        result = read_pdf(str(self.path), terms=["phonon"])
        self.assertLessEqual(sum(len(p["text"]) for p in result["passages"]), 4000)
        self.assertLessEqual(len(result["passages"]), 8)
        self.assertTrue(result["truncated"])
        self.assertIn("max_chars", result["hint"])

    def test_explicit_max_chars_still_honoured_in_terms_mode(self):
        result = read_pdf(str(self.path), terms=["phonon"], max_chars=16000)
        total = sum(len(p["text"]) for p in result["passages"])
        self.assertGreater(total, 4000)
        self.assertEqual(len(result["passages"]), 8)

    def test_pages_default_unchanged(self):
        result = read_pdf(str(self.path), pages="1-10")
        total = sum(len(p["text"]) for p in result["passages"])
        self.assertGreater(total, 4000)
        self.assertLessEqual(total, 16000)

    def test_mcp_wrappers_pick_mode_defaults(self):
        with mock.patch("scholarly_access_agent.runtime.public.read_url", return_value={"ok": True}) as read_url:
            server._handle_read_url({"url": "https://arxiv.org/abs/1", "terms": ["x"]})
            self.assertEqual(read_url.call_args.kwargs["max_chars"], 4000)
            server._handle_read_url({"url": "https://arxiv.org/abs/1", "sections": ["Methods"]})
            self.assertEqual(read_url.call_args.kwargs["max_chars"], 12000)
            server._handle_read_url({"url": "https://arxiv.org/abs/1", "terms": ["x"], "max_chars": 9000})
            self.assertEqual(read_url.call_args.kwargs["max_chars"], 9000)
        result = server._handle_read_pdf({"path": str(self.path), "terms": ["phonon"], "pages": "1-5"})
        self.assertLessEqual(sum(len(p["text"]) for p in result["passages"]), 4000)


if __name__ == "__main__":
    unittest.main()
