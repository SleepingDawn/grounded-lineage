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

    def test_a_long_heading_from_the_outline_can_be_read_back(self):
        heading = ("2.2 Sampling of solid-liquid interfaces with explicit solvent, ions and adsorbates "
                   "from short relaxations and ab initio molecular dynamics")
        self.assertGreater(len(heading), 100)
        html = HTML.replace("<h2>3 Results</h2><p>Phonon softening was reduced.</p>",
                            f"<h2>{heading}</h2><p>Each box holds 1000 K AIMD frames. " + "More text. " * 40 + "</p>")
        url = "https://arxiv.org/html/2509.17862v2"
        names = [item["section"] for item in public.read_html(html, url)["outline"]]
        self.assertIn(heading, names)
        section = public.read_html(html, url, sections=[heading, "2 Methods"])
        self.assertEqual([p["section"] for p in section["passages"]], ["2 Methods", heading])
        self.assertIn("1000 K AIMD", section["passages"][1]["text"])
        with self.assertRaises(ValueError):
            public.read_html(html, url, terms=["x" * 101])   # search terms keep their short limit

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


class EngineeringRepositoryTests(unittest.TestCase):
    """Engineering open repositories: landing page -> abstract via read_url, public PDF found from the page."""

    def test_engineering_hosts_are_allowed_and_lookalikes_are_not(self):
        for url in ("https://engrxiv.org/preprint/view/3000", "https://hal.science/hal-05729555v1",
                    "https://www.osti.gov/biblio/3739948", "https://ntrs.nasa.gov/citations/20230005410",
                    "https://aclanthology.org/N19-1423/", "https://openaccess.thecvf.com/content/x.html"):
            self.assertTrue(public.is_public_url(url), url)
        self.assertFalse(public.is_public_url("https://hal.science.evil.com/x"))
        self.assertFalse(public.is_public_url("http://www.osti.gov/biblio/1"))
        self.assertFalse(public.is_public_url("https://www.techrxiv.org/doi/full/10.36227/x"))  # blocks bots

    def test_pdf_link_found_on_landing_page(self):
        meta = '<meta name="citation_pdf_url" content="https://hal.science/hal-1/document">'
        self.assertEqual(public.pdf_link_in(meta, "https://hal.science/hal-1v1"), "https://hal.science/hal-1/document")
        flipped = '<meta content="/servlets/purl/42" name="citation_pdf_url">'
        self.assertEqual(public.pdf_link_in(flipped, "https://www.osti.gov/biblio/42"), "https://www.osti.gov/servlets/purl/42")
        # no meta tag: a .pdf link named like the page (ACL, CVF), not an unrelated supplement
        page = "https://openaccess.thecvf.com/content/html/Smith_Crack_Segmentation_paper.html"
        links = '<a href="../papers/Smith_Crack_Segmentation_paper.pdf">pdf</a><a href="../sup/other.pdf">sup</a>'
        self.assertEqual(public.pdf_link_in(links, page), "https://openaccess.thecvf.com/content/papers/Smith_Crack_Segmentation_paper.pdf")
        # a PDF off the allow list (or plain http) is never returned
        off = '<meta name="citation_pdf_url" content="http://www.cv-foundation.org/x.pdf">'
        self.assertIsNone(public.pdf_link_in(off, "https://openaccess.thecvf.com/content/html/x.html"))

    def test_landing_page_download_and_library_fallback(self):
        landing = ('<html><meta name="citation_pdf_url" content="https://engrxiv.org/preprint/download/3000/5505">'
                   '</html>').encode()

        def fake_fetch(url, limit, timeout):
            if url.endswith("/view/3000"):
                return landing, url, "text/html; charset=utf-8"
            return b"%PDF-1.7 x", url, "application/pdf"
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(public, "_fetch", side_effect=fake_fetch):
            got = public.public_pdf_attempt("https://engrxiv.org/preprint/view/3000", download_dir=Path(directory))
            self.assertTrue(got["ok"])
            self.assertTrue(got["output_path"].endswith("engrxiv_3000.pdf"))  # named after the page, not "5505"
        no_pdf = (b"<html>no link here</html>", "https://hal.science/hal-9", "text/html")
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(public, "_fetch", return_value=no_pdf):
            # landing page without a public PDF: None, so the caller tries the library route instead
            self.assertIsNone(public.public_pdf_attempt("https://hal.science/hal-9", download_dir=Path(directory)))
        with mock.patch.object(public, "_fetch", side_effect=AssertionError("not fetched")):
            self.assertIsNone(public.public_pdf_attempt("https://ieeexplore.ieee.org/document/1", download_dir=Path(".")))


class PreprintHostTests(unittest.TestCase):
    def test_engineering_preprint_servers_are_recognised(self):
        from scholarly_access_agent.lineage import links
        for url in ("https://www.techrxiv.org/doi/full/10.36227/x", "https://engrxiv.org/preprint/view/1"):
            self.assertTrue(links.PREPRINT_HOST.search(url), url)
        self.assertFalse(links.PREPRINT_HOST.search("https://ieeexplore.ieee.org/document/1"))
        self.assertTrue(links.is_preprint_doi("10.36227/techrxiv.1"))
        self.assertTrue(links.is_preprint_doi("10.31224/3000"))
        self.assertFalse(links.is_preprint_doi("10.1109/TPEL.2020.1"))


if __name__ == "__main__":
    unittest.main()
