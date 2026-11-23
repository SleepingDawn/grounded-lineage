import json
import tempfile
import unittest
from pathlib import Path

from scholarly_access_agent import refs

CR = {"title": ["Is it expensive to be poor? Public transport in Sweden"], "issued": {"date-parts": [[2021]]},
      "author": [{"family": "Bondemark", "given": "Anders"}], "container-title": ["Transportation"],
      "type": "journal-article"}


class RefsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, record):
        (self.dir / name).write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")

    def test_matching_record_is_ok_and_venue_type_suggested(self):
        self.write("a.json", {"paper_id": "https://doi.org/10.1007/s11116-020-10145-5", "title": CR["title"][0],
                              "year": 2021, "authors": "Anders Bondemark; Henrik Andersson",
                              "venue": "Transportation", "venue_type": "journal"})
        out = refs.check([self.dir], fetch=lambda doi: CR)
        row = out["records"][0]
        self.assertEqual(row["status"], "ok", row["issues"])
        self.assertEqual(row["suggested_venue_type"], "journal")
        self.assertEqual(row["doi"], "10.1007/s11116-020-10145-5")

    def test_mismatches_are_reported(self):
        self.write("b.json", {"paper_id": "10.1007/x", "title": "A different paper altogether", "year": 2019,
                              "authors": [{"family": "Kim"}], "venue_type": "conference_abstract"})
        row = refs.check([self.dir], fetch=lambda doi: CR)["records"][0]
        self.assertEqual(row["status"], "mismatch")
        text = " ".join(row["issues"])
        for part in ("title differs", "year 2019", "first author", "venue_type"):
            self.assertIn(part, text)

    def test_no_doi_goes_to_manual_check_and_missing_venue_type_flagged(self):
        self.write("c.json", {"paper_id": "학술대회 발표 요약", "title": "기후동행카드가 지하철 역별 수요에 미친 영향"})
        row = refs.check([self.dir], fetch=lambda doi: CR)["records"][0]
        self.assertEqual(row["status"], "manual")
        self.assertTrue(any("venue_type" in i for i in row["issues"]))

    def test_venue_acronym_matches_full_name(self):
        self.write("f.json", {"paper_id": "10.1073/pnas.1", "venue": "PNAS 122(28) (2025)", "venue_type": "journal"})
        cr = {**CR, "container-title": ["Proceedings of the National Academy of Sciences"]}
        row = refs.check([self.dir], fetch=lambda doi: cr)["records"][0]
        self.assertFalse(any("venue" in i and "venue_type" not in i for i in row["issues"]), row["issues"])

    def test_unresolved_doi_and_offline(self):
        self.write("d.json", {"journal_version": "10.5555/nothing", "venue_type": "journal"})
        self.assertEqual(refs.check([self.dir], fetch=lambda doi: None)["records"][0]["status"], "not_found")
        self.assertEqual(refs.check([self.dir], offline=True)["records"][0]["status"], "skipped")

    def test_type_mapping_for_proceedings_and_preprints(self):
        self.write("e.json", {"paper_id": "10.1000/p", "venue_type": "journal"})
        row = refs.check([self.dir], fetch=lambda doi: {**CR, "type": "proceedings-article"})["records"][0]
        self.assertEqual(row["suggested_venue_type"], "conference_paper")
        self.assertEqual(refs.TYPE_TO_VENUE["posted-content"], "preprint")


if __name__ == "__main__":
    unittest.main()
