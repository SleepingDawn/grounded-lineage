import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scholarly_access_agent import cli, evidence, trace
from scholarly_access_agent.evidence import lint_record, verify_folder
from scholarly_access_agent.runtime import report

from test_reader import make_pdf


def rec(**fields):
    base = {"paper_id": "10.1103/PhysRevB.89.144303", "title": "Thermal conductivity of glass",
            "version": "publisher PDF", "access": "fulltext_pdf", "read_via": "read_pdf", "venue_type": "journal",
            "evidence_role": "empirical", "authors": "Jason M. Larkin; Alan J. H. McGaughey; Ada Third", "year": 2014,
            "venue": "Physical Review B",
            "criteria": [{"criterion": "kappa", "judgment": "met", "reason": "GK kappa 2.1 W/mK at 300 K",
                          "evidence": [{"pdf_page": 9, "section": "IV.A Results", "read_mode": "pages",
                                        "summary": "Table II lists 2.1 W/mK"}]}],
            "results": [{"id": "k300", "quantity": "kappa", "value": 1.40, "lo": None, "hi": None, "unit": "W/mK",
                         "condition": "350 K, bulk", "pdf_page": 5, "section": "§IV.A", "read_mode": "pages",
                         "verified_by": None},
                        {"id": "range", "quantity": "mfp", "value": "14-24", "unit": "nm", "section": "§V"}]}
    base.update(fields)
    return base


RECORDS = {
    "larkin2014": rec(),
    "kim2025": rec(authors=["Kim, Minsu", "Cheng, Bingqing"], year=2025, title="Two authors",
                   paper_id="arXiv:2501.00001", journal_version="10.1038/s41524-025-00001-1", results=[]),
    "lee2023": rec(authors="이도경 (Lee, Dokyung)", year=2023, title="Korean paper", results=[]),
    "solo2020": rec(authors=[{"family": "Petit", "given": "A."}], year=2020, results=[]),
}


def cite(text, records=RECORDS):
    return trace.render_citations(text, records)


class CitationRenderTests(unittest.TestCase):
    def test_single_and_locator(self):
        out, warnings = cite("κ is 1.4 [@larkin2014, p.9].\n")
        self.assertEqual(out, "κ is 1.4 (Larkin 외, 2014 [1], p.9).\n")
        self.assertEqual(warnings, [])

    def test_multiple_keys_and_numbering_by_first_citation(self):
        out, _ = cite("A [@kim2025; @larkin2014, §IV.A]. B [@larkin2014]. C [@solo2020].\n")
        self.assertEqual(out, "A (Kim & Cheng, 2025 [1]; Larkin 외, 2014 [2], §IV.A). B (Larkin 외, 2014 [2]). "
                              "C (Petit, 2020 [3]).\n")

    def test_korean_author_and_result_locator(self):
        out, _ = cite("가 [@lee2023]. 나 [@larkin2014#k300]. 다 [@larkin2014#range].\n")
        self.assertEqual(out, "가 (이도경, 2023 [1]). 나 (Larkin 외, 2014 [2], p.5). 다 (Larkin 외, 2014 [2], §V).\n")

    def test_references_table(self):
        out, _ = cite("x [@kim2025] y [@larkin2014].\n\n## 참고문헌\n\n<!-- references -->\n")
        table = out.split("## 참고문헌\n\n")[1]
        lines = table.splitlines()
        self.assertEqual(lines[0], "| 번호 | 문헌 | 읽은 판 | 근거 |")
        self.assertTrue(lines[2].startswith("| 1 | Two authors. *Physical Review B*. 2025. "
                                            "[doi:10.1038/s41524-025-00001-1](https://doi.org/10.1038/s41524-025-00001-1)"))
        self.assertIn("| publisher PDF | 본문 확인 (§IV.A p.9) |", lines[2])
        self.assertTrue(lines[3].startswith("| 2 | Thermal conductivity of glass."))
        self.assertNotIn("<!-- references -->", out)

    def test_unknown_key_is_kept_and_warned(self):
        out, warnings = cite("x [@nobody2020] and [@larkin2014#nope].\n")
        self.assertIn("[\\@nobody2020?]", out)
        self.assertEqual(warnings, ["citation_unknown_key: nobody2020", "citation_unknown_result: larkin2014#nope"])

    def test_code_untouched_and_plain_text_identical(self):
        text = "Use `[@larkin2014]` like this.\n\n```\n[@larkin2014]\n```\n\n[link](x) and [@ref](u) ![i](a.png)\n"
        out, warnings = cite(text)
        self.assertEqual(out, text)
        self.assertEqual(warnings, [])
        out, _ = cite("A `[@larkin2014]` B [@larkin2014].\n")
        self.assertEqual(out, "A `[@larkin2014]` B (Larkin 외, 2014 [1]).\n")

    def test_render_report_applies_pass_in_both_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "evidence").mkdir()
            (root / "evidence" / "larkin2014.json").write_text(json.dumps(rec()), encoding="utf-8")
            md = root / "report.md"
            md.write_text("# R\n\n## 요약\n\n- κ = 1.40 W/mK [@larkin2014#k300]\n- 3.3 W/mK [@ghost]\n",
                          encoding="utf-8")
            seen = {}

            def fake(source, output, text=None):
                seen["text"] = text
                return {"ok": True, "engine": "reportlab", "warnings": ["w0"]}

            with mock.patch.object(report, "_render_reportlab", side_effect=fake):
                result = report.render_report(md, engine="reportlab")
            self.assertIn("(Larkin 외, 2014 [1], p.5)", seen["text"])
            self.assertEqual(result["warnings"][0], "w0")
            self.assertIn("citation_unknown_key: ghost", result["warnings"])
            self.assertTrue(any(w.startswith("report_trace: 1 errors") for w in result["warnings"]))
            self.assertTrue(result["warnings"][-1].startswith("evidence_lint:"))

    def test_render_without_keys_passes_no_text(self):
        with tempfile.TemporaryDirectory() as directory:
            md = Path(directory) / "report.md"
            md.write_text("# R\n\n1.4 W/mK\n", encoding="utf-8")
            calls = []
            with mock.patch.object(report, "_render_reportlab",
                                   side_effect=lambda *a, **k: calls.append(k) or {"ok": True, "warnings": []}):
                result = report.render_report(md, engine="reportlab")
            self.assertEqual(calls, [{}])
            self.assertEqual(result["warnings"], [])


class TraceTests(unittest.TestCase):
    def rules(self, text, records=RECORDS):
        result = trace.trace_text(text, records)
        return [(f["level"], f["rule"]) for f in result["findings"]], result

    def test_unknown_key_is_error(self):
        found, result = self.rules("X is 1.4 [@ghost2020].\n")
        self.assertIn(("error", "unknown_key"), found)
        self.assertFalse(result["ok"])

    def test_number_found_and_not_found(self):
        found, result = self.rules("κ is 1.4 W/mK at 350 K [@larkin2014]. κ is 1.9 W/mK [@larkin2014].\n")
        self.assertEqual(found, [("warning", "number_not_in_record")])
        self.assertIn("1.9 not in larkin2014", result["findings"][0]["message"])
        self.assertEqual(result["sentences"][0]["numbers"][0], {"number": "1.4", "found_in": ["larkin2014"]})

    def test_number_cited_to_the_wrong_record(self):
        found, _ = self.rules("Martin found 1.40 W/mK [@kim2025].\n")
        self.assertEqual(found, [("warning", "number_not_in_record")])

    def test_range_decimal_and_tolerance(self):
        found, _ = self.rules("MFP spans 14–24 nm and κ ≈ 1.41 ± 2.1 [@larkin2014]. Also −1.400 [@larkin2014].\n")
        self.assertEqual(found, [])
        found, _ = self.rules("κ ≈ 1.45 [@larkin2014].\n")
        self.assertEqual(found, [("warning", "number_not_in_record")])

    def test_figures_years_and_formulas_are_not_values(self):
        found, _ = self.rules("In 2014 Fig. 3 of Bi2Te3 shows 1.4 (Larkin et al.) [@larkin2014].\n")
        self.assertEqual(found, [])

    def test_locator_checks(self):
        found, _ = self.rules("a [@larkin2014, p.9]. b [@larkin2014, §IV.A]. c [@larkin2014, p.5]. "
                              "d [@larkin2014, p.12]. e [@larkin2014#nope].\n")
        self.assertEqual(found, [("warning", "locator_not_in_record"), ("error", "unknown_result")])

    def test_uncited_number_only_in_summary(self):
        text = ("# T\n\n2026-11-23 · v1\n\n## 한눈에 보기\n\n- κ is 3.3 W/mK.\n- cited 1.4 [@larkin2014].\n\n"
                "| 항목 | 값 |\n|---|---|\n| κ | 7.7 |\n\n## Body\n\nκ is 9.9 W/mK.\n")
        found, result = self.rules(text)
        self.assertEqual(found, [("warning", "uncited_number"), ("warning", "uncited_number")])
        self.assertEqual([f["line"] for f in result["findings"]], [7, 12])

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "evidence").mkdir()
            (root / "evidence" / "larkin2014.json").write_text(json.dumps(rec()), encoding="utf-8")
            md = root / "report.md"
            md.write_text("ok 1.4 [@larkin2014].\n", encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(cli.main(["report", "trace", str(md)]), 0)
            md.write_text("bad [@ghost].\n", encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(cli.main(["report", "trace", str(md), "--json"]), 1)
            self.assertEqual(json.loads(out.getvalue())["summary"]["errors"], 1)


class ResultsLintTests(unittest.TestCase):
    def test_clean_results(self):
        self.assertEqual(lint_record(rec(), "r.json"), [])

    def test_missing_fields(self):
        bad = rec(results=[{"id": "a", "value": None}, {"id": "a", "quantity": "q", "value": 1, "unit": "",
                                                        "pdf_page": 2}, "x"])
        found = {f["rule"] for f in lint_record(bad, "r.json") if f["level"] == "error"}
        self.assertEqual(found, {"result_missing_quantity", "result_missing_value", "result_missing_unit",
                                 "result_without_locator", "result_duplicate_id", "result_not_an_object"})

    def test_results_need_body_or_excerpt_reading(self):
        found = lint_record(rec(access="abstract_only", criteria=[]), "r.json")
        self.assertIn("results_without_reading", {f["rule"] for f in found if f["level"] == "warning"})


class VerifyTests(unittest.TestCase):
    def make_topic(self, root):
        (root / "evidence").mkdir()
        (root / "pdfs").mkdir()
        make_pdf(root / "pdfs" / "larkin.pdf", ["Intro.", "Methods.", "Results.", "More.",
                                                "Table: kappa = 1.40 W/mK at 350 K."])
        record = rec(source_file="pdfs/larkin.pdf")
        record["results"].append({"id": "bad", "quantity": "kappa", "value": 3.3, "unit": "W/mK", "pdf_page": 5})
        (root / "evidence" / "larkin2014.json").write_text(json.dumps(record), encoding="utf-8")
        (root / "evidence" / "kim2025.json").write_text(json.dumps(rec()), encoding="utf-8")

    def test_verify_and_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_topic(root)
            result = verify_folder(root)
            status = {(r["kind"], r["id"]): r["status"] for r in result["checks"]}
            self.assertEqual(status[("result", "k300")], "ok")
            self.assertEqual(status[("result", "bad")], "missing")
            self.assertEqual(status[("result", "range")], "skipped")
            self.assertEqual(status[("locator", "§IV.A p.9")], "error")  # the PDF has 5 pages
            self.assertIn("kim2025: skipped (no source_file)", result["notes"])
            self.assertFalse(result["ok"])
            self.assertEqual(result["written"], [])

            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli.main(["evidence", "verify", str(root), "--record", "larkin2014", "--write"])
            self.assertEqual(code, 1)
            self.assertIn("missing", out.getvalue())
            data = json.loads((root / "evidence" / "larkin2014.json").read_text(encoding="utf-8"))
            k300, rng, bad = data["results"]
            self.assertEqual(k300["verified_by"]["method"], "read_pdf p.5")
            self.assertTrue(k300["verified_by"]["ok"])
            self.assertFalse(bad["verified_by"]["ok"])
            self.assertNotIn("verified_by", rng)
            self.assertIn('"title": "Thermal conductivity of glass"', (root / "evidence" / "larkin2014.json")
                          .read_text(encoding="utf-8"))

    def test_lint_warns_on_missing_source_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "evidence").mkdir()
            (root / "evidence" / "a.json").write_text(json.dumps(rec(source_file="pdfs/none.pdf")), encoding="utf-8")
            found = evidence.lint_folder(root)["findings"]
            self.assertIn("source_file_missing", {f["rule"] for f in found})


if __name__ == "__main__":
    unittest.main()
