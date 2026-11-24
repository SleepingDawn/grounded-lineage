import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from scholarly_access_agent import combine, trace

REVIEW = """# Review title

2026-11-24 · v1 · review method line

## 한눈에 보기

- point one [@larkin2014].

## Q1. First question

### Detail

See [the old review](../Other/README.md) and ![map](figs/map.html).

## 부록: 근거 목록

<!-- references -->
"""

TOPICS = """# Topic title

2026-11-24 · v1 · topic method line

## Cards

Matrix in [matrix.md](matrix.md), review in [the review](../README.md), web [x](https://example.org/a.md).

![fig](figs/gap.html)

```text
# not a heading
```

## 부록: 근거 목록

<!-- references -->
"""

CALC = """# Calc plan

2026-11-24 · plan line

## 1. What

Inputs in [calc](../calc-C1/README.md#order).
"""


def make_topic(root: Path, parts=("review", "topics", "calc")) -> Path:
    topic = root / "My-topic"
    (topic / "ideas").mkdir(parents=True)
    if "review" in parts:
        (topic / "README.md").write_text(REVIEW, encoding="utf-8")
    if "topics" in parts:
        (topic / "ideas" / "README.md").write_text(TOPICS, encoding="utf-8")
    if "calc" in parts:
        (topic / "ideas" / "calc-C1.md").write_text(CALC, encoding="utf-8")
    return topic


class CombineTests(unittest.TestCase):
    def test_default_parts_merge_in_order_with_one_title_and_one_reference_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            topic = make_topic(Path(tmp))
            result = combine.combine_reports(topic)
            out = Path(result["output"])
            self.assertEqual(out, topic / "My-topic.md")
            text = out.read_text(encoding="utf-8")
            lines, in_code = [], False
            for l in text.splitlines():
                if l.startswith("```"):
                    in_code = not in_code
                elif not in_code:
                    lines.append(l)
            self.assertEqual([l for l in lines if l.startswith("# ")], ["# Review title"])
            parts = [l for l in lines if l.startswith("## ")]
            self.assertEqual(parts, ["## Review title", "## Topic title", "## Calc plan", "## 부록: 근거 목록"])
            self.assertIn("### Q1. First question", lines)
            self.assertIn("#### Detail", lines)
            self.assertEqual(text.count("<!-- references -->"), 1)
            self.assertTrue(text.rstrip().endswith("<!-- references -->"))
            self.assertEqual(result["parts"], ["README.md", "ideas/README.md", "ideas/calc-C1.md"])

    def test_links_are_rebased_to_the_topic_folder_and_code_is_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            topic = make_topic(Path(tmp))
            text = Path(combine.combine_reports(topic)["output"]).read_text(encoding="utf-8")
            self.assertIn("[matrix.md](ideas/matrix.md)", text)
            self.assertIn("[the review](README.md)", text)
            self.assertIn("![fig](ideas/figs/gap.html)", text)
            self.assertIn("![map](figs/map.html)", text)
            self.assertIn("[the old review](../Other/README.md)", text)
            self.assertIn("[calc](calc-C1/README.md#order)", text)
            self.assertIn("[x](https://example.org/a.md)", text)
            self.assertIn("\n# not a heading\n", text)

    def test_meta_lines_stay_with_their_part(self):
        with tempfile.TemporaryDirectory() as tmp:
            topic = make_topic(Path(tmp))
            text = Path(combine.combine_reports(topic)["output"]).read_text(encoding="utf-8")
            self.assertLess(text.index("## Topic title"), text.index("*2026-11-24 · v1 · topic method line*"))

    def test_summary_file_goes_first_and_title_can_be_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            topic = make_topic(Path(tmp))
            (topic / "summary.md").write_text("## 한눈에 보기\n\n- overall [@larkin2014].\n", encoding="utf-8")
            result = combine.combine_reports(topic, title="Everything", summary=topic / "summary.md")
            lines = Path(result["output"]).read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines[0], "# Everything")
            heads = [l for l in lines if l.startswith("## ")]
            self.assertEqual(heads[0], "## 한눈에 보기")
            self.assertEqual(heads[1], "## Review title")

    def test_single_part_is_copied_without_nesting(self):
        with tempfile.TemporaryDirectory() as tmp:
            topic = make_topic(Path(tmp), parts=("review",))
            text = Path(combine.combine_reports(topic)["output"]).read_text(encoding="utf-8")
            self.assertEqual(text.strip(), REVIEW.strip())

    def test_explicit_parts_and_missing_part(self):
        with tempfile.TemporaryDirectory() as tmp:
            topic = make_topic(Path(tmp))
            result = combine.combine_reports(topic, parts=["ideas/calc-C1.md", "README.md"])
            self.assertEqual(result["parts"], ["ideas/calc-C1.md", "README.md"])
            with self.assertRaises(FileNotFoundError):
                combine.combine_reports(topic, parts=["ideas/none.md"])

    def test_cli_report_combine(self):
        with tempfile.TemporaryDirectory() as tmp:
            topic = make_topic(Path(tmp))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = trace.main(["combine", str(topic), "--json"])
            self.assertEqual(code, 0)
            payload = json.loads(buf.getvalue())
            self.assertTrue(Path(payload["output"]).is_file())


if __name__ == "__main__":
    unittest.main()
