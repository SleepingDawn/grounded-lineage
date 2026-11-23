import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from scholarly_access_agent import cost


def run(*argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cost.main(list(argv))
    return code, json.loads(buf.getvalue())


class CostTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = str(Path(self.tmp.name) / ".cost" / "ledger.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def test_deep_costs_more_than_default_and_roles_sum_to_total(self):
        _, d = run("--ledger", self.ledger, "estimate", "--playbook", "status")
        _, deep = run("--ledger", self.ledger, "estimate", "--playbook", "status", "--preset", "deep")
        self.assertGreater(deep["total_tokens"], d["total_tokens"])
        self.assertEqual(sum(d["by_role"].values()), d["total_tokens"])
        self.assertEqual(d["calibrated_stages"], "0/4")
        self.assertIsNone(d["plan_pct_per_mtok"])

    def test_topics_adds_topic_stages_and_skip_status_drops_review(self):
        _, full = run("--ledger", self.ledger, "estimate", "--playbook", "topics")
        _, only = run("--ledger", self.ledger, "estimate", "--playbook", "topics", "--skip-status", "--records", "20")
        self.assertIn("read", full["stages"])
        self.assertIn("novelty_read", full["stages"])
        self.assertNotIn("read", only["stages"])
        self.assertLess(only["total_tokens"], full["total_tokens"])
        self.assertEqual(full["topic"]["records"], full["counts"]["read"])

    def test_overrides_replace_preset_counts(self):
        _, out = run("--ledger", self.ledger, "estimate", "--playbook", "status", "--read", "10", "--pdf", "2")
        self.assertEqual(out["counts"]["read"], 10)
        self.assertEqual(out["counts"]["pdf"], 2)

    def test_cap_shrinks_figures_and_pdfs_before_reading(self):
        _, base = run("--ledger", self.ledger, "estimate", "--playbook", "status")
        cap = base["total_tokens"] - 20_000
        _, out = run("--ledger", self.ledger, "estimate", "--playbook", "status", "--cap-tokens", str(cap))
        self.assertFalse(out["fits"])
        reduced = out["reduced"]
        self.assertTrue(reduced["fits"])
        self.assertLessEqual(reduced["total_tokens"], cap)
        self.assertEqual(reduced["counts"]["read"], 22)  # figures/PDFs absorbed the cut
        self.assertLess(reduced["counts"]["figures"] + reduced["counts"]["pdf"], 15)

    def test_record_calibrates_later_estimates(self):
        _, base = run("--ledger", self.ledger, "estimate", "--playbook", "status")
        est = base["stages"]["read"]["tokens"]
        for i in range(3):
            run("--ledger", self.ledger, "record", "--run", f"r{i}", "--stage", "read",
                "--tokens", str(est * 2), "--estimated", str(est), "--plan-pct", "4")
        _, after = run("--ledger", self.ledger, "estimate", "--playbook", "status")
        self.assertEqual(after["stages"]["read"]["factor"], 2.0)
        self.assertEqual(after["stages"]["read"]["calibrated_runs"], 3)
        self.assertAlmostEqual(after["stages"]["read"]["tokens"], est * 2, delta=1000)
        self.assertIsNotNone(after["plan_pct_per_mtok"])
        self.assertIn("plan_pct_estimate", after)

    def test_remaining_pct_caps_at_half_once_rate_is_known(self):
        run("--ledger", self.ledger, "record", "--run", "r", "--stage", "read",
            "--tokens", "1000000", "--estimated", "1000000", "--plan-pct", "10")
        _, out = run("--ledger", self.ledger, "estimate", "--playbook", "status", "--remaining-pct", "10")
        self.assertEqual(out["cap_tokens"], 500_000)

    def test_cap_pct_without_rate_explains_instead_of_guessing(self):
        _, out = run("--ledger", self.ledger, "estimate", "--playbook", "status", "--cap-pct", "20")
        self.assertNotIn("cap_tokens", out)
        self.assertIn("cap_note", out)

    def test_report_sums_one_run_and_rejects_unknown_stage(self):
        run("--ledger", self.ledger, "record", "--run", "A", "--stage", "read", "--tokens", "100", "--estimated", "50")
        run("--ledger", self.ledger, "record", "--run", "A", "--stage", "locate", "--tokens", "30")
        run("--ledger", self.ledger, "record", "--run", "B", "--stage", "read", "--tokens", "999")
        _, rep = run("--ledger", self.ledger, "report", "--run", "A")
        self.assertEqual(rep["measured_tokens"], 130)
        self.assertEqual(rep["estimated_tokens"], 50)
        code, err = run("--ledger", self.ledger, "record", "--run", "A", "--stage", "nope", "--tokens", "1")
        self.assertEqual(code, 1)
        self.assertFalse(err["ok"])


if __name__ == "__main__":
    unittest.main()
