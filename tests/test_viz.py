import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from scholarly_access_agent import cli
from scholarly_access_agent.viz import effects, lineage_charts, matrix, novelty
from scholarly_access_agent.viz.common import VEGA, VEGA_EMBED, VEGA_LITE, VizError, page_html


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


MATRIX_MD = """# 공백 행렬

## 힘 × 방식

| 힘 \\ 방식 | MD 직접 (GK) | 모드 분해 (AF·NMD) |
| --- | --- | --- |
| 경험 포텐셜 (BKS) | covered — [alpha2014] [beta2020] | **contested** — [alpha2014] vs [beta2020] |
| 범용 MLIP (MACE) | **empty-searched** (2 queries) | empty-unsearched |
| DFT 직접 | thin: [beta2020] C9 | 메모만 |

## 영역

| 영역 | 상태 |
| --- | --- |
| 저온 | thin |
"""

CARDS_MD = """# 카드

## C1 — 범용 MLIP 모드 분해
- **Gap:** 범용 MLIP × 모드 분해 (`empty-unsearched`), 문헌 공백

## C2 — 저온 PIMD
- **Gap:** PIMD × 유리 (`empty-searched`)
"""


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
        self.assertEqual(by_id["r1"]["design"], "모형")
        self.assertEqual(by_id["b1"]["design"], "관찰")
        self.assertEqual(by_id["r1"]["study"], "Alpha 2014")
        self.assertEqual(by_id["b1"]["study"], "Beta 2020")
        point = spec["layer"][-1]
        scale = point["encoding"]["fillOpacity"]["scale"]
        self.assertEqual(dict(zip(scale["domain"], scale["range"])), {"본문 확인": 1.0, "발췌 확인": 0.45, "초록만 확인": 0.0})
        self.assertEqual(spec["usermeta"]["access_key"][-1], {"label": "초록만 확인", "fill_opacity": 0.0})
        colors = point["encoding"]["color"]["scale"]
        self.assertEqual(dict(zip(colors["domain"], colors["range"])), {"모형": "#0072B2", "관찰": "#009E73"})
        band = spec["layer"][0]
        self.assertEqual(band["data"]["values"][0]["lo"], 1.3)
        self.assertEqual(band["data"]["values"][0]["text"], "실험")
        self.assertIn("미확인 1건 생략", meta["notes"])
        # ordered by year: Alpha 2014 rows before Beta 2020
        order = point["encoding"]["y"]["sort"]
        self.assertTrue(order.index(by_id["r1"]["row"]) < order.index(by_id["b1"]["row"]))
        self.assertEqual(spec["width"], "container")

    def test_sort_by_value(self):
        spec, _ = effects.build(self.t.root, "kappa", sort="value")
        values = [r["value"] for r in spec["data"]["values"]]
        self.assertEqual(values, sorted(values))

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


class MatrixTests(unittest.TestCase):
    def setUp(self):
        self.t = Topic()
        self.addCleanup(self.t.cleanup)
        write(self.t.root / "ideas" / "matrix.md", MATRIX_MD)
        write(self.t.root / "ideas" / "cards.md", CARDS_MD)

    def test_parse_first_table(self):
        m = matrix.parse_matrix_md(MATRIX_MD)
        self.assertEqual(m["row_axis"], "힘")
        self.assertEqual(m["column_axis"], "방식")
        self.assertEqual(m["columns"], ["MD 직접 (GK)", "모드 분해 (AF·NMD)"])
        self.assertEqual(m["rows"], ["경험 포텐셜 (BKS)", "범용 MLIP (MACE)", "DFT 직접"])  # second table ignored
        cells = {(c["row"], c["column"]): c for c in m["cells"]}
        first = cells[("경험 포텐셜 (BKS)", "MD 직접 (GK)")]
        self.assertEqual(first["state"], "covered")
        self.assertEqual(first["refs"], ["alpha2014", "beta2020"])
        self.assertEqual(cells[("경험 포텐셜 (BKS)", "모드 분해 (AF·NMD)")]["state"], "contested")
        self.assertEqual(cells[("범용 MLIP (MACE)", "MD 직접 (GK)")]["state"], "empty-searched")
        self.assertEqual(cells[("범용 MLIP (MACE)", "모드 분해 (AF·NMD)")]["state"], "empty-unsearched")
        self.assertEqual(cells[("DFT 직접", "MD 직접 (GK)")]["cards"], ["C9"])
        no_kw = cells[("DFT 직접", "모드 분해 (AF·NMD)")]
        self.assertFalse(no_kw["state_given"])

    def test_build_writes_matrix_json_then_reads_it(self):
        spec, meta = matrix.build(self.t.root)
        j = self.t.root / "ideas" / "matrix.json"
        self.assertTrue(j.exists())
        data = json.loads(j.read_text(encoding="utf-8"))
        placed = {(c["row"], c["column"]): c["cards"] for c in data["cells"]}
        self.assertEqual(placed[("범용 MLIP (MACE)", "모드 분해 (AF·NMD)")], ["C1"])
        self.assertEqual(data["unplaced_cards"], ["C2"])
        values = spec["data"]["values"]
        self.assertEqual(len(values), 6)
        covered = next(v for v in values if v["row_full"] == "경험 포텐셜 (BKS)" and v["col_full"] == "MD 직접 (GK)")
        self.assertTrue(covered["mark"].startswith("●"))
        self.assertIn("Alpha 2014", covered["papers"])
        c1 = next(v for v in values if v["cards"] == "C1")
        self.assertEqual(c1["mark"], "? C1")
        domain = spec["layer"][0]["encoding"]["color"]["scale"]["domain"]
        self.assertEqual(len(domain), 5)
        self.assertIn("matrix.md", meta["source"])
        # edit the JSON: later runs use it rather than the Markdown
        data["cells"][0]["state"] = "thin"
        write(j, data)
        spec2, meta2 = matrix.build(self.t.root)
        self.assertIn("matrix.json", meta2["source"])
        self.assertTrue(spec2["data"]["values"][0]["state"].startswith("◔ thin"))

    def test_no_write_json(self):
        matrix.build(self.t.root, write_json=False)
        self.assertFalse((self.t.root / "ideas" / "matrix.json").exists())

    def test_missing_matrix(self):
        (self.t.root / "ideas" / "matrix.md").unlink()
        with self.assertRaises(VizError):
            matrix.build(self.t.root)


class NoveltyTests(unittest.TestCase):
    def setUp(self):
        self.t = Topic()
        self.addCleanup(self.t.cleanup)
        nov = self.t.root / "ideas" / "novelty"
        write(nov / "C1.json", {"card": "C1", "verdict": "novel", "closest": [
            {"paper_id": "10.1/Ann Alpha2014", "access": "fulltext_pdf", "read_via": "evidence/alpha2014.json",
             "grade": "Medium"},
            {"paper_id": "arXiv:1", "access": "abstract_only", "read_via": "web_summary", "grade": "Medium"},
            {"paper_id": "arXiv:2", "access": "unavailable", "read_via": "none", "grade": "Low"}]})
        write(nov / "C10.json", {"card": "C10", "closest": [
            {"paper_id": "arXiv:3", "access": "excerpts", "grade": "High"}]})
        write(nov / "C2.json", {"card": "C2", "verdict": "reframe", "closest": [
            {"paper_id": "arXiv:4", "access": "fulltext_pdf", "read_via": "read_pdf", "pdf_page": 2,
             "read_mode": "pages", "grade": "unknown"}]})

    def test_strip_positions_access_and_verdicts(self):
        spec, meta = novelty.build(self.t.root)
        pts = spec["layer"][0]["data"]["values"]
        self.assertEqual(len(pts), 4)  # the unavailable one is left out
        c1 = sorted((p for p in pts if p["card"] == "C1"), key=lambda p: p["x"])
        self.assertEqual([p["grade"] for p in c1], ["Medium", "Medium"])
        self.assertAlmostEqual(c1[0]["x"] + c1[1]["x"], 6.0)  # two papers centred on Medium (3)
        self.assertNotEqual(c1[0]["x"], c1[1]["x"])
        labels = {p["paper"]: p["label"] for p in pts}
        self.assertEqual(labels["Alpha 2014"], "본문 확인")  # read through the evidence record
        self.assertEqual(labels["arXiv:1"], "초록만 확인")
        self.assertEqual(labels["arXiv:3"], "발췌 확인")
        self.assertEqual(labels["arXiv:4"], "본문 확인")
        unknown = next(p for p in pts if p["paper"] == "arXiv:4")
        self.assertEqual((unknown["g"], unknown["grade"]), (0, "미등급"))
        verdicts = spec["layer"][1]["data"]["values"]
        self.assertEqual([v["card"] for v in verdicts], ["C1", "C2", "C10"])  # numeric card order
        texts = {v["card"]: v["text"] for v in verdicts}
        self.assertEqual(texts["C1"], "새로움 · 미확인 1")
        self.assertEqual(texts["C2"], "재구성")
        self.assertEqual(texts["C10"], "재구성")  # no stored verdict: derived from the High grade
        self.assertEqual(spec["layer"][0]["encoding"]["x"]["scale"]["domain"][0], -0.5)  # room for 미등급
        self.assertIn("미확인 1편 생략", meta["notes"])

    def test_no_novelty(self):
        empty = tempfile.TemporaryDirectory()
        self.addCleanup(empty.cleanup)
        with self.assertRaises(VizError):
            novelty.build(Path(empty.name))


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
        page = page_html({"mark": "point", "usermeta": {"access_key": [{"label": "본문 확인", "fill_opacity": 1}]}},
                         "제목 </title>", "자료: x <b>")
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
        self.assertIn("본문 확인", page)

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
