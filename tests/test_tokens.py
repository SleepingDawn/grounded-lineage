import json
import re
import unittest

from scholarly_access_agent.lineage import page as lineage_page
from scholarly_access_agent.viz import common, tokens


def declared(css: str, name: str) -> list[str]:
    """Every value a stylesheet gives the custom property `name`, in order."""
    return [m.group(1).strip() for m in re.finditer(re.escape(name) + r"\s*:\s*([^;]+);", css)]


class TokenSourceTests(unittest.TestCase):
    """The report, the lineage map and the viz charts all take their colours and fonts from design_tokens.json."""

    def setUp(self):
        self.t = json.loads(tokens.TOKENS_FILE.read_text(encoding="utf-8"))

    def test_json_has_both_modes_for_every_colour(self):
        for group in ("color", "design"):
            self.assertEqual(set(self.t[group]["light"]), set(self.t[group]["dark"]), group)
        for k in ("ink", "muted", "rule", "surface", "page", "accent", "head_bg", "band", "band_edge"):
            self.assertIn(k, self.t["color"]["light"])
        self.assertEqual(self.t["design"]["light"]["model"], "#0072B2")
        self.assertEqual(self.t["design"]["dark"]["model"], "#3A93D8")
        self.assertEqual(self.t["font"]["body"][:2], ["Pretendard", "Noto Sans KR"])
        self.assertEqual(set(self.t["read_depth"]) - {"_about"},
                         {"본문 확인", "발췌 확인", "인용 맥락만", "초록만 확인", "미확인"})

    def assert_follows(self, css: str, mapping: dict[str, str]):
        for name, path in mapping.items():
            values = declared(css, name)
            light, dark = tokens.value(path, "light"), tokens.value(path, "dark")
            self.assertTrue(values, f"{name} missing")
            self.assertEqual(values[0], light, name)
            if dark != light:  # repeated for the OS dark setting and for data-theme="dark"
                self.assertEqual(values[1:3], [dark, dark], name)
            else:
                self.assertEqual(len(values), 1, name)

    def test_report_css_matches_json(self):
        css = tokens.REPORT_CSS.read_text(encoding="utf-8")
        self.assertEqual(tokens.report_css_current(css), tokens.report_block(),
                         "snu-report.css is out of date: python -m scholarly_access_agent.viz.tokens --write")
        self.assert_follows(css, tokens.report_vars())
        self.assertIn("background: var(--snu-surface)", css)  # the report itself follows dark mode

    def test_inline_code_uses_report_colours_over_quarto_defaults(self):
        # Quarto styles `p|li|td code:not(.sourceCode)` with a near-white background that beats a
        # plain `code` rule; in dark mode the light code ink then sits on near-white (unreadable).
        css = tokens.REPORT_CSS.read_text(encoding="utf-8")
        rule = next((m for m in re.finditer(r"([^{}]+)\{([^}]*)\}", css)
                     if "td code:not(.sourceCode)" in m.group(1)), None)
        self.assertIsNotNone(rule, "no inline-code rule matching Quarto's selectors")
        selectors = {s.strip() for s in rule.group(1).split(",")}
        for tag in ("p", "li", "td", "th", "dd"):
            self.assertIn(f"{tag} code:not(.sourceCode)", selectors)
        self.assertIn("background: var(--snu-code-bg)", rule.group(2))
        self.assertIn("color: var(--snu-code-ink)", rule.group(2))

    def test_lineage_css_matches_json(self):
        css = lineage_page.base_css({"lanes": [], "nodes": [], "edges": [], "meta": {}})
        self.assert_follows(css, tokens.lineage_vars())
        page_css = (lineage_page.ASSETS / "page.css").read_text(encoding="utf-8")
        for name in ("--fg", "--surface", "--line", "--f-body"):  # no second, drifting definition
            self.assertEqual(declared(page_css, name), [], name)
        self.assertEqual(lineage_page.DESIGN_COLORS["model"], tokens.value("design.model"))

    def test_viz_page_and_config_match_json(self):
        page = common.page_html({"mark": "point"}, "t", "c")
        self.assert_follows(page, tokens.viz_vars())
        cfg = common.base_config()
        self.assertEqual(cfg["font"], tokens.font_stack("body"))
        self.assertEqual(cfg["axis"]["labelColor"], tokens.value("color.muted"))
        self.assertEqual(cfg["text"]["color"], tokens.value("color.ink"))
        self.assertEqual(cfg["axis"]["labelFontSize"], self.t["size"]["chart_small"])
        light, dark = tokens.viz_swap()
        self.assertEqual(light["surface"], self.t["color"]["light"]["surface"])
        self.assertEqual(dark["d_model"], self.t["design"]["dark"]["model"])
        self.assertEqual([d[2] for d in common.DESIGNS], [self.t["design"]["light"][k] for k in
                                                          ("model", "observational", "experiment", "quasi", "review")])

    def test_one_value_everywhere(self):
        """The same token reaches all three consumers with the same value."""
        report = tokens.REPORT_CSS.read_text(encoding="utf-8")
        lineage = lineage_page.base_css({"lanes": [], "nodes": [], "edges": [], "meta": {}})
        viz = common.page_html({"mark": "point"}, "t", "c")
        for r, l, v in (("--snu-ink", "--fg", "--fg"), ("--snu-surface", "--surface", "--c-surface"),
                        ("--snu-d-model", "--d-model", "--c-d-model"), ("--snu-font", "--f-body", None)):
            values = declared(report, r)
            self.assertEqual(declared(lineage, l), values, r)
            if v:
                self.assertEqual(declared(viz, v), values, r)

    def test_check_flag(self):
        self.assertEqual(tokens.main(["--check"]), 0)


if __name__ == "__main__":
    unittest.main()
