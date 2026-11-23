import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from scholarly_access_agent import cli, trace
from scholarly_access_agent.viz import effects, figure
from scholarly_access_agent.viz.common import LIGHT, VizError


def write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False), encoding="utf-8")


def record(authors, year, design, results, access="fulltext_pdf"):
    return {"paper_id": f"10.1/{authors}{year}", "title": f"Paper by {authors}", "authors": authors, "year": year,
            "version": "publisher PDF", "access": access, "read_via": "read_pdf", "design": design,
            "criteria": [{"criterion": "c", "evidence": [{"pdf_page": 3, "section": "Results", "read_mode": "pages"}]}],
            "results": results}


def res(rid, value, unit="%", **extra):
    return {"id": rid, "quantity": "ridership change", "value": value, "unit": unit, "condition": "1 year",
            "pdf_page": 7, **extra}


def leaves(spec):
    out = []
    for lay in spec.get("layer") or []:
        out.extend(leaves(lay) if "layer" in lay else [lay])
    return out


class FigureTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        ev = self.root / "evidence"
        write(ev / "bull2021.json", record("Oliver Bull", 2021, "RCT", [
            res("trips", 12, lo=8, hi=16), res("fare", 1000, unit="CLP")]))
        write(ev / "lee2025.json", record("Lee", 2025, "quasi-experimental DiD", [
            res("use", 2.7), res("fare", 62000, unit="KRW")], access="abstract_only"))
        write(ev / "ziedan2024.json", record("Abubakr Ziedan", 2024, "quasi DiD", [
            res("bus", "3.6-4.1", read_mode="terms"), res("cap", 5, unit="USD")]))
        write(ev / "gone2020.json", record("Gone", 2020, "RCT", [res("x", 9)], access="unavailable"))
        self.records = figure.records_of(self.root)

    def spec(self, form="forest", rows=None, **extra):
        rows = rows if rows is not None else [
            {"key": "bull2021", "result": "trips", "label": "Bull 2021 · 산티아고 RCT", "group": "실험"},
            {"key": "lee2025", "result": "use", "group": "준실험"},
            {"key": "ziedan2024", "result": "bus", "group": "준실험"}]
        return {"question": "Q1 얼마나 늘리나?", "takeaway": "단기 +2.7~12%", "form": form,
                "x": {"title": "이용 변화", "unit": "%"}, "rows": rows, **extra}

    # ---------------------------------------------------------------- provenance

    def test_rows_take_numbers_page_and_read_depth_from_evidence(self):
        rows, problems, info = figure.resolve_rows(self.spec(), self.records)
        self.assertEqual(problems, [])
        by = {r["record"]: r for r in rows}
        self.assertEqual((by["bull2021"]["value"], by["bull2021"]["lo"], by["bull2021"]["hi"]), (12.0, 8.0, 16.0))
        self.assertEqual((by["ziedan2024"]["value"], by["ziedan2024"]["lo"]), (3.85, 3.6))
        self.assertEqual(by["bull2021"]["page"], "7")
        self.assertEqual(by["bull2021"]["label"], "본문 확인")
        self.assertEqual(by["bull2021"]["fill"], "full")
        self.assertEqual(by["ziedan2024"]["label"], "발췌 확인")  # read_mode terms
        self.assertEqual(by["lee2025"]["fill"], "hollow")       # abstract only
        self.assertEqual(by["bull2021"]["line1"], "Bull 2021")
        self.assertEqual(by["bull2021"]["line2"], "산티아고 RCT")
        self.assertEqual(by["bull2021"]["source"], "evidence/bull2021.json#trips")
        self.assertEqual(info["units"]["x"], "%")

    def test_literal_numbers_unknown_keys_and_results_are_refused(self):
        rows = [{"key": "bull2021", "result": "trips", "value": 12},
                {"key": "nobody2020", "result": "trips"},
                {"key": "bull2021", "result": "nope"},
                {"label": "made up", "value": 5}]
        _, problems, _ = figure.resolve_rows(self.spec(rows=rows), self.records)
        rules = [(p["row"], p["rule"]) for p in problems.errors]
        self.assertIn((0, "literal_number"), rules)
        self.assertIn((1, "unknown_key"), rules)
        self.assertIn((2, "unknown_result"), rules)
        self.assertIn((3, "literal_number"), rules)
        with self.assertRaises(VizError) as ctx:
            figure.build(self.root, self.spec(rows=rows))
        self.assertIn("literal_number", str(ctx.exception))

    def test_unit_mismatch_and_mixed_units(self):
        bad = self.spec(rows=[{"key": "bull2021", "result": "fare"}])
        _, problems, _ = figure.resolve_rows(bad, self.records)
        self.assertEqual([p["rule"] for p in problems.errors], ["unit_mismatch"])
        mixed = self.spec(rows=[{"key": "bull2021", "result": "trips"}, {"key": "lee2025", "result": "fare"}])
        mixed["x"] = {"title": "값"}
        _, problems, _ = figure.resolve_rows(mixed, self.records)
        self.assertEqual([p["rule"] for p in problems.errors], ["mixed_units"])
        # "percent" and "%" are the same unit
        same = self.spec(rows=[{"key": "bull2021", "result": "trips"}])
        same["x"]["unit"] = "percent"
        self.assertEqual(figure.resolve_rows(same, self.records)[1], [])

    def test_computed_rows(self):
        ok = {"computed": True, "op": "mean", "label": "Ziedan 2024 · 중간값",
              "inputs": [{"key": "ziedan2024", "result": "bus", "field": "lo"}, {"key": "ziedan2024", "result": "bus.hi"}]}
        rows, problems, _ = figure.resolve_rows(self.spec(rows=[ok]), self.records)
        self.assertEqual(problems, [])
        self.assertAlmostEqual(rows[0]["value"], 3.85)
        self.assertTrue(rows[0]["computed"])
        self.assertIn("mean(ziedan2024#bus.lo = 3.6, ziedan2024#bus.hi = 4.1)", rows[0]["how"])
        self.assertEqual(rows[0]["label"], "발췌 확인")  # the weakest input's read depth
        given = dict(ok, value=3.85)
        self.assertEqual(figure.resolve_rows(self.spec(rows=[given]), self.records)[1], [])
        wrong = dict(ok, value=5)
        self.assertEqual([p["rule"] for p in figure.resolve_rows(self.spec(rows=[wrong]), self.records)[1]],
                         ["computed_mismatch"])
        dangling = {"computed": True, "value": 3.85, "inputs": [{"key": "ziedan2024", "result": "nope"}]}
        self.assertEqual([p["rule"] for p in figure.resolve_rows(self.spec(rows=[dangling]), self.records)[1]],
                         ["unknown_result"])
        no_inputs = {"computed": True, "value": 3.85}
        self.assertEqual([p["rule"] for p in figure.resolve_rows(self.spec(rows=[no_inputs]), self.records)[1]],
                         ["computed_without_inputs"])
        mixed = {"computed": True, "op": "sum", "inputs": [{"key": "bull2021", "result": "trips"},
                                                           {"key": "bull2021", "result": "fare"}]}
        self.assertEqual([p["rule"] for p in figure.resolve_rows(self.spec(rows=[mixed]), self.records)[1]],
                         ["unit_mismatch"])
        spec, _ = figure.build(self.root, self.spec(rows=[ok, {"key": "bull2021", "result": "trips"}]))
        by = {r["id"]: r for r in spec["data"]["values"]}
        self.assertEqual(by["computed"]["value_text"], "≈3.9%")
        self.assertIn({"field": "how", "title": "계산"}, next(l for l in leaves(spec) if l.get("encoding", {}).get(
            "tooltip"))["encoding"]["tooltip"])

    def test_unread_rows_are_left_out_and_counted(self):
        spec, meta = figure.build(self.root, self.spec(rows=[{"key": "bull2021", "result": "trips"},
                                                             {"key": "gone2020", "result": "x"}]))
        self.assertEqual(len(spec["data"]["values"]), 1)
        self.assertIn("미확인 1건 생략", meta["notes"])

    # ---------------------------------------------------------------- forms

    def test_forest_title_subtitle_groups_and_zero_line(self):
        spec, meta = figure.build(self.root, self.spec(zero=True, band={"lo": 3, "hi": 5, "label": "목표"}), "figs/q1.fig.json")
        head = spec["usermeta"]["header"]
        self.assertEqual((head["title"], head["subtitle"]), ("단기 +2.7~12%", "Q1 얼마나 늘리나?"))
        heads = [v["text"] for l in leaves(spec) for v in (l.get("data") or {}).get("values", []) if "n" in v]
        self.assertEqual(heads, ["실험 · 1개 값", "준실험 · 2개 값"])  # the spec's groups, in its order
        domain = leaves(spec)[0]["encoding"]["x"]["scale"]["domain"]
        self.assertEqual(domain[0], 0.0)
        self.assertEqual(spec["usermeta"]["figure"], {"form": "forest", "spec": "figs/q1.fig.json", "rows": 3})
        self.assertIn("figs/q1.fig.json", meta["source"])
        self.assertEqual(meta["title"], "단기 +2.7~12%")

    def test_every_form_builds(self):
        for form in ("dot", "bar", "strip"):
            spec, _ = figure.build(self.root, self.spec(form))
            marks = [l["mark"]["type"] if isinstance(l["mark"], dict) else l["mark"] for l in leaves(spec)]
            if form == "bar":
                self.assertIn("rect", marks)
                self.assertEqual(leaves(spec)[0]["encoding"]["x"]["scale"]["domain"][0], 0.0)  # bars start at 0
            if form == "strip":  # one label row per group
                labels = next(l for l in spec["layer"] if "data" in l and l["data"]["values"]
                              and "line1" in l["data"]["values"][0] and "layer" in l)
                self.assertEqual([v["line1"] for v in labels["data"]["values"]], ["실험", "준실험"])
        line = self.spec("line", rows=[{"key": "bull2021", "result": "trips", "group": "A"},
                                       {"key": "lee2025", "result": "use", "group": "A"},
                                       {"key": "ziedan2024", "result": "bus", "group": "B"}])
        line["y"] = {"title": "이용 변화", "unit": "%"}
        spec, _ = figure.build(self.root, line)
        self.assertEqual(spec["layer"][0]["mark"]["type"], "line")
        self.assertEqual(spec["layer"][0]["encoding"]["x"]["axis"]["format"], "d")  # x = record year
        self.assertEqual(sorted(d["xv"] for d in spec["data"]["values"]), [2021, 2024, 2025])
        stacked = self.spec("stacked", rows=[{"key": "bull2021", "result": "trips", "bar": "합계", "stack": "버스"},
                                             {"key": "lee2025", "result": "use", "bar": "합계", "stack": "지하철"}])
        spec, _ = figure.build(self.root, stacked)
        self.assertEqual(spec["encoding"]["x"]["stack"], "zero")
        self.assertEqual(spec["encoding"]["color"]["scale"]["domain"], ["버스", "지하철"])
        scatter = self.spec("scatter", rows=[{"key": "bull2021", "x_result": "trips", "y_result": "trips"},
                                             {"key": "lee2025", "x_result": "use", "y_result": "use"}])
        scatter["y"] = {"title": "y", "unit": "%"}
        spec, _ = figure.build(self.root, scatter)
        self.assertEqual([(d["xv"], d["yv"]) for d in spec["data"]["values"]], [(12.0, 12.0), (2.7, 2.7)])
        bad = self.spec("scatter", rows=[{"key": "bull2021", "x_result": "trips", "y_result": "fare"}])
        bad["y"] = {"title": "y", "unit": "%"}
        self.assertEqual([p["rule"] for p in figure.resolve_rows(bad, self.records)[1]], ["unit_mismatch"])

    def test_escape_hatch_takes_only_rows(self):
        vl = {"mark": "bar", "encoding": {"y": {"field": "line1", "type": "nominal"},
                                          "x": {"field": "value", "type": "quantitative"}},
              "config": {"axis": {"labelFontSize": 14}}}
        spec, _ = figure.build(self.root, self.spec("forest", vegalite=vl))
        self.assertEqual(len(spec["data"]["values"]), 3)
        self.assertEqual(spec["config"]["axis"]["labelFontSize"], 14)       # the user's tweak on top
        self.assertEqual(spec["config"]["axis"]["labelColor"], LIGHT["muted"])  # the token config underneath
        self.assertEqual(spec["width"], "container")
        for sneaky in ({"mark": "bar", "data": {"values": [{"value": 99}]}},
                       {"layer": [{"mark": "point", "data": {"url": "x.csv"}}]},
                       {"mark": "point", "transform": [{"lookup": "k", "from": {"data": {"values": []}, "key": "k"}}]}):
            with self.assertRaises(VizError) as ctx:
                figure.build(self.root, self.spec("forest", vegalite=sneaky))
            self.assertIn("may not bring its own data", str(ctx.exception))

    def test_effects_shares_the_row_renderer(self):
        spec, _ = effects.build(self.root, "ridership", unit="%")
        self.assertIn("rows", spec["usermeta"])
        self.assertEqual(spec["params"][0]["name"], "narrow")

    # ---------------------------------------------------------------- cli and trace

    def test_cli_writes_next_to_the_spec(self):
        write(self.root / "figs" / "q1.fig.json", self.spec())
        with contextlib.redirect_stdout(io.StringIO()):
            code = cli.main(["viz", "figure", str(self.root), "--spec", "figs/q1.fig.json", "--date", "2026-01-02"])
        self.assertEqual(code, 0)
        page = (self.root / "figs" / "q1.html").read_text(encoding="utf-8")
        self.assertIn("<title>단기 +2.7~12%</title>", page)
        self.assertTrue((self.root / "figs" / "q1.vl.json").exists())
        write(self.root / "figs" / "bad.fig.json", self.spec(rows=[{"key": "bull2021", "result": "trips", "value": 1}]))
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = cli.main(["viz", "figure", str(self.root), "--spec", "figs/bad.fig.json"])
        self.assertEqual(code, 2)
        self.assertIn("literal_number", err.getvalue())
        self.assertFalse((self.root / "figs" / "bad.html").exists())

    def test_report_trace_checks_figure_specs(self):
        write(self.root / "figs" / "good.fig.json", self.spec())
        write(self.root / "figs" / "bad.fig.json", self.spec(rows=[{"key": "nobody", "result": "x"},
                                                                   {"key": "bull2021", "result": "gone"}]))
        write(self.root / "figs" / "plain.html", "<html></html>")  # no spec: not checked
        report = self.root / "README.md"
        report.write_text("# R\n\n효과는 12%다 [@bull2021].\n\n![좋은 그림](figs/good.html)\n\n"
                          "![나쁜 그림](figs/bad.html \"height=400\")\n\n![그냥](figs/plain.html)\n", encoding="utf-8")
        result = trace.trace_report(report)
        rules = [(f["line"], f["rule"]) for f in result["findings"]]
        self.assertIn((7, "figure_unknown_key"), rules)
        self.assertIn((7, "figure_unknown_result"), rules)
        self.assertFalse(any(line == 5 for line, _ in rules))
        self.assertFalse(result["ok"])
        self.assertEqual(result["summary"]["figure_findings"], 2)
        self.assertIn("figs/bad.fig.json: row 1: no evidence/nobody.json",
                      [f["message"] for f in result["findings"]])


if __name__ == "__main__":
    unittest.main()
