import unittest

from scholarly_access_agent.runtime.pdf import derive_candidates_from_source


class DeriveCandidatesTests(unittest.TestCase):
    def test_aps_abstract_page_maps_to_pdf_endpoint(self):
        # APS pages expose no PDF link in the DOM; /<journal>/pdf/<DOI> serves the bytes.
        url = "https://journals.aps.org/prb/abstract/10.1103/PhysRevB.89.144303"
        hrefs = [c.href for c in derive_candidates_from_source(url, url)]
        self.assertEqual(hrefs, ["https://journals.aps.org/prb/pdf/10.1103/PhysRevB.89.144303"])

    def test_aps_proxied_host_keeps_proxy_origin(self):
        page = "https://journals-aps-org-ssl.example-proxy.ac.kr/prl/abstract/10.1103/PhysRevLett.62.645"
        hrefs = [c.href for c in derive_candidates_from_source(page, page)]
        self.assertEqual(hrefs, [])  # proxied host name differs; derivation relies on the original URL
        original = "https://journals.aps.org/prl/abstract/10.1103/PhysRevLett.62.645"
        hrefs = [c.href for c in derive_candidates_from_source(original, page)]
        self.assertIn("https://journals.aps.org/prl/pdf/10.1103/PhysRevLett.62.645", hrefs)


if __name__ == "__main__":
    unittest.main()
