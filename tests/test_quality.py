"""Source-quality checks: retraction, peer-review status, unverified journals, off-field outside finds, provenance
(offline: OpenAlex is mocked)."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scholarly_access_agent import quality, refs
from scholarly_access_agent.lineage import page, report, source_check

from test_lineage import LINEAGE, quiet, synthetic_corpus


def info(**kw):
    base = {"retracted": False, "type": "article", "source_type": "journal", "h_index": 120, "citedness": 3.1}
    return {**base, **kw}


class FlagTests(unittest.TestCase):
    def test_flags_are_data_driven(self):
        self.assertEqual(quality.flags_of(info()), [])
        self.assertEqual(quality.flags_of(info(source_type="conference", h_index=None)), [])  # refereed proceedings
        self.assertIn("retracted", quality.flags_of(info(retracted=True)))
        for t in ("preprint", "dissertation", "report"):
            self.assertIn("not_peer_reviewed", quality.flags_of(info(type=t)))
        self.assertIn("not_peer_reviewed", quality.flags_of(info(source_type="repository")))
        self.assertIn("venue_unverified", quality.flags_of(info(h_index=4, citedness=0.2)))
        self.assertNotIn("venue_unverified", quality.flags_of(info(h_index=4, citedness=2.5)))  # young, well cited

    def test_lookup_uses_works_and_sources_endpoints(self):
        calls = []

        def fake_get(params, endpoint="works", **kw):
            calls.append((endpoint, params["filter"]))
            if endpoint == "sources":
                return {"results": [{"id": "https://openalex.org/S1", "display_name": "Some Journal", "type": "journal",
                                     "summary_stats": {"h_index": 3, "2yr_mean_citedness": 0.1}}]}
            return {"results": [{"id": "https://openalex.org/W1", "doi": "https://doi.org/10.1/X", "type": "article",
                                 "is_retracted": True, "primary_location": {"source": {"id": "https://openalex.org/S1"}},
                                 "referenced_works": ["https://openalex.org/W9"]}]}
        with mock.patch.object(quality, "get", side_effect=fake_get):
            q = quality.lookup(dois=["https://doi.org/10.1/X"])
        self.assertEqual([c[0] for c in calls], ["works", "sources"])
        self.assertEqual(calls[0][1], "doi:10.1/x")
        got = q["by_doi"]["10.1/x"]
        self.assertEqual(set(got["flags"]), {"retracted", "venue_unverified"})
        self.assertEqual(got["referenced"], ["W9"])


class RefsCheckTests(unittest.TestCase):
    CR = {"title": ["Fatigue crack growth in welded joints"], "issued": {"date-parts": [[2021]]},
          "author": [{"family": "Kim"}], "container-title": ["International Journal of Fatigue"], "type": "journal-article"}

    def test_retracted_and_unverified_venue_are_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            d = Path(directory)
            rec = {"title": self.CR["title"][0], "year": 2021, "authors": "Kim", "venue": "Int. J. Fatigue 150, 1",
                   "venue_type": "journal"}
            (d / "a.json").write_text(json.dumps({**rec, "paper_id": "10.1016/j.ijfatigue.2021.106001"}), encoding="utf-8")
            (d / "b.json").write_text(json.dumps({**rec, "paper_id": "10.1016/j.ijfatigue.2021.106002"}), encoding="utf-8")
            fake = lambda dois: {"by_doi": {"10.1016/j.ijfatigue.2021.106001": {"flags": ["retracted"]},
                                            "10.1016/j.ijfatigue.2021.106002": {"flags": ["venue_unverified"], "venue": "Some Journal",
                                                       "h_index": 3, "citedness": 0.1}}}
            out = refs.check([d], fetch=lambda doi: self.CR, quality=fake)
            rows = {r["file"]: r for r in out["records"]}
            self.assertEqual(rows["a.json"]["status"], "retracted")
            self.assertEqual(rows["b.json"]["status"], "ok")  # the abbreviated venue matches; the journal is a prompt
            self.assertTrue(any("indexing" in i for i in rows["b.json"]["issues"]))
            self.assertEqual((out["summary"]["retracted"], out["summary"]["venue_unverified"]), (1, 1))
            failing = lambda dois: (_ for _ in ()).throw(RuntimeError("down"))
            out = refs.check([d], fetch=lambda doi: self.CR, quality=failing)
            self.assertTrue(all("retraction not checked" in " ".join(r["issues"]) for r in out["records"]))

    def test_iso_abbreviations_match_full_titles(self):
        self.assertTrue(refs._venue_match("J. Chem. Phys. 140, 214110", "The Journal of Chemical Physics"))
        self.assertTrue(refs._venue_match("Int. J. Fatigue", "International Journal of Fatigue"))
        self.assertTrue(refs._venue_match("IEEE Trans. Power Electron. 35", "IEEE Transactions on Power Electronics"))
        self.assertFalse(refs._venue_match("J. Chem. Phys.", "Journal of Applied Physics"))


class LineageQualityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name)
        (self.work / "data").mkdir()
        synthetic_corpus(self.work / "data")  # S cites A, B; F1..F6 cite S; core paper of the field: A
        L = json.loads(json.dumps(LINEAGE))
        L["nodes"] += [{"id": "x", "lane": 1, "year": 2026, "title": "Outside find", "sub": "X 2026", "openalex": "X1",
                        "key": True},
                       {"id": "t", "lane": 1, "year": 2026, "title": "Thesis", "sub": "T 2026", "evidence": "t2026",
                        "url": "https://example.org/t"}]
        self.L = L
        (self.work / "evidence").mkdir()
        (self.work / "evidence" / "t2026.json").write_text(json.dumps({"venue_type": "thesis", "access": "abstract_only"}),
                                                           encoding="utf-8")
        (self.work / "lineage.json").write_text(json.dumps(L, ensure_ascii=False), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_quality(self, x_info):
        by_id = {"A": info(referenced=[]), "B": info(), "S": info(), "F1": info(), "X1": x_info}
        for k, v in by_id.items():
            v.setdefault("referenced", [])
            v["flags"] = quality.flags_of(v)
        with mock.patch.object(source_check, "lookup", return_value={"by_id": by_id}), quiet():
            source_check.main([str(self.work)])
        return json.loads((self.work / "data" / "quality.json").read_text(encoding="utf-8"))["nodes"]

    def test_provenance_flags_warnings_page_and_report(self):
        nodes = self.run_quality(info(type="preprint", referenced=["Q7"]))  # outside, cites no core paper
        self.assertEqual(nodes["a"]["found"], "corpus")
        self.assertEqual(nodes["x"]["found"], "outside")
        self.assertEqual(set(nodes["x"]["flags"]), {"not_peer_reviewed", "off_field"})
        self.assertEqual(set(nodes["t"]["flags"]), {"not_peer_reviewed", "abstract_only"})
        warns, summary = source_check.quality_warnings(self.L, self.work)
        codes = {w.split(":")[0] for w in warns}
        self.assertEqual(codes, {"quality_key_preliminary", "quality_off_field"})
        self.assertIn("2 not peer-reviewed or read as abstract only", summary[0])
        # the page draws both preliminary boxes dashed and says so in the legend
        L = json.loads(json.dumps(self.L))
        self.assertEqual(page.mark_preliminary(L, self.work / "data"), 2)
        self.assertEqual(page.n_preprints(L, page.Links({}, None)), 2)
        self.assertIn("2개는 그 밖(웹 검색·원문 읽기)", report.quality_md(self.L, self.work)[0])
        # an outside find that cites the field's core is not off-field; a changed box is reported stale
        nodes = self.run_quality(info(referenced=["A"]))
        self.assertNotIn("off_field", nodes["x"]["flags"])
        self.L["nodes"][-2]["openalex"] = "X2"
        warns, _ = source_check.quality_warnings(self.L, self.work)
        self.assertTrue(any(w.startswith("quality_stale") for w in warns))

    def test_without_quality_file_check_says_not_checked(self):
        warns, summary = source_check.quality_warnings(self.L, self.work)
        self.assertEqual(warns, [])
        self.assertIn("not checked", summary[0])


if __name__ == "__main__":
    unittest.main()
