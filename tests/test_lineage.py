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


def fake_sorted_get(cited, newest, count=999):
    """OpenAlex stand-in: answers by the requested sort order; records every request."""
    calls = []

    def fake(params, **kw):
        calls.append(params)
        ids = cited if params.get("sort") == "cited_by_count:desc" else newest
        cites = 500 if params.get("sort") == "cited_by_count:desc" else 0
        return {"results": [work(i, 2026, [], f"T {i}", cites=cites) for i in ids][:params.get("per-page", 25)],
                "meta": {"count": count}}
    return fake, calls


class RecencyMixTests(unittest.TestCase):
    """Capped lists must not be ranked by citations alone: new papers have had no time to be cited."""

    def test_capped_list_keeps_newest_low_cited_works(self):
        fake, calls = fake_sorted_get(["C1", "C2", "C3", "C4"], ["N1", "N2", "N3", "N4"])
        with mock.patch.object(openalex, "get", side_effect=fake):
            works, total = openalex.top_mixed({"filter": "cites:S"}, 4)
        self.assertEqual(list(works), ["C1", "C2", "N1", "N2"])
        self.assertEqual(total, 999)
        self.assertEqual({c["sort"] for c in calls}, {"cited_by_count:desc", "publication_date:desc"})

    def test_overlap_is_filled_from_the_cited_ranking(self):
        fake, _ = fake_sorted_get(["C1", "C2", "C3", "C4"], ["C1", "C2", "N1"])
        with mock.patch.object(openalex, "get", side_effect=fake):
            works, _ = openalex.top_mixed({"filter": "x"}, 4)
        self.assertEqual(sorted(works), ["C1", "C2", "C3", "N1"])

    def test_fetch_citing_with_limit_includes_newest(self):
        fake, calls = fake_sorted_get(["C1", "C2"], ["N1", "N2"])
        with mock.patch.object(openalex, "get", side_effect=fake):
            works = openalex.fetch_citing("W9", 2)
        self.assertEqual(sorted(works), ["C1", "N1"])
        self.assertTrue(all(c["filter"] == "cites:W9" for c in calls))

    def test_collect_keyword_widening_includes_newest(self):
        from scholarly_access_agent.lineage import collect
        fake, _ = fake_sorted_get(["C1", "C2"], ["N1", "N2"])
        with mock.patch.object(openalex, "get", side_effect=fake):
            works = collect.search_keyword("latent charge", "", 2)
        self.assertEqual(sorted(works), ["C1", "N1"])

    def test_search_fallback_is_mixed_and_keeps_the_count(self):
        def fake(params, **kw):
            if params.get("sort") == "relevance_score:desc":
                raise openalex.OpenAlexError("relevance sort unavailable")
            return fake_mixed(params)
        fake_mixed, _ = fake_sorted_get(["C1", "C2"], ["N1", "N2"], count=42)
        with mock.patch.object(openalex, "get", side_effect=fake):
            d = openalex.search("a AND b", 2)
        self.assertEqual(sorted(w["id"].rsplit("/", 1)[-1] for w in d["results"]), ["C1", "N1"])
        self.assertEqual(d["meta"]["count"], 42)


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

    def test_report_figure_points_the_html_report_at_the_clickable_page(self):
        from PIL import Image as PILImage

        def fake_figure(L, links, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            PILImage.new("RGB", (8, 8)).save(path)

        rdir = self.root / "report"
        with quiet(), mock.patch.object(report, "render_figure", side_effect=fake_figure):
            self.assertEqual(report.main([str(self.root), "--report-dir", str(rdir), "--chapter", "3"]), 0)
        md = (rdir / "lineage_section.md").read_text(encoding="utf-8")
        self.assertIn('(figs/lineage.png "interactive=test_lineage.html")', md)

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
        # CI runners may lack a Korean font or Quarto; only rendering problems count here
        self.assertEqual([w for w in result["warnings"]
                          if not w.startswith(("no_korean_font", "quarto_unavailable"))], [])


TOPIC = {
    "meta": {"mode": "topic", "page_title": "정기권 지도", "slug": "topic_map", "date": "2026-11-23",
             "headline": "Topic", "lede": "lede", "data_dir": "data"},
    "lanes": [{"kind": "events", "label": "정책·사건"},
              {"question": "이용을 얼마나 늘리나?", "answer": "단기 +2.7~12%"},
              {"question": "가격은 어떻게 정하나?", "answer": "이부요금"}],
    "nodes": [{"id": "ev", "kind": "event", "lane": 0, "year": 1998, "title": "MetroCard"},
              {"id": "h", "lane": 1, "year": 2000, "title": "MetroCard 평가", "sub": "Hirsch 2000", "openalex": "W1",
               "design": "observational", "ref": 5},
              {"id": "b", "lane": 1, "year": 2021, "title": "RCT", "sub": "Bull 2021", "openalex": "W2",
               "design": "experiment"},
              {"id": "s", "lane": 2, "year": 1967, "title": "클럽형 정기권", "sub": "Sherman 1967", "openalex": "W3",
               "design": "model"},
              {"id": "c", "lane": 2, "year": 1988, "title": "이부요금", "sub": "Carbajo 1988", "openalex": "W4",
               "design": "model"},
              {"id": "r", "lane": 2, "year": 2021, "title": "리뷰", "sub": "Hörcher 외 2021", "openalex": "W5",
               "design": "review"}],
    "edges": [["s", "c", "s"], ["c", "r", "s"], ["h", "b", "d"], ["h", "ev", "e"]],
    "limits": ["demo"],
}


class TopicModeTests(unittest.TestCase):
    def topic(self):
        return json.loads(json.dumps(TOPIC))

    def test_valid_topic_file_has_no_problems_or_warnings(self):
        self.assertEqual(page.validate(TOPIC), [])
        self.assertEqual(page.warnings(TOPIC), [])  # the e edge runs backward in time by design: no warning

    def test_missing_question_blocks_and_missing_answer_warns(self):
        L = self.topic()
        del L["lanes"][1]["question"]
        L["lanes"][1]["label"] = "이용"
        self.assertTrue(any("lane 1: topic mode needs a 'question'" in e for e in page.validate(L)))
        L = self.topic()
        del L["lanes"][2]["answer"]
        self.assertEqual(page.validate(L), [])
        self.assertTrue(any("question lane 2" in w and "no 'answer'" in w for w in page.warnings(L)))

    def test_bad_e_edges_are_problems(self):
        L = self.topic()
        L["edges"].append(["h", "b", "e"])      # study -> study
        L["edges"].append(["ev", "h", "e"])     # event -> study
        L["edges"].append(["s", "ev", "s"])     # event joined by a non-e edge
        errs = page.validate(L)
        self.assertEqual(sum("from a study node to the event node" in e for e in errs), 2)
        self.assertTrue(any("only through 'e' edges" in e for e in errs))

    def test_event_outside_events_lane_and_second_events_lane(self):
        L = self.topic()
        L["nodes"][0]["lane"] = 1
        self.assertTrue(any("event node in lane 1, which is not the events lane" in e for e in page.validate(L)))
        L = self.topic()
        L["nodes"][1]["lane"] = 0
        self.assertTrue(any("study node in the events lane" in e for e in page.validate(L)))
        L = self.topic()
        L["lanes"].append({"kind": "events"})
        self.assertTrue(any("2 events lanes" in e for e in page.validate(L)))

    def test_topic_warnings_design_thin_lane_and_question_count(self):
        L = self.topic()
        del L["nodes"][2]["design"]
        L["nodes"][2]["design"] = None
        L["lanes"] += [{"question": f"Q{k}?", "answer": "a"} for k in range(4)]
        ws = page.warnings(L)
        self.assertTrue(any("without 'design'" in w and ": b" in w for w in ws))
        self.assertTrue(any("6 question lanes (> 5)" in w for w in ws))
        self.assertTrue(any("question lane 3" in w and "0 studies" in w for w in ws))
        L["nodes"][2]["design"] = "survey"
        self.assertTrue(any("design 'survey'" in e for e in page.validate(L)))

    def test_unlinked_study_is_allowed_with_a_reason_and_warned(self):
        L = self.topic()
        del L["nodes"][2]["openalex"]
        self.assertTrue(any("needs 'openalex'" in e for e in page.validate(L)))
        L["nodes"][2]["unlinked"] = "no record found"
        self.assertEqual(page.validate(L), [])
        self.assertTrue(any("node b has no link" in w for w in page.warnings(L)))
        self.assertIn('<g tabindex="0" class="node"', page.svg(L, page.Links({}, {})))

    def test_same_lane_edge_skipping_a_box_bows_around_it(self):
        L = self.topic()
        L["edges"].append(["s", "r", "d"])  # 1967 -> 2021 in lane 2 passes the 1988 box
        self.assertEqual(page.edges_through_boxes(L), [])

    def test_page_shows_events_band_answer_cells_and_design_legend(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "lineage.json").write_text(json.dumps(TOPIC, ensure_ascii=False), encoding="utf-8")
            with quiet():
                page.main([str(root)])
            html = (root / "topic_map.html").read_text(encoding="utf-8")
        self.assertIn('class="node ev"', html)                 # event pill
        self.assertIn('class="e ev"', html)                    # evaluates edge
        self.assertIn('<g class="ans" data-lane="1">', html)   # answer cell at the end of the lane
        self.assertIn("단기 +2.7~12%", html)
        self.assertIn(">Q1</text>", html)
        self.assertIn("이용을 얼마나 늘리나?", html)
        for label in page.DESIGN_KO.values():                   # legend inside the SVG (the PNG carries it)
            self.assertIn(label, html)
        self.assertIn("var(--d-observational)", html)
        self.assertIn("질문별 지금의 답", html)
        self.assertNotIn("데이터로 본 근거", html)              # no corpus: section left out, not empty
        # the events band is the first, narrower column
        geo = page.Geo(TOPIC)
        self.assertEqual(geo.order[0], 0)
        self.assertLess(geo.w[0], geo.w[1])

    def test_report_section_has_per_question_table(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "lineage.json").write_text(json.dumps(TOPIC, ensure_ascii=False), encoding="utf-8")
            with quiet():
                self.assertEqual(report.main([str(root), "--chapter", "4", "--no-figure"]), 0)
            md = (root / "lineage_section.md").read_text(encoding="utf-8")
        self.assertIn("## 4. 질문별 연구 지도", md)
        self.assertIn("| 질문 | 지금의 답 | 핵심 연구 |", md)
        self.assertIn("| Q1. 이용을 얼마나 늘리나? | 단기 +2.7~12% | Hirsch 2000 [5]: 관찰자료; Bull 2021: 실험(무작위) |", md)
        self.assertIn("MetroCard (1998; 평가: Hirsch 2000 [5])", md)
        self.assertNotIn("| 계열 |", md)
        self.assertNotIn("analysis.json", md)
        self.assertNotIn("<", md)

    def test_lineage_mode_with_design_colours_boxes_and_adds_legend(self):
        L = json.loads(json.dumps(LINEAGE))
        plain = page.svg(L, page.Links({}, {}))
        self.assertNotIn("--d-", plain)
        L["nodes"][0]["design"] = "model"
        coloured = page.svg(L, page.Links({}, {}))
        self.assertIn("stroke:var(--d-model)", coloured)
        self.assertIn("모형·이론", coloured)
        self.assertNotIn("관찰자료", coloured)  # lineage mode lists only the designs in use

    def test_transit_example_checks_clean(self):
        ex = Path(__file__).resolve().parents[1] / "skills" / "research-lineage" / "examples" / "transit" / "lineage.json"
        L = json.loads(ex.read_text(encoding="utf-8"))
        self.assertEqual(page.validate(L), [])
        ws = page.warnings(L)
        self.assertEqual(len(ws), 1)  # the one unlinked review, explained in its 'unlinked' field and limits
        self.assertIn("node rodrigue has no link", ws[0])


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
