"""Measured search for plain reviews: expand saves a corpus, saturation needs precision, evidence coverage
summarises the search and the era balance of what was read (offline)."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scholarly_access_agent import coverage
from scholarly_access_agent.lineage import expand, query_test, searchlog

from test_lineage_expand import CITING, fake_many


class ExpandCorpusTests(unittest.TestCase):
    def run_main(self, out: Path):
        with mock.patch.object(expand, "fetch_many", side_effect=fake_many), \
                mock.patch.object(expand, "fetch_citing", side_effect=lambda s, n=None: CITING[s]), \
                mock.patch.object(expand, "resolve_seeds", side_effect=lambda seeds: seeds), \
                contextlib.redirect_stdout(io.StringIO()) as buf:
            expand.main(["W1", "W2", "--out", str(out)])
        return json.loads(buf.getvalue())

    def test_expansion_is_saved_as_a_corpus_without_overwriting_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "data" / "expansion.json"
            summary = self.run_main(out)
            corpus = json.loads((out.parent / "corpus.json").read_text(encoding="utf-8"))
            self.assertEqual(corpus["W1"]["_role"], ["seed"])
            self.assertEqual(corpus["W10"]["_role"], ["backward"])   # cited by both seeds
            self.assertEqual(corpus["W30"]["_role"], ["forward"])    # cites both seeds
            self.assertTrue(summary["corpus"].endswith("corpus.json"))
            (out.parent / "corpus.json").write_text('{"LINEAGE": {"_role": ["seed"]}}', encoding="utf-8")
            summary = self.run_main(out)
            self.assertIn("left unchanged", summary["corpus"])
            self.assertIn("LINEAGE", json.loads((out.parent / "corpus.json").read_text(encoding="utf-8")))


class SaturationTests(unittest.TestCase):
    def test_saturation_needs_precision(self):
        self.assertTrue(query_test.is_saturated([1], 0.05, 0.8))
        self.assertFalse(query_test.is_saturated([1], 0.05, 0.2))   # mostly off-topic results
        self.assertFalse(query_test.is_saturated([], 0.0, 0.9))
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "queries.json").write_text(json.dumps([
                {"label": "junk", "saturated": True, "precision": 0.2, "novelty": 0.05},
                {"label": "old", "saturated": True, "novelty": 0.05}]), encoding="utf-8")
            self.assertEqual(searchlog.saturation(d)["saturated"], ["old"])  # an older log without precision counts


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.topic = Path(self.tmp.name)
        (self.topic / "data").mkdir()
        (self.topic / "evidence").mkdir()
        corpus = {f"F{i}": {"publication_year": 2026 if i < 12 else 2012, "_role": ["forward"]} for i in range(40)}
        (self.topic / "data" / "corpus.json").write_text(json.dumps(corpus), encoding="utf-8")
        rows = ([{"openalex": f"A{i}", "doi": f"10.1000/a{i}", "title": f"Founding method {i}", "year": 1990 + i,
                  "links": 3, "cited_by": 500, "cited_by_seeds": ["S1", "S2"], "cites_seeds": []} for i in range(5)]
                + [{"openalex": f"R{i}", "doi": f"10.1000/r{i}", "title": f"Recent follow-up {i}", "year": 2026,
                    "links": 1, "score": 1.0, "cited_by_seeds": [], "cites_seeds": ["S1"]} for i in range(3)])
        (self.topic / "data" / "expansion.json").write_text(json.dumps({"rows": rows}), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def record(self, name, **kw):
        (self.topic / "evidence" / f"{name}.json").write_text(json.dumps(kw), encoding="utf-8")

    def test_unmeasured_search_and_both_eras_missing(self):
        self.record("old", paper_id="10.1000/other", title="Something else", year=2015)
        res = coverage.coverage(self.topic, today=2026)
        codes = [w.split(":")[0] for w in res["warnings"]]
        self.assertEqual(codes, ["search_not_measured", "era_recent_thin", "era_founders_thin"])
        self.assertEqual(len(res["era"]["founders_unread"]), 5)
        self.assertEqual(res["era"]["recent_unread"][0][1], "Recent follow-up 0")
        # the focus switches off only the other era's warning
        only = lambda f: [w.split(":")[0] for w in coverage.coverage(self.topic, f, 2026)["warnings"]]
        self.assertEqual(only("origin"), ["search_not_measured", "era_founders_thin"])
        self.assertEqual(only("current"), ["search_not_measured", "era_recent_thin"])

    def test_measured_search_and_read_records_clear_the_warnings(self):
        for i in range(3):
            self.record(f"a{i}", paper_id=f"https://doi.org/10.1000/A{i}", title=f"Founding method {i}", year=1990 + i)
        self.record("r0", title="Recent follow-up 0", year=2026)   # matched by title (no DOI in the record)
        self.record("r1", paper_id="10.1000/r1", year=2026)
        (self.topic / "data" / "queries.json").write_text(json.dumps([
            {"label": "q1", "precision": 0.8, "novelty": 0.06, "saturated": True, "gold_found_ids": ["G1"]}]),
            encoding="utf-8")
        (self.topic / "data" / "gold.json").write_text(json.dumps({"ids": ["G1", "G2"]}), encoding="utf-8")
        (self.topic / "data" / "anchor_checks.json").write_text(json.dumps([
            {"label": "q1", "dropped": '"topology optimization"', "state": "anchor"}]), encoding="utf-8")
        res = coverage.coverage(self.topic, today=2026)
        self.assertEqual([w.split(":")[0] for w in res["warnings"]], ["anchor_flagged"])
        self.assertEqual(res["search"]["strategy_recall"], "1/2")
        self.assertEqual(res["era"]["founders_read"], 3)
        self.assertIn("1/2 of the gold", coverage.text(res))


if __name__ == "__main__":
    unittest.main()
