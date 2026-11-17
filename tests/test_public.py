import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scholarly_access_agent.runtime import public

HTML = """<html><head><title>Test Paper</title><script>ignore()</script></head><body>
<h1>A test MLIP paper</h1><div class='ltx_abstract'><h6>Abstract</h6><p>We train a universal potential.</p></div>
<section><h2>1 Introduction</h2><p>Prior work used SCAN in references only. """ + "Filler text. " * 60 + """</p></section>
<section><h2>2 Methods</h2><p>Training labels were computed with r2SCAN and energy <math alttext='E_{tot}'><mi>E</mi></math> forces.</p>
<figure><img src='x1.png'><figcaption>Figure 1: Parity plot of forces.</figcaption></figure></section>
<section><h2>3 Results</h2><p>Phonon softening was reduced.</p></section></body></html>"""


class PublicTextTests(unittest.TestCase):
    def test_url_rules(self):
        self.assertTrue(public.is_public_url("https://arxiv.org/abs/2405.07105"))
        self.assertFalse(public.is_public_url("http://arxiv.org/abs/2405.07105"))
        self.assertFalse(public.is_public_url("https://www.nature.com/articles/x"))
        self.assertFalse(public.is_public_url("https://arxiv.org.evil.com/abs/1"))
        self.assertEqual(public.text_url("https://arxiv.org/pdf/2405.07105v2"), "https://arxiv.org/html/2405.07105v2")
        self.assertEqual(public.pdf_url_for("https://arxiv.org/abs/2405.07105"), "https://arxiv.org/pdf/2405.07105")
        self.assertEqual(public.text_url("https://arxiv.org/abs/cond-mat/0102030"), "https://arxiv.org/html/cond-mat/0102030")

    def test_outline_terms_and_sections(self):
        url = "https://arxiv.org/html/2405.07105v1"
        outline = public.read_html(HTML, url)
        self.assertEqual(outline["mode"], "outline")
        self.assertIn("universal potential", outline["abstract"])
        self.assertEqual(outline["figures"][0]["image_url"], "https://arxiv.org/html/x1.png")
        self.assertIn("2 Methods", [item["section"] for item in outline["outline"]])
        self.assertNotIn("ignore", str(outline))
        located = public.read_html(HTML, url, terms=["r2SCAN", "NEB"])
        self.assertEqual(located["passages"][0]["section"], "2 Methods")
        self.assertEqual(located["terms_without_hits"], ["NEB"])
        section = public.read_html(HTML, url, sections=["methods"])
        self.assertIn("E_{tot}", section["passages"][0]["text"])
        self.assertIn("Parity plot", section["passages"][0]["text"])
        with self.assertRaises(ValueError):
            public.read_html(HTML, url, terms=["a"], sections=["b"])

    def test_non_public_hosts_are_not_fetched(self):
        with mock.patch.object(public, "urlopen") as opened:
            result = public.read_url("https://www.sciencedirect.com/science/article/pii/X")
            self.assertEqual(result["reason"], "not_open_access_host")
            opened.assert_not_called()

    def test_public_pdf_download(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(public, "_fetch", return_value=(b"%PDF-1.4 test", "https://arxiv.org/pdf/2405.07105v1", "application/pdf")):
            result = public.download_public_pdf("https://arxiv.org/abs/2405.07105v1", download_dir=Path(directory))
            self.assertTrue(result["ok"])
            self.assertTrue(result["output_path"].endswith("2405.07105v1.pdf"))
            with mock.patch.object(public, "_fetch", return_value=(b"<html>", "https://arxiv.org/pdf/1", "text/html")):
                self.assertEqual(public.download_public_pdf("https://arxiv.org/abs/2405.07105", download_dir=Path(directory))["status"], "not_pdf")


if __name__ == "__main__":
    unittest.main()
