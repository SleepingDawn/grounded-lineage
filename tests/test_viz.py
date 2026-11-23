import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from scholarly_access_agent import cli
from scholarly_access_agent.viz import effects, lineage_charts
from scholarly_access_agent.viz.common import DARK, LIGHT, VEGA, VEGA_EMBED, VEGA_LITE, VizError, page_html


def write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False), encoding="utf-8")


def record(authors, year, access="fulltext_pdf", results=(), **extra):
    base = {"paper_id": f"10.1/{authors}{year}", "title": f"Paper by {authors}", "authors": authors, "year": year,
            "version": "publisher PDF", "access": access, "read_via": "read_pdf",
            "criteria": [{"criterion": "c", "evidence": [{"pdf_page": 3, "section": "Results", "read_mode": "pages"}]}],
            "results": list(results)}
    base.update(extra)
    return base


def res(rid, value, unit="W/mK", **extra):
    return {"id": rid, "quantity": "kappa (GK)", "value": value, "unit": unit, "condition": "300 K", "pdf_page": 4,
            **extra}


def leaves(spec: dict) -> list[dict]:
    """Every unit layer of a (nested) layer spec."""
    out = []
    for lay in spec.get("layer") or []:
        out.extend(leaves(lay) if "layer" in lay else [lay])
    return out


class Topic:
    """A small synthetic topic folder."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        ev = self.root / "evidence"
        write(ev / "alpha2014.json", record("Ann Alpha", 2014, design="simulation model", results=[
            res("r1", "14-24"), res("r2", 2.1, lo=1.9, hi=2.3), res("r3", 1.6, read_mode="terms")]))
        write(ev / "beta2020.json", record("Bo Beta; Cy Gamma", 2020, access="abstract_only", evidence_role="empirical",
                                           results=[res("b1", "1.35±0.05", unit="W m^-1 K^-1")]))
        write(ev / "gamma2018.json", record("Gamma", 2018, access="unavailable", results=[res("g1", 3.0)]))
        write(ev / "delta2019.json", record("Di Delta", 2019, evidence_role="review",
                                            results=[res("d1", 5, unit="GPa", quantity="bulk modulus")]))

    def cleanup(self):
        self.tmp.cleanup()


class EffectsTests(unittest.TestCase):
    def setUp(self):
        self.t = Topic()
        self.addCleanup(self.t.cleanup)

    def test_parse_value_ranges_and_errors(self):
        self.assertEqual(effects.parse_value({"value": "14-24"}), (19.0, 14.0, 24.0))
        self.assertEqual(effects.parse_value({"value": "14–24"}), (19.0, 14.0, 24.0))
        self.assertEqual(effects.parse_value({"value": "-3.5"}), (-3.5, None, None))
        v, lo, hi = effects.parse_value({"value": "1.35±0.05"})
        self.assertAlmostEqual(lo, 1.30)
        self.assertAlmostEqual(hi, 1.40)
        self.assertEqual(effects.parse_value({"value": 2.1, "lo": 1.9, "hi": "2.3"}), (2.1, 1.9, 2.3))
        self.assertIsNone(effects.parse_value({"value": "n/a"}))

    def test_units_compare_by_meaning(self):
        self.assertEqual(effects.norm_unit("W/mK"), effects.norm_unit("W m^-1 K^-1"))
        self.assertEqual(effects.norm_unit("W/(m·K)"), effects.norm_unit("W·m⁻¹·K⁻¹"))
        self.assertNotEqual(effects.norm_unit("W/mK"), effects.norm_unit("GPa"))

    def test_spec_rows_ranges_access_and_band(self):
        spec, meta = effects.build(self.t.root, "kappa", band=(1.3, 1.4), band_label="실험")
        rows = spec["data"]["values"]
        by_id = {r["id"]: r for r in rows}
        self.assertEqual(set(by_id), {"r1", "r2", "r3", "b1"})  # gamma2018 is 미확인: left out
        self.assertEqual((by_id["r1"]["value"], by_id["r1"]["lo"], by_id["r1"]["hi"]), (19.0, 14.0, 24.0))
        self.assertEqual(by_id["r1"]["printed"], "14-24")
        self.assertEqual(by_id["r1"]["label"], "본문 확인")
        self.assertEqual(by_id["r3"]["label"], "발췌 확인")  # read_mode terms
        self.assertEqual(by_id["b1"]["label"], "초록만 확인")
        self.assertEqual([by_id[k]["fill"] for k in ("r1", "r3", "b1")], ["full", "half", "hollow"])
        self.assertEqual(by_id["r1"]["design"], "모형")
        self.assertEqual(by_id["b1"]["design"], "관찰")
        self.assertEqual(by_id["r1"]["study"], "Alpha 2014")
        self.assertEqual(by_id["b1"]["study"], "Beta 2020")
        self.assertEqual(by_id["r1"]["value_text"], "14.0–24.0")  # a printed range is shown as printed
        self.assertEqual(by_id["r2"]["value_text"], "2.1")
        self.assertIn("미확인 1건 생략", meta["notes"])
        self.assertEqual(spec["width"], "container")
        # design colours on every dot, whisker and cap
        colors = [lay["encoding"]["color"]["scale"] for lay in leaves(spec)
                  if "color" in lay.get("encoding", {}) and "scale" in lay["encoding"]["color"]]
        self.assertTrue(colors)
        for c in colors:
            self.assertEqual(dict(zip(c["domain"], c["range"])), {"모형": "#0072B2", "관찰": "#009E73"})
        # the half fill is a custom half-disc drawn on top of the ring
        shapes = [lay["mark"].get("shape") for lay in leaves(spec) if isinstance(lay.get("mark"), dict)]
        self.assertIn(effects.HALF_PATH, shapes)
        # the reference band: neutral fill, its label with range and unit
        band_data = next(lay for lay in spec["layer"] if lay.get("data", {}).get("values", [{}])[0].get("hi") == 1.4)
        self.assertEqual(band_data["data"]["values"][0]["text"], "실험 1.3–1.4 W/mK")  # 1 decimal on a 0-25 axis
        band_rects = [lay for lay in leaves(spec) if isinstance(lay.get("mark"), dict)
                      and lay["mark"].get("type") == "rect" and lay["mark"].get("color") == LIGHT["band"]]
        self.assertEqual(len(band_rects), 2)  # the wide column and the narrow per-row strips
        # title + subtitle with quantity, unit, counts and the band takeaway
        head = spec["usermeta"]["header"]
        self.assertEqual(head["title"], "연구마다 kappa 값은 얼마나 다른가?")
        self.assertIn("kappa (W/mK)", head["subtitle"])
        self.assertIn("2편에서 4개 값", head["subtitle"])
        self.assertIn("1개가 실험 범위 안", head["subtitle"])  # b1 1.35
        # one legend row: design chips, read-depth chips, the band chip
        legend = spec["usermeta"]["legend"]
        self.assertEqual(legend[0]["title"], "연구 설계")
        self.assertEqual([(i["label"], i["color"]) for i in legend[0]["items"]],
                         [("모형", "#0072B2"), ("관찰", "#009E73")])
        self.assertEqual(legend[1]["items"], [{"label": "본문 확인", "swatch": "full"},
                                             {"label": "발췌 확인", "swatch": "half"},
                                             {"label": "초록만 확인", "swatch": "hollow"}])
        self.assertEqual(legend[2]["items"], [{"label": "실험 범위", "swatch": "band"}])

    def test_rows_grouped_by_design_then_year(self):
        spec, meta = effects.build(self.t.root, "kappa")
        rows = spec["data"]["values"]
        self.assertTrue(meta["grouped"])
        # 모형 first (fixed design order), year then value inside: r3 1.6, r2 2.1, r1 19 (all 2014); then 관찰
        self.assertEqual([r["id"] for r in rows], ["r3", "r2", "r1", "b1"])
        self.assertEqual([r["y"] for r in rows], sorted(r["y"] for r in rows))
        self.assertEqual([r["yn"] for r in rows], sorted(r["yn"] for r in rows))
        heads = [v for lay in leaves(spec) for v in (lay.get("data") or {}).get("values", []) if "n" in v]
        self.assertEqual([h["text"] for h in heads], ["모형 · 3개 값", "관찰 · 1개 값"])
        self.assertTrue(heads[0]["y"] < rows[0]["y"] < heads[1]["y"] < rows[3]["y"])
        # both row layouts are carried; the page picks one from its width
        layout = spec["usermeta"]["rows"]
        self.assertEqual(layout["height"], spec["height"])
        self.assertGreater(layout["narrow_height"], layout["height"])
        self.assertIn("narrow", [p["name"] for p in spec["params"]])

    def test_sort_by_value_inside_groups(self):
        spec, _ = effects.build(self.t.root, "kappa", sort="value")
        rows = spec["data"]["values"]
        for design in ("모형", "관찰"):
            values = [r["value"] for r in rows if r["design"] == design]
            self.assertEqual(values, sorted(values))
        self.assertIn("값 순", spec["usermeta"]["header"]["subtitle"])

    def test_single_design_has_no_group_headers(self):
        spec, meta = effects.build(self.t.root, ".", unit="GPa")
        self.assertFalse(meta["grouped"])
        heads = [v for lay in leaves(spec) for v in (lay.get("data") or {}).get("values", []) if "n" in v]
        self.assertEqual(heads, [])
        self.assertEqual(spec["usermeta"]["legend"][0]["items"][0]["label"], "리뷰")

    def test_domain_covers_whiskers_and_clips_runaways_with_an_arrow(self):
        domain, _, _ = effects.axis_domain([{"value": 2.0, "lo": 1.0, "hi": 3.0},
                                            {"value": 2.5, "lo": None, "hi": None}], (1.3, 1.4))
        self.assertLess(domain[0], 1.0)
        self.assertGreater(domain[1], 3.0)
        write(self.t.root / "evidence" / "eps2021.json", record("Eve Eps", 2021, design="simulation model", results=[
            res("e1", 2.0, lo=0.5, hi=80)]))
        spec, _ = effects.build(self.t.root, "kappa", band=(1.3, 1.4))
        row = next(r for r in spec["data"]["values"] if r["id"] == "e1")
        self.assertTrue(row["clip_hi"])
        self.assertFalse(row["clip_lo"])
        self.assertLess(row["hi_draw"], 80)
        carrier = next(lay for lay in leaves(spec) if lay.get("encoding", {}).get("x", {}).get("axis"))
        lo, hi = carrier["encoding"]["x"]["scale"]["domain"]
        self.assertGreaterEqual(row["hi_draw"], hi - (hi - lo) * 0.1)  # the arrow sits at the right edge
        self.assertLessEqual(row["hi_draw"], hi)
        self.assertIn({"label": "축 밖으로 이어지는 범위", "swatch": "arrow"}, spec["usermeta"]["legend"][-1]["items"])
        shapes = [lay["mark"].get("shape") for lay in leaves(spec) if isinstance(lay.get("mark"), dict)]
        self.assertIn("triangle-right", shapes)
        spec2, _ = effects.build(self.t.root, "kappa", title="실험과 맞는 계산은?")
        self.assertEqual(spec2["usermeta"]["header"]["title"], "실험과 맞는 계산은?")

    def test_mixed_units_refused_with_list(self):
        with self.assertRaises(VizError) as ctx:
            effects.build(self.t.root, ".")
        msg = str(ctx.exception)
        self.assertIn("mixed units", msg)
        self.assertIn("W/mK", msg)
        self.assertIn("GPa (1)", msg)
        self.assertIn("--unit", msg)

    def test_unit_filter(self):
        spec, _ = effects.build(self.t.root, ".", unit="GPa")
        self.assertEqual([r["id"] for r in spec["data"]["values"]], ["d1"])
        self.assertEqual(spec["data"]["values"][0]["design"], "리뷰")
        with self.assertRaises(VizError) as ctx:
            effects.build(self.t.root, ".", unit="eV")
        self.assertIn("units found", str(ctx.exception))

    def test_no_match(self):
        with self.assertRaises(VizError):
            effects.build(self.t.root, "viscosity")


class LineageChartTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        entry = {"scope": "silica", "method": "NEP", "date": "2026-11-20", "numerator": 3, "denominator": 10,
                 "share": 0.3, "no_abstract": 2,
                 "per_year": {"2021": {"scope": 4, "method": 1, "share": 0.25},
                              "2022": {"scope": 6, "method": 2, "share": 0.333}}}
        write(self.root / "data" / "adoption.json", [
            {"id": "adoption#1", **entry, "per_year": {"2020": {"scope": 2, "method": 0, "share": 0.0}}},
            {"id": "adoption#2", **entry}])

    def test_adoption_latest_and_by_id(self):
        spec, meta = lineage_charts.build_adoption(self.root)
        bars = spec["layer"][0]["data"]["values"]
        self.assertEqual([(b["year"], b["counts"], b["share"]) for b in bars],
                         [("2021", "1/4", 0.25), ("2022", "2/6", 0.333)])
        self.assertEqual(meta["id"], "adoption#2")
        self.assertEqual(spec["layer"][1]["data"]["values"][0]["share"], 0.3)
        self.assertIn("10편", meta["source"])
        tip = {t["field"] for t in spec["layer"][0]["layer"][0]["encoding"]["tooltip"]}
        self.assertTrue({"method", "scope", "share"} <= tip)
        spec1, meta1 = lineage_charts.build_adoption(self.root, "1")
        self.assertEqual(meta1["id"], "adoption#1")
        self.assertEqual(len(spec1["layer"][0]["data"]["values"]), 1)
        with self.assertRaises(VizError):
            lineage_charts.build_adoption(self.root, "adoption#9")

    def test_timeline_parts_and_peaks(self):
        series = [[y, 1 if y % 7 else 9, (8 if y in (1990, 2001) else 0)] for y in range(1980, 2011)]
        write(self.root / "data" / "analysis.json", {
            "rpys_series": series,
            "rpys_peaks": [[1990, 9, 8, ["Allen 1990 | 10 cit | Title A | W1"]], [2001, 9, 8, ["Bee 2001 | 3 cit | B | W2"]],
                           [1995, 1, 3, ["Gen 1995 | 1 cit | Generic | W3"]]],
            "forward_by_year": {"2021": 3, "2020": 5}})
        write(self.root / "lineage.json", {"evidence": {"rpys_years": [1990, 2001]}})
        spec, meta = lineage_charts.build_timeline(self.root)
        self.assertEqual(len(spec["vconcat"]), 2)
        self.assertEqual(spec["usermeta"]["responsive"], "concat")
        marks = spec["vconcat"][0]["layer"][1]["data"]["values"]
        self.assertEqual([m["year"] for m in marks], [1990, 2001])  # chosen peaks only
        self.assertIn("Allen", marks[0]["refs"])
        fwd = spec["vconcat"][1]["data"]["values"]
        self.assertEqual(fwd, [{"year": 2020, "n": 5}, {"year": 2021, "n": 3}])
        self.assertIn("lineage.json", spec["vconcat"][0]["title"]["subtitle"])

    def test_timeline_skips_missing_parts(self):
        write(self.root / "data" / "analysis.json", {"forward_by_year": {"2024": 2}})
        spec, meta = lineage_charts.build_timeline(self.root)
        self.assertEqual(len(spec["vconcat"]), 1)
        self.assertIn("rpys_series 없음", meta["notes"])
        write(self.root / "data" / "analysis.json", {"rpys_peaks": []})
        with self.assertRaises(VizError):
            lineage_charts.build_timeline(self.root)

    def test_adoption_missing(self):
        (self.root / "data" / "adoption.json").unlink()
        with self.assertRaises(VizError) as ctx:
            lineage_charts.build_adoption(self.root)
        self.assertIn("lineage adoption", str(ctx.exception))


class PageAndCliTests(unittest.TestCase):
    def setUp(self):
        self.t = Topic()
        self.addCleanup(self.t.cleanup)

    def test_page_has_pinned_cdn_and_height_script(self):
        page = page_html({"mark": "point"}, "제목 </title>", "자료: x <b>")
        for url in (VEGA, VEGA_LITE, VEGA_EMBED):
            self.assertIn(f'<script src="{url}"></script>', page)
        self.assertIn("vega@5.30.0", VEGA)
        self.assertIn("vega-lite@5.21.0", VEGA_LITE)
        self.assertIn("vega-embed@6.26.0", VEGA_EMBED)
        self.assertIn('postMessage({ type: "snu-embed-height", height: h }, "*")', page)
        self.assertIn('addEventListener("resize"', page)
        self.assertIn("prefers-color-scheme: dark", page)
        self.assertIn('getAttribute("data-theme")', page)
        self.assertIn("background: transparent", page)
        self.assertIn("자료: x &lt;b&gt;", page)
        self.assertIn("제목 &lt;/title&gt;", page)
        self.assertNotIn('class="legend"', page)  # no legend asked for, none drawn
        self.assertNotIn('class="fhead"', page)

    def test_page_title_and_legend_row_sit_above_the_plot(self):
        spec = {"mark": "point", "usermeta": {
            "header": {"title": "질문 <i>?", "subtitle": "부제 · n편"},
            "legend": [{"title": "연구 설계", "items": [{"label": "모형", "swatch": "dot", "color": LIGHT["d_model"]},
                                                     {"label": "관찰", "swatch": "dot", "color": "#009E73"}]},
                       {"title": "읽은 범위", "items": [{"label": "본문 확인", "swatch": "full"},
                                                     {"label": "발췌 확인", "swatch": "half"}]},
                       {"items": [{"label": "실험 범위", "swatch": "band"}]}]}}
        page = page_html(spec, "t", "c")
        head, legend, vis = page.index('class="fhead"'), page.index('class="legend"'), page.index('id="vis"')
        self.assertTrue(head < legend < vis)
        self.assertEqual(page.count('class="legend"'), 1)  # one legend row
        self.assertIn("질문 &lt;i&gt;?", page)
        self.assertIn('<span class="lg-t">연구 설계</span>', page)
        self.assertIn('fill="var(--c-d-model)"', page)  # a token colour follows dark mode
        self.assertIn('fill="var(--c-d-observational)"', page)
        self.assertIn("--c-d-model: #3A93D8;", page)  # the dark step of the blue
        self.assertIn('fill="var(--c-band)"', page)
        self.assertIn(f"--c-band: {LIGHT['band']};", page)
        self.assertIn(f"--c-band: {DARK['band']};", page)
        self.assertIn("isNarrow()", page)  # the page picks the wide or narrow row layout

    def test_theme_swap_is_unambiguous(self):
        self.assertEqual(set(LIGHT), set(DARK))
        swap = {}
        for k, v in LIGHT.items():  # the dark swap is by string: one light value, one dark value
            self.assertEqual(swap.setdefault(v, DARK[k]), DARK[k], k)

    def test_spec_cannot_break_out_of_script(self):
        page = page_html({"title": "</script><script>alert(1)</script>"}, "t", "c")
        self.assertNotIn("</script><script>alert(1)", page)

    def test_cli_writes_html_and_vl_json(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["viz", "effects", str(self.t.root), "--quantity", "kappa", "--band", "1.3,1.4",
                             "--date", "2026-01-02"])
        self.assertEqual(code, 0)
        html_path = self.t.root / "figs" / "effects-kappa.html"
        vl = self.t.root / "figs" / "effects-kappa.vl.json"
        self.assertTrue(html_path.exists() and vl.exists())
        page = html_path.read_text(encoding="utf-8")
        self.assertIn("작성 2026-01-02", page)
        self.assertIn("snu-embed-height", page)
        spec = json.loads(vl.read_text(encoding="utf-8"))
        self.assertTrue(spec["$schema"].endswith("vega-lite/v5.json"))
        self.assertIn("2026-01-02", out.getvalue())

    def test_cli_relative_out_is_inside_topic(self):
        with contextlib.redirect_stdout(io.StringIO()):
            code = cli.main(["viz", "effects", str(self.t.root), "--quantity", "modulus", "-o", "figs/bm"])
        self.assertEqual(code, 0)
        self.assertTrue((self.t.root / "figs" / "bm.html").exists())

    def test_cli_unit_mismatch_exits_2(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = cli.main(["viz", "effects", str(self.t.root), "--quantity", "."])
        self.assertEqual(code, 2)
        self.assertIn("mixed units", err.getvalue())
        self.assertFalse((self.t.root / "figs").exists())


if __name__ == "__main__":
    unittest.main()
