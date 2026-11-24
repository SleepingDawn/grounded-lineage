from __future__ import annotations

import hashlib
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from scholarly_access_agent import pack


class PackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file = Path(self.tmp.name) / "reader-pack.md"
        # CRLF, trailing spaces and non-ASCII must all come through untouched.
        self.content = "# Reader pack\r\n\nRead methods first.  \n한국어 줄\n".encode("utf-8")
        self.file.write_bytes(self.content)

    def run_pack(self, *args, search=None) -> bytes:
        out = io.BytesIO()
        code = pack.main(["reader", *args], search=search or [self.file], out=out)
        self.assertEqual(code, 0)
        return out.getvalue()

    def test_prints_bytes_unchanged_then_hash_marker(self):
        first = self.run_pack()
        expected_hash = hashlib.sha256(self.content).hexdigest()[:12]
        self.assertEqual(first, self.content + f"<!-- reader-pack sha256:{expected_hash} -->\n".encode())
        self.assertEqual(first, self.run_pack())  # identical on every call

    def test_missing_final_newline_gets_separator_only(self):
        self.file.write_bytes(b"no newline")
        output = self.run_pack()
        self.assertTrue(output.startswith(b"no newline\n<!-- reader-pack sha256:"))
        self.assertIn(hashlib.sha256(b"no newline").hexdigest()[:12].encode(), output)

    def test_check_prints_hash_and_size_only(self):
        line = self.run_pack("--check").decode()
        chars = len(self.content.decode("utf-8"))
        self.assertEqual(line, f"sha256:{hashlib.sha256(self.content).hexdigest()[:12]} "
                               f"bytes={len(self.content)} chars={chars} approx_tokens={round(chars / 3.5)}\n")

    def test_falls_back_in_order_and_reports_missing(self):
        missing = Path(self.tmp.name) / "absent.md"
        self.assertEqual(pack.locate("reader", [missing, self.file]), self.file)
        with self.assertRaises(FileNotFoundError):
            pack.locate("reader", [missing])
        self.assertEqual(pack.main(["reader"], search=[missing], out=io.BytesIO()), 1)

    def test_default_search_order_is_repo_then_claude_then_codex(self):
        paths = pack.candidates("reader")
        self.assertTrue(all(p.parts[-3:] == ("snu-library-scholarly-access", "references", "reader-pack.md")
                            for p in paths))
        self.assertEqual([p.parts[-5] for p in paths[1:]], [".claude", ".codex"])

    def test_the_record_readers_copy_passes_lint_including_a_printed_range(self):
        """Readers copy the pack's example record; a range-only result with a null value failed lint."""
        import json
        import re

        from scholarly_access_agent.evidence import lint_record
        repo_pack = pack.candidates("reader")[0]
        block = re.search(r"```json\n(.*?)\n```", repo_pack.read_text(encoding="utf-8"), re.S).group(1)
        record = json.loads(block)
        self.assertEqual([f for f in lint_record(record, "example.json") if f["level"] == "error"], [])
        ranges = [r for r in record["results"] if isinstance(r.get("value"), str) and "-" in r["value"]]
        self.assertTrue(ranges, "the example shows how to record a printed range")
        self.assertTrue(all(r.get("lo") is not None and r.get("hi") is not None for r in ranges))

    def test_cli_dispatch(self):
        from scholarly_access_agent import cli
        original = pack.candidates
        pack.candidates = lambda name: [self.file]
        try:
            buffer = io.BytesIO()

            class Stdout(io.StringIO):
                pass
            stdout = Stdout()
            stdout.buffer = buffer  # type: ignore[attr-defined]
            with redirect_stdout(stdout):
                self.assertEqual(cli.main(["pack", "reader"]), 0)
            self.assertTrue(buffer.getvalue().startswith(self.content))
        finally:
            pack.candidates = original


if __name__ == "__main__":
    unittest.main()
