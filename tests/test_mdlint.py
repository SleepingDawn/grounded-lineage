import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from scholarly_access_agent import combine, trace
from scholarly_access_agent.mdlint import fix_markdown, lint_markdown

# The table that rendered as plain text in small-uMLIP-trends-2026 (calc-C1.md): Pandoc reads a
# table with no blank line before it as part of the paragraph above.
GLUED_TABLE = """**DFT (VASP, vasp 스킬 정책)**
| 항목 | 값 | 근거·비고 |
|---|---|---|
| PAW | PBE PAW: Hf_pv, Zr_sv, O | MP 관례 |
"""


def rules(text):
    return [(f["line"], f["rule"]) for f in lint_markdown(text)]


class LintRuleTests(unittest.TestCase):
    def test_table_glued_to_a_bold_label_is_flagged_at_its_header_row(self):
        self.assertEqual(rules(GLUED_TABLE), [(2, "blank_line_before_table")])

    def test_list_heading_and_quote_glued_to_a_paragraph_are_flagged(self):
        text = "Text:\n- one\n- two\n\nText\n1. one\n\nText\n## Heading\n\nText\n> quoted\n"
        self.assertEqual(rules(text), [(2, "blank_line_before_list"), (6, "blank_line_before_list"),
                                       (9, "blank_line_before_heading"), (12, "blank_line_before_quote")])

    def test_table_or_heading_right_after_a_list_item_is_flagged(self):
        text = "- item\n| a | b |\n|---|---|\n\n- item\n## Heading\n"
        self.assertEqual(rules(text), [(2, "blank_line_before_table"), (6, "blank_line_before_heading")])

    def test_blocks_after_a_quote_line_are_flagged(self):
        text = "> q\n- a\n\n> q\n## H\n\n> q\n| a | b |\n|---|---|\n"
        self.assertEqual(rules(text), [(2, "blank_line_before_list"), (5, "blank_line_before_heading"),
                                       (8, "blank_line_before_table")])

    def test_what_pandoc_parses_correctly_is_not_flagged(self):
        text = ("# A\n## B\n| a | b |\n|---|---|\n| 1 | 2 |\n\n## C\n- one\n  continued\nlazy line\n- two\n"
                "1. three\n\nText\n```\ncode\n```\n\nText with a | pipe\nand more\n\n* * *\n\n"
                "Text\n2026. 11월에 시작\n\n::: {.note}\n## In a div\n:::\n")
        self.assertEqual(rules(text), [])

    def test_code_blocks_are_ignored(self):
        text = "```markdown\n**Label**\n| a | b |\n|---|---|\nText\n- item\n```\n"
        self.assertEqual(rules(text), [])

    def test_rows_with_more_cells_than_the_header_are_flagged(self):
        text = "| a | b |\n|---|---|---|\n| 1 | 2 | 3 |\n| 1 | 2 |\n| 4 |\n"
        self.assertEqual(rules(text), [(2, "table_column_mismatch"), (3, "table_column_mismatch")])

    def test_pipes_in_code_spans_and_escaped_pipes_do_not_split_cells(self):
        text = "| a | b |\n|:--|--:|\n| `x|y` | 2 |\n| p \\| q | 3 |\n| ``a|`b`` | 4 |\n"
        self.assertEqual(rules(text), [])


class FixTests(unittest.TestCase):
    def test_fix_inserts_the_missing_blank_lines(self):
        text = GLUED_TABLE + "\nText:\n- one\n"
        fixed, findings = fix_markdown(text)
        self.assertIn("**DFT (VASP, vasp 스킬 정책)**\n\n| 항목 |", fixed)
        self.assertIn("Text:\n\n- one", fixed)
        self.assertEqual([f["rule"] for f in findings], ["blank_line_before_table", "blank_line_before_list"])
        self.assertEqual(rules(fixed), [])
        self.assertEqual(fix_markdown(fixed)[0], fixed)

    def test_fix_leaves_column_mismatch_and_code_alone(self):
        text = "| a | b |\n|---|---|\n| 1 | 2 | 3 |\n\n```\nText\n- item\n```\n"
        fixed, findings = fix_markdown(text)
        self.assertEqual(fixed, text)
        self.assertEqual([(f["rule"], f["fixable"]) for f in findings], [("table_column_mismatch", False)])


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_report_trace_reports_markdown_findings_as_errors(self):
        path = self.root / "README.md"
        path.write_text("# Title\n\n" + GLUED_TABLE, encoding="utf-8")
        result = trace.trace_report(path)
        found = [(f["level"], f["line"], f["rule"]) for f in result["findings"]]
        self.assertIn(("error", 4, "blank_line_before_table"), found)
        self.assertFalse(result["ok"])

    def test_render_markdown_pass_fixes_the_text_and_warns(self):
        from scholarly_access_agent.runtime.report import _markdown_pass

        path = self.root / "README.md"
        path.write_text("# Title\n\n" + GLUED_TABLE, encoding="utf-8")
        text, warnings = _markdown_pass(path, None)
        self.assertIn("**\n\n| 항목 |", text)
        self.assertTrue(any("line 4" in w and "blank_line_before_table" in w for w in warnings))
        self.assertTrue(any("report lint --fix" in w for w in warnings))
        clean = self.root / "clean.md"
        clean.write_text("# Title\n\nText\n", encoding="utf-8")
        self.assertEqual(_markdown_pass(clean, None), (None, []))
        self.assertEqual(_markdown_pass(clean, "# Title\n\nText [1]\n"), ("# Title\n\nText [1]\n", []))

    def test_cli_report_lint_reports_then_fixes(self):
        topic = self.root / "Topic"
        (topic / "ideas").mkdir(parents=True)
        (topic / "README.md").write_text("# Review\n\nText\n", encoding="utf-8")
        calc = topic / "ideas" / "calc-C1.md"
        calc.write_text("# Plan\n\n" + GLUED_TABLE, encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = trace.main(["lint", str(topic)])
        self.assertEqual(code, 1)
        self.assertIn("blank_line_before_table", out.getvalue())
        self.assertIn("calc-C1.md", out.getvalue())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(trace.main(["lint", "--fix", str(calc)]), 0)
        self.assertIn("**\n\n| 항목 |", calc.read_text(encoding="utf-8"))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(trace.main(["lint", str(topic), "--json"]), 0)
        self.assertEqual(json.loads(out.getvalue())["findings"], [])

    def test_combine_reports_markdown_findings_per_part(self):
        topic = self.root / "Topic"
        (topic / "ideas").mkdir(parents=True)
        (topic / "README.md").write_text("# Review\n\nText\n", encoding="utf-8")
        (topic / "ideas" / "calc-C1.md").write_text("# Plan\n\n" + GLUED_TABLE, encoding="utf-8")
        result = combine.combine_reports(topic)
        self.assertEqual([(f["file"], f["line"], f["rule"]) for f in result["lint"]],
                         [("ideas/calc-C1.md", 4, "blank_line_before_table")])


if __name__ == "__main__":
    unittest.main()
