import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scholarly_access_agent import cli, evidence
from scholarly_access_agent.evidence import derive_label, derive_verdict, lint_folder, lint_record
from scholarly_access_agent.runtime import report


def rec(**fields):
    base = {"paper_id": "10.1103/PhysRevB.1.1", "title": "A paper", "version": "publisher PDF",
            "access": "fulltext_pdf", "read_via": "read_pdf", "venue_type": "journal", "evidence_role": "empirical",
            "criteria": [{"criterion": "c", "evidence": [{"pdf_page": 5, "section": "IV.A Results", "summary": "s"}]}]}
    base.update(fields)
    return base


def locs(*items):
    return [{"criterion": "c", "evidence": list(items)}]


def rules(findings, level=None):
    return {f["rule"] for f in findings if level is None or f["level"] == level}


class LabelTests(unittest.TestCase):
    def test_fulltext_with_read_via_and_locator_is_body(self):
        result = derive_label(rec())
        self.assertEqual(result["label"], "본문 확인")
        self.assertEqual(result["locator"], "§IV.A p.5")

    def test_fulltext_with_body_read_mode(self):
        record = rec(read_via=None, criteria=locs({"section": "Methods", "read_mode": "sections"}))
        self.assertEqual(derive_label(record)["label"], "본문 확인")
        self.assertEqual(derive_label(record)["locator"], "§Methods")

    def test_fulltext_terms_only_is_excerpts_and_warns(self):
        record = rec(criteria=locs({"pdf_page": 3, "read_mode": "terms"}, {"pdf_page": 4, "read_mode": "caption"}))
        self.assertEqual(derive_label(record)["label"], "발췌 확인")
        self.assertIn("fulltext_terms_only", rules(lint_record(record, "x.json"), "warning"))

    def test_fulltext_without_read_via_or_read_mode_is_not_body(self):
        self.assertEqual(derive_label(rec(access="fulltext", read_via=None))["label"], "발췌 확인")

    def test_other_access_levels(self):
        self.assertEqual(derive_label(rec(access="excerpts"))["label"], "발췌 확인")
        secondary = rec(access="secondary", read_via="citing_paper",
                        criteria=locs({"section": "II", "read_mode": "citing"}))
        self.assertEqual(derive_label(secondary)["label"], "인용 맥락만")
        self.assertEqual(derive_label(rec(access="abstract_only", criteria=[]))["label"], "초록만 확인")
        self.assertEqual(derive_label(rec(access="unavailable", criteria=[]))["label"], "미확인")
        self.assertEqual(derive_label(rec(access=None))["label"], "미확인")


class LintTests(unittest.TestCase):
    def test_clean_record_has_no_errors_or_warnings(self):
        self.assertEqual(lint_record(rec(), "x.json"), [])

    def test_missing_ids_and_access(self):
        found = rules(lint_record(rec(paper_id="", title=None, access=None), "x.json"), "error")
        self.assertTrue({"missing_paper_id", "missing_title", "access_missing"} <= found)
        self.assertIn("access_invalid", rules(lint_record(rec(access="full"), "x.json"), "error"))

    def test_legacy_fulltext_is_warning(self):
        findings = lint_record(rec(access="fulltext"), "x.json")
        self.assertIn("access_legacy_fulltext", rules(findings, "warning"))
        self.assertEqual(rules(findings, "error"), set())

    def test_fulltext_without_locator(self):
        record = rec(criteria=locs({"summary": "no place"}))
        self.assertIn("fulltext_without_locator", rules(lint_record(record, "x.json"), "error"))

    def test_abstract_with_pdf_page(self):
        record = rec(access="abstract_only")
        self.assertIn("pdf_page_without_fulltext", rules(lint_record(record, "x.json"), "error"))

    def test_web_summary_fulltext(self):
        record = rec(access="fulltext_html", read_via="web_summary")
        self.assertIn("web_summary_fulltext", rules(lint_record(record, "x.json"), "error"))

    def test_preprint_with_journal_doi(self):
        record = rec(version="arXiv 2401.11427v2 (HTML)", access="fulltext_html", read_via="read_url")
        self.assertIn("preprint_without_reason", rules(lint_record(record, "x.json"), "error"))
        ok = dict(record, preprint_fallback_reason="access_restricted")
        self.assertNotIn("preprint_without_reason", rules(lint_record(ok, "x.json")))
        retried = dict(record, route="Fell back to arXiv. Journal retry 2026-11-23: still 403.")
        found = lint_record(retried, "x.json")
        self.assertNotIn("preprint_without_reason", rules(found))
        self.assertIn("preprint_reason_in_route", rules(found, "warning"))
        publisher = rec(version="publisher PDF (APS); journal version read, arXiv fallback not needed")
        self.assertNotIn("preprint_without_reason", rules(lint_record(publisher, "x.json")))
        arxiv_only = rec(paper_id="arXiv:2607.11384", version="preprint", access="excerpts")
        self.assertNotIn("preprint_without_reason", rules(lint_record(arxiv_only, "x.json")))

    def test_warnings_and_preliminary_info(self):
        found = lint_record(rec(read_via=None, venue_type=None, evidence_role=None), "x.json")
        self.assertTrue({"read_via_missing", "venue_type_missing", "evidence_role_missing"} <= rules(found, "warning"))
        self.assertIn("read_via_unknown", rules(lint_record(rec(read_via="browser"), "x.json"), "warning"))
        prelim = lint_record(rec(venue_type="conference_abstract"), "x.json")
        self.assertIn("preliminary_evidence", rules(prelim, "info"))
        self.assertIn("예비 근거", prelim[-1]["message"])
        self.assertIn("preliminary_evidence", rules(lint_record(rec(access="excerpts"), "x.json"), "info"))


class NoveltyTests(unittest.TestCase):
    def close(self, grade, access="fulltext_pdf", read_via="read_pdf"):
        return {"paper_id": f"p-{grade}", "grade": grade, "access": access, "read_via": read_via}

    def test_derivation(self):
        self.assertEqual(derive_verdict({"closest": [self.close("Exact"), self.close("High")]})[0], "not-novel")
        self.assertEqual(derive_verdict({"closest": [self.close("High"), self.close("Low")]})[0], "reframe")
        medium_web = self.close("Medium", "abstract_only", "web_summary")
        self.assertEqual(derive_verdict({"closest": [self.close("Medium"), medium_web]})[0], "provisional")
        self.assertEqual(derive_verdict({"closest": [self.close("Medium"), self.close("Low", "abstract_only")]})[0],
                         "novel")
        self.assertEqual(derive_verdict({"closest": [self.close("Medium", "fulltext_html", "web_summary")]})[0],
                         "provisional")
        self.assertEqual(derive_verdict({"closest": [self.close("unknown"), self.close("Low")]})[0], "provisional")

    def test_mismatch_is_error_and_reframed_accepted(self):
        record = {"card": "C1", "verdict": "novel",
                  "closest": [self.close("Medium", "abstract_only", "web_summary")]}
        found, row = evidence.lint_novelty(record, "C1.json")
        self.assertIn("novelty_verdict_mismatch", rules(found, "error"))
        self.assertEqual(row["derived"], "provisional")
        rewritten = {"card": "C3b", "verdict": "reframe", "reframed_from": "C3", "closest": [self.close("Medium")]}
        self.assertEqual(rules(evidence.lint_novelty(rewritten, "C3b.json")[0], "error"), set())


class FolderAndCliTests(unittest.TestCase):
    def make_topic(self, root: Path, bad=True):
        (root / "evidence").mkdir()
        (root / "ideas" / "novelty").mkdir(parents=True)
        (root / "evidence" / "good.json").write_text(json.dumps(rec()), encoding="utf-8")
        (root / "evidence" / "abs.json").write_text(
            json.dumps(rec(access="abstract_only", criteria=[], title="Abstract paper")), encoding="utf-8")
        if bad:
            (root / "evidence" / "broken.json").write_text("{not json", encoding="utf-8")
        (root / "ideas" / "novelty" / "C1.json").write_text(json.dumps(
            {"card": "C1", "verdict": "novel", "closest": [{"paper_id": "x", "grade": "Low",
                                                            "access": "fulltext_pdf", "read_via": "read_pdf"}]}),
            encoding="utf-8")

    def run_cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["evidence", *args])
        return code, out.getvalue()

    def test_lint_folder_and_exit_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_topic(root)
            result = lint_folder(root)
            self.assertEqual(result["summary"]["errors"], 1)
            self.assertIn("invalid_json", rules(result["findings"], "error"))
            self.assertEqual(result["summary"]["novelty_records"], 1)
            code, text = self.run_cli("lint", str(root), "--json")
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(text)["summary"]["errors"], 1)
            code, text = self.run_cli("lint", str(root / "evidence"))
            self.assertEqual(code, 1)
            self.assertIn("invalid_json", text)
            (root / "evidence" / "broken.json").unlink()
            self.assertEqual(self.run_cli("lint", str(root))[0], 0)
            self.assertEqual(self.run_cli("lint", str(root / "missing"))[0], 2)

    def test_labels_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_topic(root, bad=False)
            code, text = self.run_cli("labels", str(root), "--markdown")
            self.assertEqual(code, 0)
            self.assertIn("| good.json | A paper | 본문 확인 | §IV.A p.5 | journal |", text)
            self.assertIn("초록만 확인", text)
            code, text = self.run_cli("labels", str(root))
            self.assertEqual(code, 0)
            self.assertIn("본문 확인", text)


class RenderHookTests(unittest.TestCase):
    def fake_render(self, *args, **kwargs):
        return {"ok": True, "engine": "reportlab", "warnings": ["no_korean_font"]}

    def test_render_adds_lint_summary(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(report, "_render_reportlab", side_effect=self.fake_render):
            root = Path(directory)
            (root / "evidence").mkdir()
            (root / "evidence" / "bad.json").write_text(json.dumps(rec(access="full")), encoding="utf-8")
            (root / "ideas").mkdir()
            for md in (root / "report.md", root / "ideas" / "README.md"):
                md.write_text("# Report\n\ntext\n", encoding="utf-8")
                result = report.render_report(md, engine="reportlab")
                self.assertTrue(result["ok"])
                self.assertEqual(result["warnings"][0], "no_korean_font")
                self.assertTrue(any(w.startswith("evidence_lint error: evidence/bad.json access_invalid")
                                    for w in result["warnings"]))
                self.assertTrue(result["warnings"][-1].startswith("evidence_lint: 1 errors, 0 warnings"))
                self.assertIn("scholarly-access-agent evidence lint", result["warnings"][-1])

    def test_render_without_evidence_or_with_lint_crash(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(report, "_render_reportlab", side_effect=self.fake_render):
            md = Path(directory) / "report.md"
            md.write_text("# Report\n", encoding="utf-8")
            self.assertEqual(report.render_report(md, engine="reportlab")["warnings"], ["no_korean_font"])
            (Path(directory) / "evidence").mkdir()
            with mock.patch.object(evidence, "lint_folder", side_effect=RuntimeError("boom")):
                result = report.render_report(md, engine="reportlab")
            self.assertTrue(result["ok"])
            self.assertEqual(result["warnings"][-1], "evidence_lint_failed: RuntimeError")


if __name__ == "__main__":
    unittest.main()
