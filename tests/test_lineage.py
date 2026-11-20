"""Offline tests for the research-lineage tools (synthetic data; no OpenAlex calls)."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scholarly_access_agent.lineage import analyze, openalex, page, query_test, report, topic
from scholarly_access_agent.lineage.cli import main as lineage_main


def work(wid, year, refs, title, cites=10, role=(), abstract=None):
    w = {"id": f"https://openalex.org/{wid}", "title": title, "publication_year": year, "cited_by_count": cites,
         "referenced_works": [f"https://openalex.org/{r}" for r in refs],
         "authorships": [{"author": {"display_name": f"Author {wid}"}}], "_role": list(role)}
    if abstract:
        w["abstract_inverted_index"] = {t: [i] for i, t in enumerate(abstract.split())}
    return w


def synthetic_corpus(d: Path):
    """Seed S cites A,B; F1..F6 cite S and the ancestors; G is a generic tool everyone cites."""
    corpus = {
        "S": work("S", 2024, ["A", "B", "G"], "Latent long-range seed", 100, ["seed"]),
        "A": work("A", 2007, ["G"], "Neural network potential founder", 100, ["backward"]),
        "B": work("B", 2015, ["A", "G"], "Charge equilibration network", 80, ["backward"]),
    }
    for i in range(1, 7):
        refs = ["S", "A", "G"] + (["B"] if i % 2 else []) + ([f"F{i-1}"] if i > 1 else [])
        corpus[f"F{i}"] = work(f"F{i}", 2025 + (i > 3), refs, f"Electrostatic follow-up {i}", 5, ["forward"],
                               abstract="long-range electrostatic charges learned from energies")
    meta = {"G": {"id": "https://openalex.org/G", "title": "Generic DFT functional", "publication_year": 1996,
                  "cited_by_count": 200000, "authorships": [], "referenced_works": []}}
    (d / "corpus.json").write_text(json.dumps(corpus), encoding="utf-8")
    (d / "refs_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return corpus


LINEAGE = {
    "meta": {"page_title": "Test 계보", "slug": "test_lineage", "date": "2026-11-20", "headline": "Test",
             "lede": "lede", "seed_ids": ["S"], "papers_read": ["S"], "data_dir": "data"},
    "lanes": [{"label": ["A. 국소", ""], "how": "국소 합", "limit": "cutoff"},
              {"label": ["B. 잠재 전하", ""], "how": "잠재 전하 + Ewald", "limit": "국소 전하"}],
    "nodes": [{"id": "a", "lane": 0, "year": 2007, "title": "Founder", "sub": "A 2007", "openalex": "A"},
              {"id": "b", "lane": 0, "year": 2015, "title": "QEq net", "sub": "B 2015", "openalex": "B"},
              {"id": "s", "lane": 1, "year": 2024, "title": "Seed", "sub": "S 2024", "openalex": "S", "key": True},
              {"id": "f", "lane": 1, "year": 2025, "title": "Follow-up", "sub": "F1 2025", "openalex": "F1"}],
    "edges": [["a", "b", "s"], ["b", "s", "d"], ["s", "f", "m"]],
    "trends": [{"title": "From labels to energies", "points": ["moved (Seed 2024)"]}],
    "one_line": "One line.",
    "verdict": [{"tag": "현재 기본값", "title": "Seed", "points": ["adopted"]}],
    "rows": [{"year": "2024", "work": "Seed | paper", "what": "w", "change": "c", "lane": 1,
              "level": "fulltext", "evidence": "p.1", "openalex": "S"},
             {"year": "2026", "work": "Review", "what": "w", "change": "c", "lane": None,
              "level": "abstract", "openalex": "F6"}],
    "limits": ["bias"],
}


def quiet():
    return contextlib.redirect_stdout(io.StringIO())


class OpenAlexClientTests(unittest.TestCase):
    def test_long_retry_after_raises_quota_exhausted(self):
        with mock.patch.object(openalex, "_request", return_value=(429, {"Retry-After": "70000"}, {})):
            with self.assertRaises(openalex.QuotaExhausted):
                openalex.get({"filter": "x"}, sleep=lambda s: None)

    def test_failure_message_never_contains_api_key(self):
        with mock.patch.dict(os.environ, {"OPENALEX_API_KEY": "SECRET-KEY-123"}), \
                mock.patch.object(openalex, "_request", return_value=(500, {}, {})) as req:
            with self.assertRaises(openalex.OpenAlexError) as ctx:
                openalex.get({"filter": "openalex_id:W1"}, tries=2, sleep=lambda s: None)
        self.assertNotIn("SECRET-KEY-123", str(ctx.exception))
        self.assertEqual(req.call_args[0][0]["api_key"], "SECRET-KEY-123")  # key is sent, never printed

    def test_success_and_comma_rejection(self):
        with mock.patch.object(openalex, "_request", return_value=(200, {}, {"results": []})):
            self.assertEqual(openalex.get({"filter": "x"}, sleep=lambda s: None), {"results": []})
        with self.assertRaises(ValueError):
            openalex.check_query('"a" OR b, c')


class AnalysisTests(unittest.TestCase):
    def test_analyze_runs_offline_on_cached_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            d = Path(directory)
            synthetic_corpus(d)
            with mock.patch.object(analyze, "fetch_many", side_effect=AssertionError("network used")):
                with quiet():
                    analyze.main([str(d)])
            res = json.loads((d / "analysis.json").read_text(encoding="utf-8"))
            text = (d / "analysis.txt").read_text(encoding="utf-8")  # saved even when stdout is piped away
            for heading in ("== RPYS peaks", "== Core ancestors", "== Clusters ==", "== Main path ==", "== forward by year"):
                self.assertIn(heading, text)
            self.assertTrue(res["main_path"])
            self.assertIn("rpys_peaks", res)
            self.assertEqual(res["forward_by_year"], {"2025": 3, "2026": 3})

    def test_core_set_drops_generic_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            d = Path(directory)
            synthetic_corpus(d)
            core = topic.core_set(d)
            self.assertIn("A", core)          # 7 field citations of 100 → specific
            self.assertNotIn("G", core)       # cited by everyone, 200k global → generic
            self.assertTrue(topic.in_field({"referenced_works": ["https://openalex.org/A"]}, core))


class QueryTestTests(unittest.TestCase):
    def test_logs_precision_recall_and_saturation(self):
        with tempfile.TemporaryDirectory() as directory:
            d = Path(directory)
            synthetic_corpus(d)
            hits = {"meta": {"count": 3}, "results": [
                work("N1", 2025, ["A"], "New in-field"), work("N2", 2025, ["X"], "Off-field"),
                work("F1", 2025, ["A"], "Known")]}
            with mock.patch.object(query_test, "search", return_value=hits), \
                    mock.patch.object(query_test, "get", side_effect=[
                        {"results": [{"id": "https://openalex.org/S"}]},  # recall: S found
                        {"results": [{"id": "https://openalex.org/A", "title": "Founder", "publication_year": 2007}]}]):
                with quiet():
                    query_test.main([str(d), '("a" OR b) AND c', "--gold", "S,A", "--label", "t", "--list", "0"])
            log = json.loads((d / "queries.json").read_text(encoding="utf-8"))
            self.assertEqual(log[0]["on_topic"], 2)        # N1 and F1 cite core paper A
            self.assertEqual(log[0]["new_on_topic"], 1)    # only N1 is new
            self.assertEqual((log[0]["gold"], log[0]["gold_found"]), (2, 1))
            self.assertFalse(log[0]["saturated"])

    def test_batch_runs_queries_in_parallel_and_logs_in_order(self):
        with tempfile.TemporaryDirectory() as directory:
            d = Path(directory)
            synthetic_corpus(d)
            hits = {"meta": {"count": 2}, "results": [work("N1", 2025, ["A"], "New in-field"),
                                                      work("F1", 2025, ["A"], "Known")]}

            def fake_get(params):  # order-independent: threads may call in any order
                if "title_and_abstract.search:q1" in params["filter"]:
                    return {"results": [{"id": "https://openalex.org/S"}]}
                if "title_and_abstract.search" in params["filter"]:
                    return {"results": [{"id": "https://openalex.org/A"}]}
                return {"results": []}

            out = io.StringIO()
            with mock.patch.object(query_test, "search", return_value=hits), \
                    mock.patch.object(query_test, "get", side_effect=fake_get), \
                    contextlib.redirect_stdout(out):
                query_test.main([str(d), "q1 AND x", "q2 AND y", "--gold", "S,A",
                                 "--label", "first", "--label", "second", "--list", "0", "--workers", "2"])
            log = json.loads((d / "queries.json").read_text(encoding="utf-8"))
            self.assertEqual([e["label"] for e in log], ["first", "second"])
            self.assertEqual([e["gold_found_ids"] for e in log], [["S"], ["A"]])
            text = out.getvalue()
            self.assertIn("== batch summary ==", text)
            self.assertIn("strategy recall (all logged queries + this one): 2/2 (100%)", text)  # accumulates

    def test_batch_rejects_bad_query_before_any_network_call(self):
        with tempfile.TemporaryDirectory() as directory:
            d = Path(directory)
            synthetic_corpus(d)
            with mock.patch.object(query_test, "search", side_effect=AssertionError("network used")):
                with self.assertRaises(ValueError):
                    query_test.main([str(d), "good AND query", '"a" OR b, c'])


class PageAndReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "data").mkdir()
        synthetic_corpus(self.root / "data")
        with quiet():
            analyze.main([str(self.root / "data")])
        (self.root / "lineage.json").write_text(json.dumps(LINEAGE, ensure_ascii=False), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_validation_reports_problems(self):
        bad = json.loads(json.dumps(LINEAGE))
        bad["nodes"][0]["title"] = "아주 긴 한국어 상자 제목입니다"
        bad["edges"].append(["a", "zz", "s"])
        bad["nodes"][1]["lane"] = 5
        errs = page.validate(bad)
        self.assertTrue(any("wide" in e for e in errs))
        self.assertTrue(any("bad edge" in e for e in errs))
        self.assertTrue(any("out of range" in e for e in errs))
        self.assertTrue(any("Hangul or" in e for e in errs))  # tells the budget, not just the overflow
        self.assertEqual(page.validate(LINEAGE), [])

    def test_check_warns_when_an_edge_is_drawn_through_another_box(self):
        L = json.loads(json.dumps(LINEAGE))
        # all four papers in one lane: the added edge a -> f runs straight down through b and s
        for n in L["nodes"]:
            n["lane"] = 0
        L["edges"].append(["a", "f", "m"])
        hits = page.edges_through_boxes(L)
        self.assertIn(("a", "f", "m", "b"), hits)
        self.assertFalse([h for h in hits if h[:2] == ("a", "b")])  # adjacent nodes: nothing in between
        self.assertTrue(any(w.startswith("main-path edge a->f is drawn through 'b', 's'") for w in page.warnings(L)))
        # the same crossing by a thin edge is only counted, not listed
        L["edges"][-1] = ["a", "f", "d"]
        ws = page.warnings(L)
        self.assertFalse(any(w.startswith("main-path edge") for w in ws))
        self.assertIn("1 thin s/d edge(s) cross another box (usually harmless; look at the figure once)", ws)
        self.assertEqual(page.edges_through_boxes(LINEAGE), [])

    def test_check_command_exit_codes(self):
        from scholarly_access_agent.lineage import check

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(check.main([str(self.root)]), 0)
        self.assertIn("box budget: title: about", out.getvalue())
        bad = json.loads(json.dumps(LINEAGE))
        bad["edges"].append(["a", "zz", "s"])
        (self.root / "lineage.json").write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
        with quiet():
            self.assertEqual(check.main([str(self.root)]), 1)
            self.assertEqual(lineage_main(["check", str(self.root)]), 1)  # dispatched through the CLI

    def test_page_links_boxes_and_uses_shared_evidence_labels(self):
        with quiet():
            page.main([str(self.root)])
        html = (self.root / "test_lineage.html").read_text(encoding="utf-8")
        self.assertIn('href="https://openalex.org/S"', html)   # no links.json: OpenAlex fallback
        self.assertIn("본문 확인", html)
        self.assertIn("초록만 확인", html)
        self.assertIn("단계별 흐름", html)

    def test_report_section_is_renderable_markdown(self):
        rdir = self.root / "report"
        with quiet():
            self.assertEqual(report.main([str(self.root), "--report-dir", str(rdir), "--chapter", "3", "--no-figure"]), 0)
        md = (rdir / "lineage_section.md").read_text(encoding="utf-8")
        for expected in ("## 3. 계보와 흐름", "### 3.2 단계별 흐름", "| 계열 | 시기 | 방식 |",
                         "From labels to energies", "**현재 판정**", "본문 확인 (p.1", "Seed / paper"):
            self.assertIn(expected, md)
        self.assertNotIn("<", md.replace("<sub>", "").replace("<sup>", ""))  # no raw HTML
        from scholarly_access_agent.runtime.report import render_report

        doc = rdir / "doc.md"
        doc.write_text("# Doc\n\n2026-11-20 · test\n\n" + md, encoding="utf-8")
        result = render_report(doc)
        self.assertTrue(result["ok"], result)
        # CI runners may lack a Korean font (no_korean_font); only rendering problems count here
        self.assertEqual([w for w in result["warnings"] if not w.startswith("no_korean_font")], [])


class CliTests(unittest.TestCase):
    def test_dispatch_and_unknown_command(self):
        with quiet():
            self.assertEqual(lineage_main(["--help"]), 0)
        self.assertEqual(lineage_main(["nope"]), 2)
        from scholarly_access_agent.cli import main

        with quiet():
            self.assertEqual(main(["lineage", "--help"]), 0)



class WorkspaceTests(unittest.TestCase):
    def test_init_creates_topic_layout_under_research_root(self):
        from scholarly_access_agent.lineage import workspace

        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.dict(os.environ, {"SNU_RESEARCH_ROOT": directory}):
            self.assertEqual(workspace.research_root(), Path(directory))
            folder = workspace.init("LES-lineage")
            self.assertEqual(folder, Path(directory) / "LES-lineage")
            for sub in ("evidence", "figs", "archive", "data"):
                self.assertTrue((folder / sub).is_dir())
            skeleton = json.loads((folder / "lineage.json").read_text(encoding="utf-8"))
            self.assertEqual(skeleton["meta"]["slug"], "les-lineage")
            self.assertEqual(page.validate(skeleton), [])
            with self.assertRaises(ValueError):
                workspace.init("../escape")

if __name__ == "__main__":
    unittest.main()
