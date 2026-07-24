from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from scholarly_access_agent.cli import build_parser, read_batch_jobs
from scholarly_access_agent.runtime.batch import (
    BatchJob,
    _atomic_save,
    _valid_pdf_file,
    schedule_jobs,
)
from scholarly_access_agent.runtime.storage import load_saved_cookies


class BatchJobTests(unittest.TestCase):
    def test_job_validation_accepts_basename_pdf(self):
        job = BatchJob.from_dict(
            {"id": "slot-1", "url": "https://example.org/a", "filename": "a.pdf"}
        )
        self.assertEqual(job.filename, "a.pdf")

    def test_job_validation_rejects_path_traversal(self):
        with self.assertRaises(ValueError):
            BatchJob.from_dict(
                {
                    "id": "slot-1",
                    "url": "https://example.org/a",
                    "filename": "../a.pdf",
                }
            )

    def test_jsonl_reader(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jobs.jsonl"
            path.write_text(
                json.dumps(
                    {
                        "id": "slot-1",
                        "url": "https://example.org/a",
                        "filename": "a.pdf",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            jobs = read_batch_jobs(str(path))
            self.assertEqual([job.id for job in jobs], ["slot-1"])

    def test_cli_keeps_single_and_adds_batch_commands(self):
        parser = build_parser()
        single = parser.parse_args(["download-pdf", "https://example.org/a"])
        batch = parser.parse_args(["download-many", "--input", "jobs.jsonl"])
        self.assertEqual(single.command, "download-pdf")
        self.assertEqual(batch.command, "download-many")
        self.assertEqual(batch.concurrency, 1)
        self.assertEqual(batch.per_host_concurrency, 1)


class FileTests(unittest.TestCase):
    def test_atomic_save_and_existing_pdf_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "paper.pdf"
            body = b"%PDF-" + (b"x" * 20_000)
            _atomic_save(path, body)
            self.assertTrue(_valid_pdf_file(path))
            self.assertEqual(path.read_bytes(), body)

    def test_saved_session_cookies_are_loaded_from_profile_companion(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory)
            expected = [{
                "name": "session",
                "value": "opaque",
                "domain": ".example.org",
                "path": "/",
            }]
            (profile / "storage-state.json").write_text(
                json.dumps({"cookies": expected, "origins": []}),
                encoding="utf-8",
            )
            self.assertEqual(load_saved_cookies(profile), expected)


class SchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def test_global_and_host_concurrency_are_bounded(self):
        jobs = [
            BatchJob(f"job-{index}", f"https://example.org/{index}", f"{index}.pdf")
            for index in range(6)
        ]
        active = 0
        maximum = 0

        async def worker(job):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0.01)
            active -= 1
            return {
                "event": "result",
                "id": job.id,
                "ok": True,
                "status": "downloaded",
            }

        batch = await schedule_jobs(
            jobs, worker, concurrency=4, per_host_concurrency=2
        )
        self.assertEqual(maximum, 2)
        self.assertEqual(batch.summary["succeeded"], 6)

    async def test_login_required_freezes_queued_jobs(self):
        jobs = [
            BatchJob(f"job-{index}", f"https://example.org/{index}", f"{index}.pdf")
            for index in range(3)
        ]

        async def worker(job):
            if job.id == "job-0":
                return {
                    "event": "result",
                    "id": job.id,
                    "ok": False,
                    "status": "login_required",
                }
            return {
                "event": "result",
                "id": job.id,
                "ok": True,
                "status": "downloaded",
            }

        batch = await schedule_jobs(
            jobs, worker, concurrency=1, per_host_concurrency=1
        )
        self.assertTrue(batch.summary["login_required"])
        self.assertEqual(batch.summary["not_started"], 2)


if __name__ == "__main__":
    unittest.main()
