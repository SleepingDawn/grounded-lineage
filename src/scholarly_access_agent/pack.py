"""Print a reader pack byte-for-byte so sub-agent briefs share a cached prompt prefix.

  scholarly-access-agent pack reader           # the pack, then a sha256 marker line
  scholarly-access-agent pack reader --check   # hash, bytes and approximate tokens only

The pack is the skill's own file (references/reader-pack.md), so it ships with the skill
and needs no package data. Nothing is normalised or stamped: every call prints the same bytes.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

SKILL = "snu-library-scholarly-access"
PACKS = {"reader": "reader-pack.md"}


def candidates(name: str) -> list[Path]:
    """Repository/installed-data skill first, then the Claude Code copy, then the Codex copy."""
    from scholarly_access_agent.installer import SKILLS_DIR

    relative = Path(SKILL) / "references" / PACKS[name]
    home = Path.home()
    return [SKILLS_DIR / relative, home / ".claude" / "skills" / relative, home / ".codex" / "skills" / relative]


def locate(name: str, search: list[Path] | None = None) -> Path:
    for path in search if search is not None else candidates(name):
        if path.is_file():
            return path
    raise FileNotFoundError(f"{PACKS[name]} not found; run `scholarly-access-agent setup` or check skills/{SKILL}/references.")


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()[:12]


def marker(content: bytes) -> bytes:
    return f"<!-- reader-pack sha256:{digest(content)} -->\n".encode("ascii")


def render(content: bytes) -> bytes:
    """The pack unchanged, then the marker on its own line."""
    return content + (b"" if not content or content.endswith(b"\n") else b"\n") + marker(content)


def check_line(content: bytes) -> str:
    chars = len(content.decode("utf-8", errors="replace"))
    return f"sha256:{digest(content)} bytes={len(content)} chars={chars} approx_tokens={round(chars / 3.5)}"


def main(argv=None, *, search: list[Path] | None = None, out=None) -> int:
    ap = argparse.ArgumentParser(prog="scholarly-access-agent pack", description=__doc__.split("\n\n")[0])
    ap.add_argument("name", choices=sorted(PACKS), help="which pack to print")
    ap.add_argument("--check", action="store_true", help="print only the hash, byte count and approximate tokens")
    args = ap.parse_args(argv)
    try:
        content = locate(args.name, search).read_bytes()
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    stream = out if out is not None else sys.stdout.buffer
    data = (check_line(content) + "\n").encode("ascii") if args.check else render(content)
    if out is None:
        sys.stdout.flush()
    stream.write(data)  # bytes, so Windows newline translation cannot alter the pack
    stream.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
