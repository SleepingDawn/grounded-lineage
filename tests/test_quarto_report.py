import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image as PILImage
from pypdf import PdfReader

from scholarly_access_agent.runtime import quarto_report as qr
from scholarly_access_agent.runtime.report import render_report

from test_report import SAMPLE


class PrepareTests(unittest.TestCase):
    def test_title_and_metadata_line_leave_the_body(self):
        title, subtitle, body = qr.split_front("# 제목 \"A\"\n\n2026-11-23 · v1\n\n## 요약\n\n- x\n")
        self.assertEqual((title, subtitle), ('제목 "A"', "2026-11-23 · v1"))
        self.assertEqual(body[0], "## 요약")

    def test_heading_right_after_title_means_no_subtitle(self):
        title, subtitle, body = qr.split_front("# T\n## S\n")
        self.assertEqual((title, subtitle, body), ("T", "", ["## S"]))

    def test_short_columns_keep_their_longest_token_unwrapped(self):
        lines = ["| 계열 | 시기 | 대표 연구 |", "| --- | :---: | --- |",
                 "| 고전 정전기 | 1921–2025 | " + "아주 긴 설명 문장이 계속 이어집니다 " * 6 + "|"]
        sep = qr.size_tables(lines)[1]
        cols = [c for c in sep.strip("|").split("|")]
        self.assertTrue(cols[1].startswith(":") and cols[1].endswith(":"))  # alignment kept
        share = len(cols[1]) / sum(len(c) for c in cols)
        self.assertGreater(share, 11 / 88)  # "1921–2025" (9 units) + padding fits on one line

    def test_images_html_and_breaks_are_made_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "figs").mkdir()
            PILImage.new("RGB", (4, 4)).save(root / "figs/ok.png")
            body, warnings = qr.prepare_body([
                "H<sub>2</sub>O and Å<sup>3</sup>", "| a<br>b | c |", "line<br>next",
                "![ok](figs/ok.png)", "![r](https://example.com/a.png)", "![o](../outside.png)",
                "![m](figs/missing.png)"], root)
        text = "\n".join(body)
        self.assertIn("H~2~O and Å^3^", text)
        self.assertIn("| a b | c |", text)
        self.assertIn("line\\\nnext", text)
        self.assertIn("![ok](figs/ok.png)", text)
        self.assertNotIn("example.com", text)
        self.assertNotIn("outside.png", text)
        self.assertEqual([w.split(":")[0] for w in warnings], [
            "image_skipped_remote", "image_skipped_outside_report_folder",
            "image_skipped_unsupported_or_missing (use PNG/JPG)"])

    def test_interactive_figure_becomes_an_inline_frame_in_html_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "figs").mkdir()
            PILImage.new("RGB", (4, 4)).save(root / "figs/lineage.png")
            (root / "les.html").write_text('<html><body><a href="x?a=1&b=2">"box"</a></body></html>', encoding="utf-8")
            line = '![계보도](figs/lineage.png "interactive=les.html")'
            html_body, html_warn = qr.prepare_body([line], root, interactive=True)
            pdf_body, pdf_warn = qr.prepare_body([line], root, interactive=False)
            gone, gone_warn = qr.prepare_body(['![g](figs/lineage.png "interactive=../x.html")'], root, interactive=True)
        html = "\n".join(html_body)
        self.assertIn("```{=html}", html)
        self.assertIn("<iframe", html)
        self.assertIn("srcdoc=", html)
        self.assertIn("&amp;b=2", html)        # page content escaped into the attribute
        self.assertIn("&quot;box&quot;", html)
        self.assertIn("<figcaption>계보도</figcaption>", html)
        self.assertEqual(pdf_body, ["![계보도](figs/lineage.png)"])
        self.assertEqual(html_warn + pdf_warn, [])
        self.assertEqual(gone, ["![g](figs/lineage.png)"])  # unsafe target: keep the PNG
        self.assertTrue(gone_warn[0].startswith("interactive_figure_skipped"))

    def test_typst_string_escapes(self):
        self.assertEqual(qr.typst_string('a"b\\c'), '"a\\"b\\\\c"')


class EngineChoiceTests(unittest.TestCase):
    def _report(self, root):
        report = root / "r.md"
        report.write_text("# T\n\nmeta\n\n## S\n\ntext\n", encoding="utf-8")
        return report

    def test_auto_falls_back_to_reportlab_pdf_without_quarto(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(qr, "find_quarto", return_value=None):
            report = self._report(Path(directory))
            result = render_report(report)
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["engine"], "reportlab")
            self.assertEqual(Path(result["output_path"]), report.with_suffix(".pdf").resolve())
            self.assertIsNone(result["html_path"])
            self.assertTrue(any(w.startswith("quarto_unavailable") for w in result["warnings"]))

    def test_formats_and_output_suffix_are_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            report = self._report(Path(directory))
            self.assertEqual(render_report(report, formats=["docx"])["status"], "invalid_input")
            self.assertEqual(render_report(report, Path(directory) / "x.txt")["status"], "invalid_input")

    def test_quarto_engine_required_but_missing(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(qr, "find_quarto", return_value=None):
            result = render_report(self._report(Path(directory)), engine="quarto")
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "quarto_unavailable")


@unittest.skipUnless(qr.find_quarto(), "Quarto is not installed")
class QuartoRenderTests(unittest.TestCase):
    def _sample(self, root):
        (root / "figs").mkdir()
        PILImage.new("RGB", (400, 200), "white").save(root / "figs/chart.png")
        report = root / "report.md"
        report.write_text(SAMPLE, encoding="utf-8")
        return report

    def test_default_is_html_only(self):
        with tempfile.TemporaryDirectory() as directory:
            report = self._sample(Path(directory))
            result = render_report(report)
            self.assertTrue(result["ok"], result)
            self.assertEqual(Path(result["output_path"]), report.with_suffix(".html").resolve())
            self.assertEqual(result["html_path"], result["output_path"])
            self.assertIsNone(result["pdf_path"])
            self.assertFalse(report.with_suffix(".pdf").exists())
            self.assertIsNone(result["pages"])

    def test_renders_pdf_and_html_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = self._sample(root)

            result = render_report(report, engine="quarto", formats=["html", "pdf"])

            self.assertTrue(result["ok"], result)
            self.assertEqual(result["engine"], "quarto")
            self.assertEqual(result["title"], "Sample report")
            self.assertEqual(Path(result["pdf_path"]), report.with_suffix(".pdf").resolve())
            reader = PdfReader(result["pdf_path"])
            text = "".join(page.extract_text() for page in reader.pages)
            for expected in ("Sample report", "Summary", "OMat24 then MPtrj", "nested item",
                             "second step", "code block line", "chart caption"):
                self.assertIn(expected, text)
            self.assertNotIn("**", text)
            self.assertEqual([i.title for i in reader.outline if not isinstance(i, list)], ["Summary"])
            self.assertEqual(reader.metadata.title, "Sample report")
            html = Path(result["html_path"])
            self.assertEqual(html, report.with_suffix(".html").resolve())
            page = html.read_text(encoding="utf-8")
            self.assertIn("OMat24 then MPtrj", page)
            self.assertNotIn("fonts.googleapis", page)
            self.assertEqual(sorted(p.name for p in root.iterdir()), ["figs", "report.html", "report.md", "report.pdf"])
            self.assertEqual(result["missing_glyphs"], "")

    def test_finds_an_installed_korean_font(self):
        if not any(f.lower() in {x.lower() for x in qr.typst_fonts(qr.find_quarto())} for f in qr.FONT_FAMILIES):
            self.skipTest("no Korean font installed")
        self.assertIn(qr.pick_font(qr.find_quarto()), qr.FONT_FAMILIES)


if __name__ == "__main__":
    unittest.main()


class CleanupFailureTests(unittest.TestCase):
    def test_cleanup_only_failure_is_recognised(self):
        stderr = ("ERROR: Os error 32\n    at safeRemoveDirSync (file:///quarto.js:1:1)\n"
                  "    at renderCleanup (file:///quarto.js:2:2)\n")
        self.assertTrue(qr._cleanup_only(stderr))
        self.assertFalse(qr._cleanup_only("ERROR: pandoc failed\n    at render (file:///quarto.js:3:3)"))

    def test_output_kept_when_only_cleanup_fails(self):
        with tempfile.TemporaryDirectory() as root:
            md = Path(root) / "r.md"
            md.write_text("# T\n\nbody\n", encoding="utf-8")

            def fake_run(quarto, qmd, to):
                (qmd.parent / (qmd.name[:-4] + ".html")).write_text("<html>ok</html>", encoding="utf-8")
                return mock.Mock(returncode=1, stderr="at safeRemoveDirSync\nat renderCleanup")

            with mock.patch.object(qr, "_run", fake_run), mock.patch.object(qr, "pick_font", return_value=None):
                out = qr.render_with_quarto(md, Path(root) / "r.html", "quarto", ("html",))
            self.assertTrue(out["ok"])
            self.assertTrue((Path(root) / "r.html").is_file())
            self.assertTrue(any(w.startswith("quarto_cleanup_failed") for w in out["warnings"]))
