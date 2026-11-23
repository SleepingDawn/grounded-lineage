from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest import mock
from urllib.error import URLError

from scholarly_access_agent import resolve as R

DOI = "10.1103/PhysRevB.99.014104"
DOMAINS = ("journals.aps.org", "sciencedirect.com", "*.elsevier.com")

CROSSREF = {"message": {
    "title": ["Machine-learned potentials for oxides"],
    "author": [{"given": "Ana", "family": "Kim"}, {"given": "B", "family": "Lee"}],
    "issued": {"date-parts": [[2019, 1, 7]]},
    "container-title": ["Physical Review B"], "type": "journal-article", "publisher": "APS",
    "resource": {"primary": {"URL": "https://link.aps.org/doi/10.1103/PhysRevB.99.014104"}},
    "link": [{"URL": "https://journals.aps.org/prb/pdf/10.1103/PhysRevB.99.014104",
              "content-type": "application/pdf", "intended-application": "similarity-checking"},
             {"URL": "https://example.org/xml", "content-type": "text/xml"}],
    "relation": {"has-preprint": [{"id-type": "doi", "id": "10.48550/arXiv.1809.01234"}]},
}}

UNPAYWALL = {"is_oa": True, "oa_status": "green", "oa_locations": [
    {"host_type": "repository", "version": "submittedVersion", "license": None,
     "url": "http://arxiv.org/abs/1809.01234", "url_for_pdf": "http://arxiv.org/pdf/1809.01234"},
    {"host_type": "repository", "version": "publishedVersion", "license": "cc-by",
     "url": "https://dspace.example.edu/handle/1721.1/555", "url_for_pdf": None,
     "repository_institution": "Example University"},
    {"host_type": "repository", "version": "acceptedVersion", "license": None,
     "url": "https://eprints.example.ac.uk/77/", "url_for_pdf": "https://eprints.example.ac.uk/77/1/am.pdf"},
]}

DSPACE = {
    "https://dspace.example.edu/server/api/pid/find?id=1721.1/555":
        {"_links": {"bundles": {"href": "https://dspace.example.edu/server/api/core/items/u1/bundles"}}},
    "https://dspace.example.edu/server/api/core/items/u1/bundles": {"_embedded": {"bundles": [
        {"name": "LICENSE", "_links": {"bitstreams": {"href": "https://dspace.example.edu/lic"}}},
        {"name": "ORIGINAL", "_links": {"bitstreams": {"href": "https://dspace.example.edu/orig"}}}]}},
    "https://dspace.example.edu/orig": {"_embedded": {"bitstreams": [
        {"name": "data.zip", "_links": {"content": {"href": "https://dspace.example.edu/bs/zip/content"}}},
        {"name": "paper.pdf", "_links": {"content": {"href": "https://dspace.example.edu/bs/pdf/content"}}}]}},
}


def fake_fetch(table):
    calls = []

    def fetch(url):
        calls.append(url)
        if url.startswith(R.CROSSREF):
            value = table.get("crossref")
        elif url.startswith(R.UNPAYWALL):
            value = table.get("unpaywall")
        else:
            value = table.get(url)
        if isinstance(value, Exception):
            raise value
        if value is None:
            raise URLError("not found")
        return value
    fetch.calls = calls
    return fetch


class NormalizeTests(unittest.TestCase):
    def test_accepts_doi_forms(self):
        for text in (DOI, "doi:" + DOI, "https://doi.org/" + DOI, "https://dx.doi.org/10.1103%2FPhysRevB.99.014104"):
            with self.subTest(text=text):
                self.assertEqual(R.normalize_doi(text), DOI)
        with self.assertRaises(ValueError):
            R.normalize_doi("not a doi")

    def test_arxiv_ids(self):
        self.assertEqual(R.arxiv_from("10.48550/arXiv.1809.01234"), "1809.01234")
        self.assertEqual(R.arxiv_from("https://arxiv.org/pdf/1809.01234v2.pdf"), "1809.01234")
        self.assertIsNone(R.arxiv_from("https://example.org/abs/1809.01234"))


class ResolveTests(unittest.TestCase):
    def run_resolve(self, table, landing="https://journals.aps.org/prb/abstract/" + DOI, domains=DOMAINS):
        fetch = fake_fetch(table)
        result = R.resolve("doi:" + DOI, fetch=fetch, landing=lambda doi: landing, domains=domains)
        return result, fetch

    def test_full_ranking_with_dspace_and_aps(self):
        table = {"crossref": CROSSREF, "unpaywall": UNPAYWALL, **DSPACE}
        result, fetch = self.run_resolve(table)
        self.assertTrue(result["ok"])
        self.assertEqual(result["errors"], {})
        cr = result["crossref"]
        self.assertEqual((cr["title"], cr["first_author_family"], cr["year"], cr["venue_type"], cr["publisher"]),
                         ("Machine-learned potentials for oxides", "Kim", 2019, "journal", "APS"))
        self.assertEqual([link["url"] for link in cr["pdf_links"]],
                         ["https://journals.aps.org/prb/pdf/10.1103/PhysRevB.99.014104"])
        self.assertEqual(cr["arxiv_ids"], ["1809.01234"])
        locations = result["unpaywall"]["locations"]
        self.assertEqual([loc["best_published"] for loc in locations], [False, True, False])

        kinds = [(r["rank"], r["kind"]) for r in result["routes"]]
        self.assertEqual(kinds, [(1, "published_open"), (2, "subscription"), (3, "accepted_manuscript"), (4, "preprint")])
        dspace, aps, accepted, arxiv = result["routes"]
        self.assertEqual(dspace["tool"], "download_pdf")
        self.assertEqual(dspace["url"], "https://dspace.example.edu/handle/1721.1/555")
        self.assertEqual(dspace["pdf_url"], "https://dspace.example.edu/bs/pdf/content")
        self.assertFalse(dspace["in_snu_domains"])
        self.assertIn("needs add_domain (user approval)", dspace["note"])
        self.assertEqual((aps["tool"], aps["url"]), ("download_pdf", "https://journals.aps.org/prb/abstract/" + DOI))
        self.assertEqual(accepted["pdf_url"], "https://eprints.example.ac.uk/77/1/am.pdf")
        self.assertEqual((arxiv["tool"], arxiv["url"]), ("read_url", "https://arxiv.org/abs/1809.01234"))
        self.assertIn("journal version has an open copy", arxiv["preprint_fallback_reason"])
        # Crossref's has-preprint relation duplicates the Unpaywall arXiv copy: listed once.
        self.assertEqual(sum(1 for r in result["routes"] if r.get("arxiv_id")), 1)
        unpaywall_call = next(c for c in fetch.calls if c.startswith(R.UNPAYWALL))
        self.assertIn("email=unpaywall-client%40example.org", unpaywall_call)

    def test_elsevier_subscription_is_policy_blocked_and_preprint_reason_says_so(self):
        table = {"crossref": CROSSREF, "unpaywall": {"is_oa": True, "oa_locations": [UNPAYWALL["oa_locations"][0]]}}
        result, _ = self.run_resolve(table, landing="https://linkinghub.elsevier.com/retrieve/pii/S0001")
        kinds = [r["kind"] for r in result["routes"]]
        self.assertEqual(kinds, ["preprint", "subscription_blocked"])
        self.assertEqual(result["routes"][1]["policy"], R.POLICY_BLOCKED)
        self.assertNotIn("tool", result["routes"][1])
        self.assertIn("publisher policy", result["routes"][0]["preprint_fallback_reason"])

    def test_duplicate_arxiv_locations_and_doi_links_collapse(self):
        arxiv = [{"host_type": "repository", "version": v, "url": u, "url_for_pdf": None}
                 for v, u in ((None, "https://doi.org/10.48550/arxiv.1809.01234"),
                              ("submittedVersion", "http://arxiv.org/abs/1809.01234"),
                              ("submittedVersion", "https://arxiv.org/pdf/1809.01234v1"))]
        dataset = {"host_type": "repository", "version": None, "url": "https://doi.org/10.17632/abc.1"}
        published = {"host_type": "publisher", "version": "publishedVersion", "license": "cc-by",
                     "url": "https://www.nature.com/articles/x.pdf", "url_for_pdf": "https://www.nature.com/articles/x.pdf"}
        table = {"crossref": CROSSREF, "unpaywall": {"oa_locations": [published, *arxiv, dataset]}}
        result, _ = self.run_resolve(table, landing="https://www.nature.com/articles/x",
                                     domains=DOMAINS + ("nature.com",))
        routes = result["routes"]
        self.assertEqual([r["kind"] for r in routes], ["published_open", "other_open_copy", "preprint"])
        self.assertTrue(routes[0]["in_snu_domains"])
        self.assertIn("resolve it to the repository page", routes[1]["note"])

    def test_sources_failing_are_recorded_not_raised(self):
        table = {"crossref": URLError("down"), "unpaywall": ValueError("bad json")}

        def boom(doi):
            raise OSError("offline")
        result = R.resolve(DOI, fetch=fake_fetch(table), landing=boom, domains=DOMAINS)
        self.assertFalse(result["ok"])
        self.assertEqual(result["errors"], {"crossref": "URLError", "unpaywall": "ValueError", "landing": "OSError"})
        self.assertEqual(result["routes"], [])

    def test_unresolved_landing_falls_back_to_crossref_resource(self):
        table = {"crossref": CROSSREF, "unpaywall": {"oa_locations": []}}
        result, _ = self.run_resolve(table, landing="https://doi.org/" + DOI)
        self.assertEqual(result["errors"], {"landing": "unresolved"})
        sub = [r for r in result["routes"] if r["kind"].startswith("subscription")]
        self.assertEqual(sub[0]["landing_url"], "https://link.aps.org/doi/10.1103/PhysRevB.99.014104")

    def test_dspace_lookup_failure_keeps_handle_route(self):
        table = {"crossref": CROSSREF, "unpaywall": {"oa_locations": [UNPAYWALL["oa_locations"][1]]}}
        result, _ = self.run_resolve(table, domains=DOMAINS + ("dspace.example.edu",))
        route = result["routes"][0]
        self.assertEqual((route["kind"], route["tool"]), ("published_open", "download_pdf"))
        self.assertNotIn("pdf_url", route)
        self.assertTrue(route["in_snu_domains"])
        self.assertIn("bitstream not found", route["note"])
        self.assertIn("dspace:dspace.example.edu", result["errors"])

    def test_publisher_hints(self):
        cases = {
            "https://pubs.acs.org/doi/10.1021/x": ("download_pdf", R.BOT_CHECK),
            "https://pubs.aip.org/aip/jcp/article/1/1": ("download_pdf", R.BOT_CHECK),
            "https://www.nature.com/articles/s1": (None, None),
            "https://pmc.ncbi.nlm.nih.gov/articles/PMC1/": ("read_url", None),
            "https://unknown.example.com/a": (None, "host not in the snu-library domain list; needs add_domain (user approval)"),
        }
        for url, (tool, note) in cases.items():
            with self.subTest(url=url):
                hint = R.publisher_hint(url, DOMAINS)
                self.assertEqual(hint.get("tool"), tool)
                self.assertEqual(hint.get("note"), note)
        self.assertEqual(R.publisher_hint("https://link.springer.com/article/1", DOMAINS)["policy"], R.POLICY_BLOCKED)
        self.assertEqual(R.publisher_hint("https://arxiv.org/pdf/2101.00001v1", DOMAINS)["url"],
                         "https://arxiv.org/abs/2101.00001")

    def test_arxiv_doi_without_crossref_record(self):
        table = {"unpaywall": {"oa_locations": []}}
        fetch = fake_fetch(table)
        result = R.resolve("10.48550/arXiv.2101.00001", fetch=fetch,
                           landing=lambda doi: "https://arxiv.org/abs/2101.00001", domains=DOMAINS)
        self.assertTrue(result["ok"])
        # The landing page and the DOI's own preprint route are the same arXiv page: listed once.
        self.assertEqual([(r["kind"], r["url"]) for r in result["routes"]],
                         [("landing_open", "https://arxiv.org/abs/2101.00001")])

    def test_cli_json_and_table(self):
        fake = {"ok": True, "doi": DOI, "landing_url": None, "crossref": None, "unpaywall": None, "errors": {},
                "routes": [{"rank": 1, "kind": "preprint", "version": "submittedVersion", "tool": "read_url",
                            "url": "https://arxiv.org/abs/1809.01234", "preprint_fallback_reason": "x"}]}
        from scholarly_access_agent import cli
        with mock.patch.object(R, "resolve", return_value=fake) as patched:
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(cli.main(["resolve", DOI, "--json", "--email", "a@b.org"]), 0)
            self.assertEqual(json.loads(out.getvalue())["routes"][0]["tool"], "read_url")
            self.assertEqual(patched.call_args.kwargs["email"], "a@b.org")
            out = io.StringIO()
            with redirect_stdout(out):
                cli.main(["resolve", DOI])
            self.assertIn("read_url", out.getvalue())
            self.assertIn("fallback: x", out.getvalue())


if __name__ == "__main__":
    unittest.main()
