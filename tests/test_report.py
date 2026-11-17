import tempfile
import unittest
from pathlib import Path

from PIL import Image as PILImage
from pypdf import PdfReader

from scholarly_access_agent.runtime.report import cjk_bold, render_report

SAMPLE = """# Sample report

2026-11-18 · v2 · text first · evidence/part1.json

## Summary

- **Bold (PBE)**is kept. H₂O and Å³ use sub/superscripts.
  - nested item
1. first step
2. second step

| Model | F1 | Data |
| --- | --- | --- |
| A | 0.93 | OMat24 then MPtrj |
| B | 0.61 | MPtrj |

### Details

> quoted note

```
code block line
```

![chart caption](figs/chart.png)
"""


class ReportTests(unittest.TestCase):
    def test_cjk_bold_closes_before_hangul_particle(self):
        self.assertEqual(cjk_bold("**무엇(DFT)**와 `**x**`\n"), "<strong>무엇(DFT)</strong>와 `**x**`\n")
        self.assertEqual(cjk_bold("```\n**raw**\n```\n"), "```\n**raw**\n```\n")

    def test_renders_structure_outline_and_figure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "figs").mkdir()
            PILImage.new("RGB", (400, 200), "white").save(root / "figs/chart.png")
            report = root / "report.md"
            report.write_text(SAMPLE, encoding="utf-8")

            result = render_report(report)

            self.assertTrue(result["ok"], result)
            self.assertEqual(result["title"], "Sample report")
            self.assertEqual(Path(result["output_path"]), report.with_suffix(".pdf").resolve())
            self.assertEqual([w for w in result["warnings"] if w.startswith("image")], [])
            reader = PdfReader(result["output_path"])
            text = "".join(page.extract_text() for page in reader.pages)
            for expected in ("Sample report", "Summary", "OMat24 then MPtrj", "nested item",
                             "second step", "code block line", "chart caption"):
                self.assertIn(expected, text)
            self.assertNotIn("**", text)
            self.assertEqual([item.title for item in reader.outline if not isinstance(item, list)],
                             ["Summary"])
            self.assertEqual(reader.metadata.title, "Sample report")

    def test_rejects_bad_paths_and_outside_images(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "report.md"
            report.write_text("# t\n", encoding="utf-8")
            self.assertEqual(render_report(report, root / "out.txt")["status"], "invalid_input")
            self.assertEqual(render_report(root / "missing.md")["status"], "invalid_input")
            (root / "notes.txt").write_text("x", encoding="utf-8")
            self.assertEqual(render_report(root / "notes.txt")["status"], "invalid_input")

            inner = root / "report"
            inner.mkdir()
            PILImage.new("RGB", (10, 10)).save(root / "outside.png")
            nested = inner / "r.md"
            nested.write_text("# t\n\n![x](../outside.png)\n\n![y](https://example.com/a.png)\n", encoding="utf-8")
            result = render_report(nested)
            self.assertTrue(result["ok"], result)
            self.assertTrue(any("outside_report_folder" in w for w in result["warnings"]))
            self.assertTrue(any("remote" in w for w in result["warnings"]))


if __name__ == "__main__":
    unittest.main()
