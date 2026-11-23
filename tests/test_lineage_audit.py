"""Offline tests for the lineage evidence checks: edge basis and citation links, disputes, adoption share,
independent gold set and saturation, and the search log (synthetic data; no OpenAlex calls)."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scholarly_access_agent.lineage import adoption, audit, check, gold, mentions, openalex, page, query_test, report
from scholarly_access_agent.lineage.cli import main as lineage_main

from test_lineage import LINEAGE, quiet, synthetic_corpus, work


def run_out(fn, *args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = fn(*args)
    return rc, out.getvalue()


def lineage_copy():
    return json.loads(json.dumps(LINEAGE))


class TopicFolder(unittest.TestCase):
    """A topic folder with data/corpus.json (synthetic_corpus) and lineage.json."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        synthetic_corpus(self.data)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, L):
        (self.root / "lineage.json").write_text(json.dumps(L, ensure_ascii=False), encoding="utf-8")

    def check(self, *extra):
        return run_out(check.main, [str(self.root), *extra])


class EdgeObjectTests(TopicFolder):
    def test_object_edges_validate_and_draw_like_arrays(self):
        L = lineage_copy()
        L2 = lineage_copy()
        L2["edges"] = [{"from": "a", "to": "b", "type": "s", "basis": "cites", "evidence": "B 2015 §2"},
                       {"from": "b", "to": "s", "type": "d"}, ["s", "f", "m"]]
        self.assertEqual(page.validate(L2), [])
        self.assertEqual(page.edge_list(L2), page.edge_list(L))
        links = page.Links({}, {})
        self.assertEqual(page.svg(L2, links), page.svg(L, links))
        self.assertEqual(page.warnings(L2), page.warnings(L))

    def test_bad_basis_and_evidence_are_problems(self):
        L = lineage_copy()
        L["edges"][0] = {"from": "a", "to": "b", "type": "s", "basis": "vibes", "evidence": 3}
        errs = page.validate(L)
        self.assertTrue(any("basis 'vibes' must be one of" in e for e in errs))
        self.assertTrue(any("evidence must be a locator string" in e for e in errs))
        L["edges"][0] = {"from": "a", "to": "zz", "type": "s"}
        self.assertTrue(any(e.startswith("bad edge ['a', 'zz', 's']") for e in page.validate(L)))

    def test_old_file_renders_without_dispute_styles(self):
        css, _ = page.assets(LINEAGE, page.Links({}, {}))
        self.assertNotIn("--dispute", css)
        self.assertNotIn("≠", page.svg(LINEAGE, page.Links({}, {})))

    def test_check_counts_citation_links_and_flags_missing_ones(self):
        L = lineage_copy()
        L["nodes"].append({"id": "f2", "lane": 1, "year": 2025, "title": "F2", "sub": "F2 2025", "openalex": "F2"})
        L["nodes"].append({"id": "z", "lane": 1, "year": 2026, "title": "Z", "sub": "Z 2026", "openalex": "Z9"})
        L["edges"] = [["a", "b", "s"],                     # B cites A: linked
                      {"from": "b", "to": "f", "type": "s", "basis": "method", "evidence": "F1 §2"},  # F1 cites B
                      {"from": "b", "to": "f2", "type": "s", "basis": "method", "evidence": "F2 §3"},  # F2 does not
                      ["s", "z", "s"],                     # Z9 not in the corpus: unverifiable
                      ["b", "s", "d"]]                     # d edges are not checked
        self.write(L)
        rc, out = self.check()
        self.assertEqual(rc, 0)
        self.assertIn("s edges: 2 with citation link, 1 without, 1 unverifiable (no OpenAlex/refs)", out)
        self.assertIn("edge_no_citation_link: b -> f2: F2 2025 (F2) does not cite B 2015 (B)", out)
        self.assertIn("recorded basis: method", out)
        self.assertIn("edge_no_basis: 2 s edge(s) have no basis/evidence", out)
        self.assertIn("a->b, s->z", out)

    def test_refs_meta_supplies_reference_lists_outside_the_corpus(self):
        meta = json.loads((self.data / "refs_meta.json").read_text(encoding="utf-8"))
        meta["Y"] = {"id": "https://openalex.org/Y", "title": "Y", "publication_year": 2026,
                     "referenced_works": ["https://openalex.org/S"]}
        (self.data / "refs_meta.json").write_text(json.dumps(meta), encoding="utf-8")
        L = lineage_copy()
        L["nodes"].append({"id": "y", "lane": 1, "year": 2026, "title": "Y", "sub": "Y 2026", "openalex": "Y"})
        L["edges"] = [{"from": "s", "to": "y", "type": "s", "basis": "cites", "evidence": "Y p.1"}]
        _, summary, detail = audit.edge_citations(L, self.root)
        self.assertEqual(detail["linked"], [("s", "y")])
        self.assertEqual(audit.edge_basis(L), [])

    def test_no_corpus_flag_skips_corpus_checks(self):
        self.write(lineage_copy())
        _, out = self.check("--no-corpus")
        self.assertNotIn("s edges:", out)
        _, out = self.check()
        self.assertIn("s edges: 1 with citation link, 0 without, 0 unverifiable", out)


CONTESTED = [{"claim": "propagon share", "side_a": {"nodes": ["s"], "says": "large"},
              "side_b": {"nodes": ["f"], "says": "small"}, "metric_note": "MFP cutoff differs", "status": "open"}]


class DisputeTests(TopicFolder):
    def disputed(self, x_edge=True):
        L = lineage_copy()
        L["contested"] = json.loads(json.dumps(CONTESTED))
        if x_edge:
            L["edges"].append(["f", "s", "x"])
        return L

    def test_x_edge_is_drawn_with_marker_and_legend(self):
        L = self.disputed()
        self.assertEqual(page.validate(L), [])
        self.assertFalse(any("backward in time" in w for w in page.warnings(L)))  # a dispute has no direction
        svg = page.svg(L, page.Links({}, {}))
        self.assertIn('class="e dis" data-s="f" data-t="s"', svg)
        self.assertIn('<g class="e xm" data-s="f" data-t="s"><circle', svg)
        self.assertIn("≠", svg)
        self.assertIn(page.EDGE_KO["x"], svg)               # legend inside the SVG (lineage mode, no designs)
        self.assertNotIn("연구 설계", svg)
        self.assertIn(f'stroke-dasharray="{page.X_DASH}"', svg)  # pattern, not colour alone
        css, _ = page.assets(L, page.Links({}, {}))
        self.assertIn("--dispute", css)

    def test_x_edge_cannot_touch_an_event(self):
        from test_lineage import TOPIC
        L = json.loads(json.dumps(TOPIC))
        L["edges"].append(["h", "ev", "x"])
        self.assertTrue(any("only through 'e' edges" in e for e in page.validate(L)))

    def test_contested_validation(self):
        L = self.disputed()
        L["contested"][0]["side_b"]["nodes"] = ["nope"]
        L["contested"][0]["status"] = "maybe"
        errs = page.validate(L)
        self.assertTrue(any("side_b names unknown node(s) ['nope']" in e for e in errs))
        self.assertTrue(any("status must be one of" in e for e in errs))
        L = self.disputed()
        del L["contested"][0]["side_a"]
        self.assertTrue(any("'side_a' needs 'nodes'" in e for e in page.validate(L)))

    def test_check_flags_weak_sides_and_missing_x_edge(self):
        self.write(self.disputed(x_edge=False))
        _, out = self.check()
        # node s has a fulltext row; node f has no row at all
        self.assertIn("contested_side_not_fulltext: 'propagon share' side_b rests on f (no row in the evidence table)", out)
        self.assertNotIn("side_a rests on", out)
        self.assertIn("contested_without_x_edge: 'propagon share'", out)
        L = self.disputed()
        L["rows"].append({"year": "2025", "work": "F1", "what": "w", "change": "c", "lane": 1,
                          "level": "abstract", "openalex": "F1"})
        self.write(L)
        _, out = self.check()
        self.assertIn("side_b rests on f (초록만 확인)", out)
        self.assertNotIn("contested_without_x_edge", out)
        L["rows"][-1]["level"] = "fulltext"
        self.write(L)
        _, out = self.check()
        self.assertNotIn("contested_", out)

    def test_report_and_page_show_the_contested_table(self):
        L = self.disputed()
        self.write(L)
        with quiet():
            self.assertEqual(report.main([str(self.root), "--chapter", "3", "--no-figure"]), 0)
            page.main([str(self.root)])
        md = (self.root / "lineage_section.md").read_text(encoding="utf-8")
        self.assertIn("### 3.5 쟁점", md)
        self.assertIn("| 쟁점 | A | B | 측정 차이 | 상태 | 근거 수준 |", md)
        self.assertIn("| propagon share | large (S 2024) | small (F1 2025) | MFP cutoff differs | 미해결 | "
                      "A: 본문 확인 / B: F1 2025: 표 없음 |", md)
        self.assertIn("### 3.6 데이터로 본 근거", md)
        html = (self.root / "test_lineage.html").read_text(encoding="utf-8")
        self.assertIn("<h2>쟁점</h2>", html)
        self.assertIn(page.EDGE_KO["x"], html)

    def test_report_without_new_fields_keeps_its_numbering(self):
        self.write(lineage_copy())
        with quiet():
            report.main([str(self.root), "--chapter", "3", "--no-figure"])
        md = (self.root / "lineage_section.md").read_text(encoding="utf-8")
        heads = [l for l in md.splitlines() if l.startswith("### ")]
        self.assertEqual(heads, ["### 3.1 갈라진 지점", "### 3.2 단계별 흐름", "### 3.3 주요 흐름", "### 3.4 한 줄 요약",
                                 "### 3.5 데이터로 본 근거", "### 3.6 계보 표와 근거 상태", "### 3.7 이 계보의 한계"])


def author_work(wid, year, role, title, authors, abstract=None):
    w = work(wid, year, [], title, role=role, abstract=abstract)
    w["authorships"] = [{"author": {"id": f"https://openalex.org/{a}", "display_name": a}} for a in authors]
    return w


class AdoptionTests(unittest.TestCase):
    def corpus(self, d: Path):
        c = {
            "S": author_work("S", 2023, ["seed"], "Silica seed with neural network", ["A1", "A2"]),
            "S2": author_work("S2", 2024, ["seed", "forward"], "Second silica seed neural network", ["A3"]),
            "F1": author_work("F1", 2024, ["forward"], "Silica glass conductivity", ["B1"], "using a neural network potential"),
            "F2": author_work("F2", 2025, ["forward"], "SiO2 thermal transport", ["A1", "B2"], "machine learning potential"),
            "F3": author_work("F3", 2025, ["forward"], "SiO2 Green-Kubo", ["B3"]),
            "F4": author_work("F4", 2025, ["forward", "keyword:silica"], "Silica phonons", ["B4"]),
            "F5": author_work("F5", 2025, ["forward"], "Polymer conductivity neural network", ["B5"]),
            "K1": author_work("K1", 2025, ["keyword:silica"], "Silica MLIP study", ["B6"], "neural network"),
            "R1": author_work("R1", 2010, ["backward"], "Old silica neural network", ["B7"]),
        }
        (d / "corpus.json").write_text(json.dumps(c), encoding="utf-8")

    def test_forward_only_denominator_self_citation_and_log(self):
        with tempfile.TemporaryDirectory() as directory:
            d = Path(directory)
            self.corpus(d)
            args = [str(d), "--scope", "silica|SiO2", "--method", "neural network|machine learn"]
            rc, out = run_out(adoption.main, args)
            self.assertEqual(rc, 0)
            log = json.loads((d / "adoption.json").read_text(encoding="utf-8"))
            e = log[0]
            self.assertEqual(e["id"], "adoption#1")
            self.assertEqual(e["roles"], ["forward"])
            # forward + scope: F1, F2, F3, F4 (S2 is a founder; K1 widened-only; F5 off scope; R1 backward)
            self.assertEqual((e["denominator"], e["numerator"]), (4, 2))
            self.assertEqual(e["excluded_widened"], 1)
            self.assertEqual(e["per_year"], {"2024": {"scope": 1, "method": 1, "share": 1.0},
                                             "2025": {"scope": 3, "method": 1, "share": 0.333}})
            # founders default to the corpus seeds: F2 shares author A1 with S
            self.assertEqual(e["founders"], ["S", "S2"])
            self.assertEqual((e["self_citing"], e["self_citing_ids"]), (1, ["F2"]))
            self.assertIn("adoption#1", out)
            self.assertIn("2025: 1/3 (33%)", out)
            self.assertIn("self-citation: 1/2 (50%)", out)
            # second run with --since and explicit founders: appended as adoption#2
            rc, out = run_out(adoption.main, args + ["--since", "2025", "--founders", "S2"])
            log = json.loads((d / "adoption.json").read_text(encoding="utf-8"))
            self.assertEqual([x["id"] for x in log], ["adoption#1", "adoption#2"])
            self.assertEqual((log[1]["denominator"], log[1]["numerator"], log[1]["self_citing"]), (3, 1, 0))
            self.assertIn("cite as: adoption#2 = 1/3", out)

    def test_founders_from_lineage_and_cli_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            d = Path(directory)
            self.corpus(d)
            lj = d / "lineage.json"
            lj.write_text(json.dumps({"meta": {"seed_ids": ["S2"]}}), encoding="utf-8")
            with quiet():
                rc = lineage_main(["adoption", str(d), "--scope", "silica|SiO2", "--method", "neural",
                                   "--lineage", str(lj)])
            self.assertEqual(rc, 0)
            e = json.loads((d / "adoption.json").read_text(encoding="utf-8"))[0]
            self.assertEqual((e["founders"], e["founders_from"]), (["S2"], "seed_ids of lineage.json"))
            self.assertEqual(e["denominator"], 4)   # S2 left out as a founder; S is a seed, not forward

    def test_mentions_logs_regex_and_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            d = Path(directory)
            self.corpus(d)
            with quiet():
                mentions.main([str(d), "neural network"])
                mentions.main([str(d), "silica"])
            log = json.loads((d / "mentions.json").read_text(encoding="utf-8"))
            self.assertEqual([e["id"] for e in log], ["mentions#1", "mentions#2"])
            self.assertEqual(log[0]["regex"], "neural network")
            # field = forward + keyword: S2 F1-F5 K1 = 7; neural network: S2 F1 F5 K1
            self.assertEqual((log[0]["matches"], log[0]["denominator"], log[0]["widened_only"]), (4, 7, 1))
            self.assertEqual(log[0]["per_year"]["2025"], {"matches": 2, "field": 5})


class GoldAndSaturationTests(TopicFolder):
    def fake_doi_get(self, params, **kw):
        self.assertIn("doi:", params["filter"])
        return {"results": [{"id": "https://openalex.org/W77", "doi": "https://doi.org/10.1103/PhysRevB.1.2"}]}

    def test_freeze_resolves_dois_and_keeps_unresolved(self):
        src = self.root / "gold.txt"
        src.write_text("# papers cited by both reviews\nW11\nhttps://openalex.org/W12  # Review A\n"
                       "10.1103/physrevb.1.2\nhttps://doi.org/10.9999/missing\n\nW11\n", encoding="utf-8")
        with mock.patch.object(openalex, "get", side_effect=self.fake_doi_get):
            rc, out = run_out(lineage_main, ["gold", "freeze", str(self.data), "--from-file", str(src),
                                             "--note", "cited by two reviews"])
        self.assertEqual(rc, 0)
        g = json.loads((self.data / "gold.json").read_text(encoding="utf-8"))
        self.assertEqual(g["ids"], ["W11", "W12", "W77"])
        self.assertEqual(g["unresolved"], ["https://doi.org/10.9999/missing"])
        self.assertEqual((g["source"], g["note"]), ("gold.txt", "cited by two reviews"))
        self.assertIn("gold: independent (3)", out)
        self.assertIn("unresolved (not in OpenAlex by DOI): https://doi.org/10.9999/missing", out)

    def test_plain_gold_file_rejects_dois(self):
        p = self.root / "ids.txt"
        p.write_text("W1\n10.1/x\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            gold.load_ids(p)
        p.write_text("W1\nhttps://openalex.org/w2\n", encoding="utf-8")
        self.assertEqual(gold.load_ids(p), ["W1", "W2"])

    def run_query(self, *extra):
        hits = {"meta": {"count": 3}, "results": [work("N1", 2025, ["A"], "New in-field"),
                                                  work("F1", 2025, ["A"], "Known")]}
        with mock.patch.object(query_test, "search", return_value=hits), \
                mock.patch.object(query_test, "get", return_value={"results": [{"id": "https://openalex.org/S"}]}):
            return run_out(query_test.main, [str(self.data), "a AND b", "--list", "0", *extra])

    def test_query_test_uses_frozen_gold_by_default_and_flags_unsaturated(self):
        (self.data / "gold.json").write_text(json.dumps({"ids": ["S"], "source": "g.txt"}), encoding="utf-8")
        _, out = self.run_query()
        self.assertIn("gold: independent (1)", out)
        self.assertIn("UNSATURATED: no query reached novelty < 10% (last query novelty 50%)", out)
        log = json.loads((self.data / "queries.json").read_text(encoding="utf-8"))
        self.assertEqual((log[0]["gold_source"], log[0]["gold"]), ("independent", 1))
        self.write(lineage_copy())
        _, out = self.run_query("--gold-from-lineage", str(self.root / "lineage.json"))
        self.assertIn("gold: from curated lineage (circular)", out)
        _, out = self.run_query("--gold-file", str(self.data / "gold.json"))
        self.assertIn("gold: independent (1)", out)

    def test_no_unsaturated_line_once_a_query_saturates(self):
        (self.data / "queries.json").write_text(json.dumps([{"query": "q", "novelty": 0.05, "saturated": True}]),
                                                encoding="utf-8")
        _, out = self.run_query()
        self.assertNotIn("UNSATURATED", out)

    def unsaturated_log(self):
        log = [{"date": "2026-11-20", "label": f"q{i}", "query": f"q{i}", "hits": 10, "top": 10, "on_topic": 10,
                "precision": 1.0, "gold": 2, "gold_source": "independent", "gold_found": 1, "gold_found_ids": ["S"],
                "new_on_topic": 4, "novelty": nov, "saturated": False} for i, nov in enumerate((0.4, 0.59))]
        (self.data / "queries.json").write_text(json.dumps(log), encoding="utf-8")
        (self.data / "gold.json").write_text(json.dumps({"ids": ["S", "A"], "source": "g.txt",
                                                         "note": "two reviews"}), encoding="utf-8")

    def test_check_report_and_page_state_unsaturated_search(self):
        self.unsaturated_log()
        self.write(lineage_copy())
        _, out = self.check()
        self.assertIn("warning: unsaturated_search: UNSATURATED: no query reached novelty < 10% "
                      "(last query novelty 59%) across 2 logged queries", out)
        with quiet():
            report.main([str(self.root), "--chapter", "3", "--no-figure"])
            page.main([str(self.root)])
        md = (self.root / "lineage_section.md").read_text(encoding="utf-8")
        self.assertIn("### 3.6 검색 방법과 범위", md)
        self.assertIn("검색은 포화에 이르지 않았다 (마지막 질의 신규 비율 59%", md)
        self.assertIn("독립적으로 고정한 목록입니다 (2편, two reviews)", md)
        html = (self.root / "test_lineage.html").read_text(encoding="utf-8")
        self.assertIn("검색은 포화에 이르지 않았다", html)
        self.assertIn("독립적으로 고정한 목록(gold.json, 2편, two reviews)", html)


class SearchLogTests(TopicFolder):
    def test_log_search_appends_and_report_lists_it(self):
        self.write(lineage_copy())
        args = ["log-search", str(self.root), "--engine", "arXiv", "--query", "silica kappa MACE",
                "--date", "2026-11-20", "--hits", "14", "--kept", "arXiv:2501.1, W9", "--note", "nothing on a-SiO2"]
        rc, out = run_out(lineage_main, args)
        self.assertEqual(rc, 0)
        self.assertIn("search#1: arXiv", out)
        with quiet():
            lineage_main(args[:-4])  # no --kept, no --note
        log = json.loads((self.data / "searches.json").read_text(encoding="utf-8"))
        self.assertEqual([e["id"] for e in log], ["search#1", "search#2"])
        self.assertEqual(log[0]["kept"], ["arXiv:2501.1", "W9"])
        self.assertEqual((log[0]["hits"], log[0]["note"]), (14, "nothing on a-SiO2"))
        with quiet():
            report.main([str(self.root), "--chapter", "3", "--no-figure"])
            page.main([str(self.root)])
        md = (self.root / "lineage_section.md").read_text(encoding="utf-8")
        self.assertIn("### 3.6 검색 방법과 범위", md)
        self.assertIn("| 날짜 | 검색원 | 검색식 | 결과 | 남긴 것 |", md)
        self.assertIn("| 2026-11-20 | arXiv | silica kappa MACE (nothing on a-SiO2) | 14 | arXiv:2501.1, W9 |", md)
        self.assertIn("| 14 | 없음 |", md)
        self.assertIn("OpenAlex 밖 검색 기록", (self.root / "test_lineage.html").read_text(encoding="utf-8"))

    def test_bad_date_is_rejected(self):
        self.assertEqual(lineage_main(["log-search", str(self.root), "--engine", "web", "--query", "q",
                                       "--date", "20 Nov", "--hits", "1"]), 1)
        self.assertFalse((self.data / "searches.json").exists())

    def test_not_found_claim_without_search_log_warns(self):
        L = lineage_copy()
        L["limits"].append("a-SiO2 κ에 범용 MLIP를 쓴 논문은 찾지 못함")
        self.write(L)
        _, out = self.check()
        self.assertIn("not_found_without_search_log: 1 statement(s)", out)
        with quiet():
            lineage_main(["log-search", str(self.root), "--engine", "web", "--query", "q", "--date", "2026-11-20",
                          "--hits", "0"])
        _, out = self.check()
        self.assertNotIn("not_found_without_search_log", out)


class OpenAlexFieldTests(unittest.TestCase):
    def test_language_is_requested_and_dois_normalise(self):
        self.assertIn("language", openalex.FIELDS.split(","))
        self.assertEqual(openalex.norm_doi("https://doi.org/10.1103/PhysRevB.1"), "10.1103/physrevb.1")
        self.assertEqual(openalex.norm_doi("doi:10.1/X"), "10.1/x")


if __name__ == "__main__":
    unittest.main()
