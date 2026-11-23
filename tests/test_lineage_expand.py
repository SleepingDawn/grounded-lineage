import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scholarly_access_agent.lineage import expand
from scholarly_access_agent.lineage.cli import main as lineage_main


def work(wid, year, cites, refs=(), doi=None, title=None):
    return {"id": f"https://openalex.org/{wid}", "doi": f"https://doi.org/{doi}" if doi else None,
            "title": title or wid, "publication_year": year, "cited_by_count": cites,
            "referenced_works": [f"https://openalex.org/{r}" for r in refs],
            "primary_location": {"source": {"display_name": "J"}}, "type": "article"}


# Two seeds. W10 is cited by both seeds; W30 cites both; W11 and W20 touch one seed each.
WORKS = {
    "W1": work("W1", 2020, 100, refs=["W10", "W11"]),
    "W2": work("W2", 2021, 50, refs=["W10"]),
    "W10": work("W10", 2010, 900, doi="10.1000/ten"),
    "W11": work("W11", 2015, 30, doi="10.1000/eleven"),
    "W20": work("W20", 2024, 4, doi="10.1000/twenty"),
    "W30": work("W30", 2023, 12, doi="10.1000/thirty"),
}
CITING = {"W1": {"W20": WORKS["W20"], "W30": WORKS["W30"]}, "W2": {"W30": WORKS["W30"]}}


def fake_many(ids, fields=None):
    return {i: WORKS[i] for i in ids if i in WORKS}


class ExpandTest(unittest.TestCase):
    def run_expand(self, **kw):
        with mock.patch.object(expand, "fetch_many", side_effect=fake_many), \
                mock.patch.object(expand, "fetch_citing", side_effect=lambda s, n=None: CITING[s]):
            return expand.expand(["W1", "W2"], **kw)

    def test_ranks_by_seed_links_then_citations_per_year(self):
        rows = self.run_expand()
        self.assertEqual([r["openalex"] for r in rows], ["W10", "W30", "W11", "W20"])
        top = rows[0]
        self.assertEqual(top["links"], 2)
        self.assertEqual(top["cited_by_seeds"], ["W1", "W2"])
        self.assertEqual(rows[1]["cites_seeds"], ["W1", "W2"])
        self.assertNotIn("W1", [r["openalex"] for r in rows])  # seeds are not candidates

    def test_known_papers_are_flagged_and_since_filters(self):
        rows = self.run_expand(since=2016, known=({"10.1000/thirty"}, set()))
        ids = {r["openalex"]: r["known"] for r in rows}
        self.assertEqual(set(ids), {"W30", "W20"})  # W10 (2010) and W11 (2015) dropped
        self.assertTrue(ids["W30"])
        self.assertFalse(ids["W20"])

    def test_known_keys_read_dois_arxiv_and_titles_from_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "a.json").write_text(json.dumps({"doi": "https://doi.org/10.1000/TEN"}), encoding="utf-8")
            Path(tmp, "b.json").write_text(json.dumps(
                {"papers": [{"title": "UMA: A Family of Universal Models", "url": "https://arxiv.org/abs/2506.23971"}]}),
                encoding="utf-8")
            dois, wids, titles = expand.known_keys([tmp, "W30", "10.1000/Eleven."])
        self.assertEqual(dois, {"10.1000/ten", "10.1000/eleven", "10.48550/arxiv.2506.23971"})
        self.assertEqual(wids, {"W30"})
        self.assertEqual(titles, {"uma a family of universal models"})

    def test_well_used_paper_outranks_uncited_one_with_one_more_link(self):
        works = {**WORKS, "W3": work("W3", 2022, 10),
                 "W40": work("W40", 2026, 0), "W41": work("W41", 2020, 3000)}
        citing = {"W1": {"W40": works["W40"], "W41": works["W41"]},
                  "W2": {"W40": works["W40"], "W41": works["W41"]}, "W3": {"W40": works["W40"]}}
        with mock.patch.object(expand, "fetch_many", side_effect=lambda ids, f=None: {i: works[i] for i in ids if i in works}), \
                mock.patch.object(expand, "fetch_citing", side_effect=lambda s, n=None: citing[s]):
            rows = expand.expand(["W1", "W2", "W3"], since=2019)
        order = [r["openalex"] for r in rows]
        self.assertLess(order.index("W41"), order.index("W40"))  # 2 links, ~430 cites/yr vs 3 links, none

    def test_known_by_title_when_record_has_no_doi(self):
        rows = self.run_expand(known=(set(), set(), {expand.norm_title("W20")}))
        self.assertTrue({r["openalex"]: r["known"] for r in rows}["W20"])

    def test_cli_hides_known_and_writes_full_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp, "data", "expansion.json")
            buf = io.StringIO()
            with mock.patch.object(expand, "resolve_dois", return_value={"10.1000/s1": "W1"}), \
                    mock.patch.object(expand, "fetch_many", side_effect=fake_many), \
                    mock.patch.object(expand, "fetch_citing", side_effect=lambda s, n=None: CITING[s]), \
                    contextlib.redirect_stdout(buf):
                code = lineage_main(["expand", "10.1000/S1", "W2", "--known", "10.1000/ten", "--out", str(out)])
            self.assertEqual(code, 0)
            shown = json.loads(buf.getvalue())
            self.assertEqual(shown["seeds"], ["W2", "W1"])
            self.assertNotIn("W10", [r["openalex"] for r in shown["rows"]])
            self.assertEqual((shown["new"], shown["known"]), (3, 1))
            saved = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(len(saved["rows"]), 4)

    def test_unknown_seed_doi_is_an_error(self):
        with mock.patch.object(expand, "resolve_dois", return_value={}), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(lineage_main(["expand", "10.1000/missing"]), 1)


if __name__ == "__main__":
    unittest.main()
