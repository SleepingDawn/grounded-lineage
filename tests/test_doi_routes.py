import unittest
from email.message import Message
from unittest import mock
from urllib.error import HTTPError

from scholarly_access_agent.runtime import pdf


def redirect(url, location, code=302):
    headers = Message()
    headers["Location"] = location
    return HTTPError(url, code, "Found", headers, None)


class DoiResolveTests(unittest.TestCase):
    def test_doi_forms_resolve_through_redirect_hops(self):
        hops = {
            "https://doi.org/10.1103/PhysRevB.59.13707": "https://link.aps.org/doi/10.1103/PhysRevB.59.13707",
            "https://link.aps.org/doi/10.1103/PhysRevB.59.13707":
                "https://journals.aps.org/prb/abstract/10.1103/PhysRevB.59.13707",
        }
        opener = mock.Mock()
        opener.open.side_effect = lambda req, timeout: (_ for _ in ()).throw(
            redirect(req.full_url, hops[req.full_url]))
        with mock.patch.object(pdf, "build_opener", return_value=opener):
            for form in ("doi:10.1103/PhysRevB.59.13707", "10.1103/PhysRevB.59.13707",
                         "https://doi.org/10.1103/PhysRevB.59.13707"):
                self.assertEqual(pdf.resolve_doi_url(form),
                                 "https://journals.aps.org/prb/abstract/10.1103/PhysRevB.59.13707")

    def test_other_urls_and_failures_are_unchanged(self):
        url = "https://www.nature.com/articles/s41524-023-01033-4"
        self.assertEqual(pdf.resolve_doi_url(url), url)
        opener = mock.Mock()
        opener.open.side_effect = OSError("offline")
        with mock.patch.object(pdf, "build_opener", return_value=opener):
            self.assertEqual(pdf.resolve_doi_url("doi:10.1/x"), "doi:10.1/x")

    def test_aps_pdf_link_becomes_abstract_plus_pdf_url(self):
        src, pdf_url = pdf._split_pdf_endpoint("https://journals.aps.org/prb/pdf/10.1103/PhysRevB.59.13707", None)
        self.assertEqual(src, "https://journals.aps.org/prb/abstract/10.1103/PhysRevB.59.13707")
        self.assertEqual(pdf_url, "https://journals.aps.org/prb/pdf/10.1103/PhysRevB.59.13707")
        other = "https://pubs.acs.org/doi/pdf/10.1021/acs.jctc.9b01174"
        self.assertEqual(pdf._split_pdf_endpoint(other, None), (other, None))

    def test_aps_tries_derived_endpoint_before_the_page(self):
        ok = pdf.PdfDownloadResult(ok=True, provider="snu", source_url="s", status="downloaded", download_dir=".")
        with mock.patch.object(pdf, "_download_pdf_direct", return_value=ok) as direct, \
                mock.patch.object(pdf, "_download_via_playwright") as page:
            out = pdf.download_pdf("https://journals.aps.org/prb/abstract/10.1103/PhysRevB.59.13707")
        self.assertTrue(out.ok)
        self.assertEqual(direct.call_args.args[1], "https://journals.aps.org/prb/pdf/10.1103/PhysRevB.59.13707")
        page.assert_not_called()


if __name__ == "__main__":
    unittest.main()
