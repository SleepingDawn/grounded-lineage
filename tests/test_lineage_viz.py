"""Lineage map visualisation: evidence panel data, badges, palette, edge toggles, embed variant and its
report embedding (offline; no browser)."""
import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

from scholarly_access_agent.lineage import check, page
from scholarly_access_agent.runtime import quarto_report as qr

from test_lineage import LINEAGE, TOPIC

RECORD = {
    "paper_id": "10.1103/PhysRevB.89.144303", "title": "Thermal conductivity accumulation in amorphous silica",
    "authors": ["Jason M. Larkin", "Alan J. H. McGaughey"], "year": 2014, "venue": "Phys. Rev. B 89, 144303",
    "version": "publisher PDF", "access": "fulltext_pdf", "read_via": "read_pdf", "venue_type": "journal",
    "criteria": [{"criterion": "kappa method", "judgment": "Green-Kubo and NMD",
                  "evidence": [{"section": "II. Methods", "pdf_page": 2, "read_mode": "pages"}]}],
    "results": [{"id": "gk300", "quantity": "kappa (GK)", "value": 2.1, "lo": 1.9, "hi": 2.3, "unit": "W/mK",
                 "condition": "BKS, 300 K", "pdf_page": 9, "section": "Table II", "read_mode": "pages"}],
}


def quiet():
    return contextlib.redirect_stdout(io.StringIO())


def embedded_json(html, name):
    """The JSON literal the page script holds for N (__NODES__) or CFG (__CFG__)."""
    m = re.search(r"const N = (\{.*?\}), E = ", html, re.S) if name == "N" else re.search(r"CFG = (\{.*?\});\n", html, re.S)
    return json.loads(m.group(1).replace("<\\/", "</"))


class LineageVizTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        L = json.loads(json.dumps(LINEAGE))
        L["nodes"][0]["evidence"] = "larkin2014"     # file present
        L["nodes"][1]["evidence"] = "missing2015"    # file absent: falls back to rows (none here)
        (self.root / "evidence").mkdir()
        (self.root / "evidence" / "larkin2014.json").write_text(json.dumps(RECORD), encoding="utf-8")
        (self.root / "lineage.json").write_text(json.dumps(L, ensure_ascii=False), encoding="utf-8")
        self.L = L

    def tearDown(self):
        self.tmp.cleanup()

    def test_panel_data_is_embedded_from_the_evidence_folder(self):
        with quiet():
            page.main([str(self.root)])
        html = (self.root / "test_lineage.html").read_text(encoding="utf-8")
        N = embedded_json(html, "N")
        rec = N["a"]["rec"]
        self.assertEqual(rec["stem"], "larkin2014")
        self.assertEqual(rec["label"], "본문 확인")             # evidence.derive_label, not typed by hand
        self.assertEqual(rec["access"], "fulltext_pdf")
        self.assertEqual(rec["crit"][0]["at"], [{"loc": "§II p.2", "m": "pages"}])
        self.assertEqual(rec["res"][0]["v"], "2.1 (1.9–2.3)")
        self.assertEqual(rec["res"][0]["u"], "W/mK")
        self.assertEqual(rec["res"][0]["at"], "§Table II p.9")
        self.assertEqual(N["a"]["u"], "https://openalex.org/A")
        self.assertNotIn("rec", N["b"])                        # missing file: no record
        self.assertEqual(N["s"]["lab"], "본문 확인")            # row level fallback
        self.assertEqual(N["b"]["lab"], "미확인")
        self.assertEqual(embedded_json(html, "CFG")["evbase"], "evidence/")
        self.assertIn('id="panel"', html)
        self.assertIn("원문 열기", html)
        self.assertIn("기록 보기", html)
        # boxes open the panel instead of navigating
        self.assertNotIn('<a href="https://openalex.org/A"', html)
        self.assertIn('<g tabindex="0" class="node" data-id="a"', html)
        self.assertEqual(page.missing_evidence(self.L, self.root), [("b", "missing2015")])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            check.main([str(self.root), "--no-corpus"])
        self.assertIn("evidence/missing2015.json not found", out.getvalue())

    def test_evidence_field_must_be_a_stem(self):
        L = json.loads(json.dumps(self.L))
        L["nodes"][0]["evidence"] = "../secret"
        self.assertTrue(any("evidence must be the stem" in e for e in page.validate(L)))

    def test_badge_mapping_and_legend(self):
        self.assertEqual(page.BADGE, {"본문 확인": "full", "발췌 확인": "half", "인용 맥락만": "dash",
                                      "초록만 확인": "ring", "미확인": None})
        self.assertIn('class="bdg full"', page.badge_svg("full", 0, 0))
        self.assertIn('class="bdg-h"', page.badge_svg("half", 0, 0))
        self.assertEqual(page.badge_svg(None, 0, 0), "")
        ev = page.node_evidence(self.L, self.root)
        svg = page.svg(self.L, page.Links({}, {}), ev)
        self.assertEqual(svg.count('class="bdg full"'), 2 + 1)  # nodes a (record) and s (row) + legend sample
        self.assertIn("근거 수준", svg)
        self.assertIn("미확인 (표시 없음)", svg)
        # footer: date, read-level counts, source
        footer = page.figure_footer(self.L, page.node_labels(self.L, ev), ev)
        self.assertTrue(footer.startswith("2026-11-20 기준 · 연구 4편 근거 수준: 본문 2 · 발췌 0 · 인용 맥락 0 · 초록 0 · "
                                          "미확인 2 · 출처: OpenAlex"))
        self.assertIn("evidence/ 원문 기록", footer)
        self.assertIn('class="foot"', svg)                     # wrapped to the figure width inside the SVG

    def test_palette_is_okabe_ito_in_both_themes_and_answer_cell_is_neutral(self):
        self.assertEqual(page.DESIGN_COLORS, {"model": "#0072B2", "observational": "#009E73", "experiment": "#D55E00",
                                              "quasi": "#E69F00", "review": "#CC79A7"})
        css = page.base_css(TOPIC)
        for k, v in page.DESIGN_COLORS.items():
            self.assertIn(f"--d-{k}: {v};", css)
        # from data/design_tokens.json: only the blue is lightened for the dark surface (OS setting + data-theme)
        self.assertEqual(css.count("--d-model: #3A93D8;"), 2)
        self.assertEqual(css.count("--d-experiment:"), 1)
        self.assertIn("svg .ansbox{fill:color-mix(in srgb, var(--fg) 5%, var(--surface));stroke:var(--fg)", css)
        svg = page.svg(TOPIC, page.Links({}, {}))
        self.assertIn('class="dt">관</text>', svg)                # design tag in the box corner
        self.assertIn('class="dt">모</text>', svg)

    def test_edge_toggles_and_long_edges(self):
        controls = page.view_controls(TOPIC)
        for t in ("s", "d", "e"):
            self.assertIn(f'data-etype="{t}"', controls)
        self.assertNotIn('data-etype="m"', controls)               # only the types in use
        self.assertIn("화면 맞춤", controls)
        self.assertIn('svg.hide-s [data-type="s"]', page.base_css(TOPIC))
        # 1967 -> 1988 (21 years) is long; s/c labels at the start name the target
        self.assertIn(("s", "c"), page.long_edges(TOPIC))
        svg = page.svg(TOPIC, page.Links({}, {}))
        self.assertIn('class="elab"', svg)
        self.assertIn("→ Carbajo 1988", svg)
        self.assertIn('data-type="s"', svg)
        self.assertIn('id="shortbtn" aria-pressed="false"', controls)  # 6 nodes: off by default
        self.assertNotIn('class="shorten"', svg)
        big = json.loads(json.dumps(TOPIC))
        big["nodes"] += [{"id": f"n{k}", "lane": 2, "year": 1990 + k % 30, "title": "x", "sub": "y", "openalex": "W9",
                          "design": "model"} for k in range(40)]
        self.assertTrue(page.svg(big, page.Links({}, {})).startswith('<svg id="tree" class="shorten"'))

    def test_embed_variant_contents(self):
        with quiet():
            page.main([str(self.root), "--embed"])
        html = (self.root / "test_lineage_embed.html").read_text(encoding="utf-8")
        self.assertIn('data-snu-embed="1"', html)
        self.assertIn('<svg id="tree"', html)
        self.assertIn('id="panel"', html)
        self.assertIn('class="lanebtn edgebtn"', html)
        self.assertIn('class="legend"', html)
        self.assertIn("background:transparent", html)
        self.assertIn("snu-embed-height", html)                   # posts its height to the report
        self.assertIn("snu-embed-theme", html)                    # takes the report's theme and tokens
        self.assertTrue(embedded_json(html, "CFG")["embed"])
        for absent in ("단계별 흐름", "계보 표", "다시 돌리기", "검색 기록", "<h1>"):
            self.assertNotIn(absent, html)
        # the record link is relative to where the page is written
        out = self.root / "report" / "x_embed.html"
        with quiet():
            page.main([str(self.root), "--embed", "--out", str(out)])
        self.assertEqual(embedded_json(out.read_text(encoding="utf-8"), "CFG")["evbase"], "../evidence/")


class QuartoEmbedTests(unittest.TestCase):
    def test_html_image_becomes_auto_sized_frame_and_pdf_takes_the_static_image(self):
        from PIL import Image as PILImage

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "figs").mkdir()
            PILImage.new("RGB", (4, 4)).save(root / "figs/lineage.png")
            PILImage.new("RGB", (4, 4)).save(root / "figs/chart.png")
            (root / "map_embed.html").write_text("<p>map & more</p>", encoding="utf-8")
            (root / "figs/chart.html").write_text("<p>chart</p>", encoding="utf-8")
            (root / "figs/bare.html").write_text("<p>bare</p>", encoding="utf-8")
            lines = ['![지도](map_embed.html "static=figs/lineage.png")', "![차트](figs/chart.html)",
                     '![bare](figs/bare.html "height=420")', '![old](figs/lineage.png "interactive=map_embed.html")']
            html_body, html_warn = qr.prepare_body(lines, root, interactive=True)
            pdf_body, pdf_warn = qr.prepare_body(lines, root, interactive=False)
        html = "\n".join(html_body)
        self.assertEqual(html.count('<iframe class="snu-frame snu-auto"'), 3)
        self.assertEqual(html.count('<iframe class="snu-frame" '), 1)     # old interactive= form still works
        self.assertIn("map &amp; more", html)                            # srcdoc escaped
        self.assertIn('style="height:640px"', html)                      # fallback height until the page reports
        self.assertIn('style="height:420px"', html)
        self.assertIn("snu-embed-height", html)                          # resize listener
        self.assertIn("snu-embed-theme", html)                           # theme hand-off
        self.assertIn("<figcaption>차트</figcaption>", html)
        self.assertEqual(html_warn, [])
        self.assertEqual(pdf_body, ["![지도](figs/lineage.png)", "![차트](figs/chart.png)", "",
                                    "![old](figs/lineage.png)"])
        self.assertEqual(len(pdf_warn), 1)
        self.assertTrue(pdf_warn[0].startswith("interactive_figure_without_static_image"))


if __name__ == "__main__":
    unittest.main()
