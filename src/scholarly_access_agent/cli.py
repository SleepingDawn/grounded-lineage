from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Sequence

from scholarly_access_agent.providers.snu.proxy import SnuProxyProvider
from scholarly_access_agent.runtime.browser import (
    DEFAULT_PROFILE_DIR,
    DEFAULT_TIMEOUT_MS,
    BrowserRuntimeUnavailable,
    open_proxied_url,
)
from scholarly_access_agent.runtime.pdf import (
    DEFAULT_DOWNLOAD_DIR,
    DEFAULT_TIMEOUT_SECONDS,
    discover_pdfs,
    download_pdf,
)

def str2bool(v: str | bool) -> bool:
    if isinstance(v, bool):
        return v
    if v.lower() in ("yes", "true", "t", "y", "1"):
        return True
    if v.lower() in ("no", "false", "f", "n", "0"):
        return False
    raise argparse.ArgumentTypeError("Boolean value expected.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scholarly-access-agent",
        description="Local CLI for scholarly access provider workflows.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    doctor = subcommands.add_parser("doctor", help="Check runtime and session presence without exposing secrets.")
    doctor.add_argument(
        "--probe",
        metavar="ARTICLE_URL",
        help="Also fetch one subscription article's PDF headlessly into a temporary folder (deleted at once) "
             "to check the SNU session really serves PDFs.",
    )

    proxy_url = subcommands.add_parser("proxy-url", help="Build a provider proxy URL.")
    proxy_url.add_argument("url", help="Article or publisher URL to proxy.")

    check_url = subcommands.add_parser("check-url", help="Check provider domain support.")
    check_url.add_argument("url", help="Article or publisher URL to check.")
    open_url = subcommands.add_parser(
        "open-url",
        help="Open a provider-proxied URL in a persistent browser profile.",
    )
    open_url.add_argument("url", help="Article or publisher URL to open.")
    open_url.add_argument(
        "--profile-dir",
        type=Path,
        default=DEFAULT_PROFILE_DIR,
        help="Persistent browser profile directory.",
    )
    open_url.add_argument(
        "--browser-channel",
        help="Optional installed browser channel, such as chrome or msedge.",
    )
    open_url.add_argument(
        "--headless",
        type=str2bool,
        nargs="?",
        const=True,
        default=False,
        help="Run the browser headlessly. User-assisted login usually needs a window.",
    )
    open_url.add_argument(
        "--timeout-ms",
        type=int,
        default=DEFAULT_TIMEOUT_MS,
        help="Navigation timeout in milliseconds.",
    )
    open_url.add_argument(
        "--wait-for-login",
        action="store_true",
        help="Keep the browser open and wait for the user to finish SNU login.",
    )

    download_pdf_command = subcommands.add_parser(
        "download-pdf",
        help="Discover and download an accessible PDF from a URL.",
    )
    download_pdf_command.add_argument("url", help="Article page or direct PDF URL.")
    download_pdf_command.add_argument(
        "--pdf-url",
        help="Optional direct PDF URL to download, skipping page discovery.",
    )
    download_pdf_command.add_argument(
        "--download-dir",
        type=Path,
        default=DEFAULT_DOWNLOAD_DIR,
        help="Directory for downloaded PDFs.",
    )
    download_pdf_command.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Network timeout in seconds.",
    )
    download_pdf_command.add_argument(
        "--profile-dir",
        type=Path,
        default=DEFAULT_PROFILE_DIR,
        help="Persistent browser profile directory for sharing login state.",
    )
    download_pdf_command.add_argument(
        "--browser-channel",
        help="Optional browser channel (e.g. chrome, msedge) to use system browser.",
    )
    download_pdf_command.add_argument(
        "--headless",
        type=str2bool,
        nargs="?",
        const=True,
        default=True,
        help="Run browser headlessly (default: true).",
    )

    download_many_command = subcommands.add_parser(
        "download-many",
        help="Download JSONL-described PDFs through one persistent browser context.",
    )
    download_many_command.add_argument(
        "--input",
        required=True,
        help="JSONL input path, or '-' to read from stdin.",
    )
    download_many_command.add_argument(
        "--download-dir",
        type=Path,
        default=DEFAULT_DOWNLOAD_DIR,
        help="Directory for downloaded PDFs.",
    )
    download_many_command.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Per-navigation/network timeout in seconds.",
    )
    download_many_command.add_argument(
        "--profile-dir",
        type=Path,
        default=DEFAULT_PROFILE_DIR,
        help="Persistent browser profile directory for sharing login state.",
    )
    download_many_command.add_argument(
        "--browser-channel",
        help="Optional browser channel (e.g. chrome, msedge).",
    )
    download_many_command.add_argument(
        "--headless",
        type=str2bool,
        nargs="?",
        const=True,
        default=True,
        help="Run browser headlessly (default: true).",
    )
    download_many_command.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Maximum number of concurrent downloads (default: 1).",
    )
    download_many_command.add_argument(
        "--per-host-concurrency",
        type=int,
        default=1,
        help="Maximum concurrent downloads for one source host (default: 1).",
    )

    discover_pdfs_command = subcommands.add_parser(
        "discover-pdfs",
        help="Discover all PDF candidate links on an article page.",
    )
    discover_pdfs_command.add_argument("url", help="Article page URL to scan for PDF links.")
    discover_pdfs_command.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Network timeout in seconds.",
    )
    discover_pdfs_command.add_argument(
        "--profile-dir",
        type=Path,
        default=DEFAULT_PROFILE_DIR,
        help="Persistent browser profile directory for sharing login state.",
    )
    discover_pdfs_command.add_argument(
        "--browser-channel",
        help="Optional browser channel (e.g. chrome, msedge) to use system browser.",
    )
    discover_pdfs_command.add_argument(
        "--headless",
        type=str2bool,
        nargs="?",
        const=True,
        default=True,
        help="Run browser headlessly (default: true).",
    )

    read_pdf_command = subcommands.add_parser(
        "read-pdf", help="Read local PDF pages or locate terms with page-grounded excerpts.",
    )
    read_pdf_command.add_argument("path", help="Local PDF path from download-pdf or a user-provided PDF.")
    read_pdf_command.add_argument("--terms", nargs="+", help="Up to 12 English/scientific terms or phrases to locate.")
    read_pdf_command.add_argument("--pages", default="1-5", help="Page or range; ignored when terms are provided.")
    read_pdf_command.add_argument("--max-chars", type=int, default=None,
                                  help="Text budget (default: 4000 with --terms, 16000 for --pages).")

    read_url_command = subcommands.add_parser(
        "read-url", help="Text-first reading of open-access HTML full text (arXiv, PMC) with section names.",
    )
    read_url_command.add_argument("url", help="arXiv abs/pdf/html URL or another open-repository article URL.")
    read_url_command.add_argument("--terms", nargs="+", help="Up to 12 terms to locate (excerpts with section names).")
    read_url_command.add_argument("--sections", nargs="+", help="Section names to read in full; omit with --terms.")
    read_url_command.add_argument("--max-chars", type=int, default=None,
                                  help="Text budget (default: 4000 with --terms, 12000 for --sections).")

    render_report_command = subcommands.add_parser(
        "render-report",
        help="Render a finished Markdown research report to a standalone HTML page (or PDF) (local files only).",
    )
    render_report_command.add_argument("path", help="Report Markdown file (.md).")
    render_report_command.add_argument(
        "-o", "--output", type=Path,
        help="Output .html or .pdf path (default: next to the Markdown file, same name).",
    )
    render_report_command.add_argument(
        "--engine", choices=("auto", "quarto", "reportlab"), default="auto",
        help="auto: Quarto when installed, else the built-in reportlab PDF.",
    )
    render_report_command.add_argument(
        "--format", dest="formats", action="append", choices=("html", "pdf"),
        help="Output format, repeatable (default: html; pdf when -o ends in .pdf).",
    )

    subcommands.add_parser(
        "mcp-server",
        help="Start the MCP tool process over standard I/O.",
    )
    subcommands.add_parser(
        "setup",
        help="Install the canonical skill for the current Codex and Claude Code user.",
    )
    add_domain = subcommands.add_parser(
        "add-domain",
        help="Add a domain to the built-in SNU proxy domain list.",
    )
    add_domain.add_argument("domain", help="Domain to add (e.g. publisher.com).")

    # Dispatched before argparse in main(); registered here so it shows in --help.
    subcommands.add_parser(
        "lineage",
        help="Research lineage tools (seed, collect, analyze, query-test, page, report-section, ...).",
        add_help=False,
    )
    subcommands.add_parser(
        "refs",
        help="Check evidence records' bibliographic metadata against Crossref (refs check).",
        add_help=False,
    )
    subcommands.add_parser(
        "cost",
        help="Research-run token estimates, spend ledger and calibration (estimate, record, report).",
        add_help=False,
    )
    subcommands.add_parser(
        "evidence",
        help="Lint evidence/novelty records, derive read-depth labels, re-check results on the PDF page "
             "(lint, labels, verify).",
        add_help=False,
    )
    subcommands.add_parser(
        "report",
        help="Trace a report's citation keys and numbers back to evidence records (trace).",
        add_help=False,
    )
    subcommands.add_parser(
        "pack",
        help="Print the reader pack byte-for-byte (shared cached prefix for sub-agent briefs); "
             "--check prints its hash and size.",
        add_help=False,
    )
    subcommands.add_parser(
        "viz",
        help="Vega-Lite charts from a topic folder as standalone HTML + .vl.json "
             "(effects, matrix, novelty, adoption, timeline).",
        add_help=False,
    )
    subcommands.add_parser(
        "resolve",
        help="DOI -> Crossref record, Unpaywall open copies and a ranked list of reading routes.",
        add_help=False,
    )

    return parser


def provider_from_args(args: argparse.Namespace) -> SnuProxyProvider:
    return SnuProxyProvider()


def write_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def write_json_line(payload: dict[str, object]) -> None:
    print(json.dumps(payload, sort_keys=True), flush=True)


def read_batch_jobs(input_path: str):
    from scholarly_access_agent.runtime.batch import BatchJob

    if input_path == "-":
        lines = sys.stdin
    else:
        lines = Path(input_path).open("r", encoding="utf-8")
    close_after = input_path != "-"
    jobs = []
    try:
        for line_number, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON on input line {line_number}: {exc.msg}"
                ) from exc
            if not isinstance(payload, dict):
                raise ValueError(
                    f"Input line {line_number} must contain one JSON object."
                )
            jobs.append(BatchJob.from_dict(payload))
    finally:
        if close_after:
            lines.close()
    if not jobs:
        raise ValueError("Batch input contains no jobs.")
    return jobs


def run(args: argparse.Namespace) -> int:
    provider = provider_from_args(args)

    if args.command == "doctor":
        from scholarly_access_agent.runtime.diagnostics import diagnose
        result = diagnose(probe_url=args.probe)
        write_json(result)
        return 0 if result["ok"] else 1

    if args.command == "read-pdf":
        from scholarly_access_agent.runtime.reader import read_pdf
        result = read_pdf(args.path, terms=args.terms, pages=args.pages, max_chars=args.max_chars)
        write_json(result)
        return 0 if result["ok"] else 1

    if args.command == "read-url":
        from scholarly_access_agent.runtime.public import read_url
        max_chars = args.max_chars or (4000 if args.terms else 12000)
        result = read_url(args.url, terms=args.terms, sections=args.sections, max_chars=max_chars)
        write_json(result)
        return 0 if result["ok"] else 1

    if args.command == "render-report":
        from scholarly_access_agent.runtime.report import render_report
        result = render_report(args.path, args.output, engine=args.engine, formats=args.formats)
        write_json(result)
        return 0 if result["ok"] else 1

    if args.command == "proxy-url":
        write_json(
            {
                "ok": True,
                "provider": provider.provider_id,
                "source_url": args.url,
                "proxy_url": provider.proxied_url(args.url),
            }
        )
        return 0

    if args.command == "check-url":
        supported = provider.supports_url(args.url)
        payload: dict[str, object] = {
            "ok": True,
            "provider": provider.provider_id,
            "source_url": args.url,
            "supported": supported,
        }
        if supported:
            payload["proxy_url"] = provider.proxied_url(args.url)
        write_json(payload)
        return 0

    if args.command == "open-url":
        try:
            result = open_proxied_url(
                args.url,
                provider=provider,
                profile_dir=args.profile_dir,
                browser_channel=args.browser_channel,
                headless=args.headless,
                timeout_ms=args.timeout_ms,
                wait_for_login=args.wait_for_login,
            )
        except BrowserRuntimeUnavailable as exc:
            write_json(
                {
                    "ok": False,
                    "provider": provider.provider_id,
                    "source_url": args.url,
                    "profile_dir": str(args.profile_dir.resolve()),
                    "status": "unavailable",
                    "reason": "missing_playwright",
                    "message": type(exc).__name__,
                }
            )
            return 2

        write_json(result.to_dict())
        return 0 if result.ok else 1

    if args.command == "download-pdf":
        pdf_url = getattr(args, "pdf_url", None) or None
        from scholarly_access_agent.runtime.public import download_public_pdf, is_public_url, pdf_url_for
        public_target = pdf_url_for(pdf_url or args.url)
        if public_target and is_public_url(public_target):
            public = download_public_pdf(public_target, download_dir=args.download_dir, timeout_seconds=args.timeout_seconds)
            write_json(public)
            return 0 if public["ok"] else 1
        result = download_pdf(
            args.url,
            provider=provider,
            pdf_url=pdf_url,
            download_dir=args.download_dir,
            profile_dir=args.profile_dir,
            browser_channel=args.browser_channel,
            timeout_seconds=args.timeout_seconds,
            headless=args.headless,
        )
        write_json(result.to_dict())
        return 0 if result.ok else 1

    if args.command == "download-many":
        from scholarly_access_agent.runtime.batch import download_many

        jobs = read_batch_jobs(args.input)
        batch = asyncio.run(
            download_many(
                jobs,
                provider=provider,
                download_dir=args.download_dir,
                profile_dir=args.profile_dir,
                browser_channel=args.browser_channel,
                timeout_seconds=args.timeout_seconds,
                headless=args.headless,
                concurrency=args.concurrency,
                per_host_concurrency=args.per_host_concurrency,
                on_result=write_json_line,
            )
        )
        write_json_line(batch.summary)
        if batch.summary["login_required"]:
            return 3
        return 0 if batch.summary["failed"] == 0 else 1

    if args.command == "discover-pdfs":
        from scholarly_access_agent.runtime.pdf import discover_pdfs
        result = discover_pdfs(
            args.url,
            provider=provider,
            profile_dir=args.profile_dir,
            browser_channel=args.browser_channel,
            timeout_seconds=args.timeout_seconds,
            headless=args.headless,
        )
        write_json(result.to_dict())
        return 0 if result.ok else 1

    if args.command == "mcp-server":
        from scholarly_access_agent.mcp.server import run_mcp_server
        return run_mcp_server()

    if args.command == "setup":
        from scholarly_access_agent.installer import main as install_skills
        install_skills()
        return 0

    if args.command == "add-domain":
        from scholarly_access_agent.providers.snu.domains import add_domain
        result = add_domain(args.domain)
        write_json(result)
        return 0

    raise ValueError(f"Unsupported command: {args.command}")


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["lineage"]:
        # lineage subcommands own their argparse and print human-readable output
        from scholarly_access_agent.lineage.cli import main as lineage_main

        return lineage_main(argv[1:])
    if argv[:1] == ["refs"]:
        from scholarly_access_agent.refs import main as refs_main

        return refs_main(argv[1:])
    if argv[:1] == ["cost"]:
        from scholarly_access_agent.cost import main as cost_main

        return cost_main(argv[1:])
    if argv[:1] == ["evidence"]:
        from scholarly_access_agent.evidence import main as evidence_main

        return evidence_main(argv[1:])
    if argv[:1] == ["report"]:
        from scholarly_access_agent.trace import main as trace_main

        return trace_main(argv[1:])
    if argv[:1] == ["pack"]:
        from scholarly_access_agent.pack import main as pack_main

        return pack_main(argv[1:])
    if argv[:1] == ["viz"]:
        from scholarly_access_agent.viz import main as viz_main

        return viz_main(argv[1:])
    if argv[:1] == ["resolve"]:
        from scholarly_access_agent.resolve import main as resolve_main

        return resolve_main(argv[1:])
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except Exception as exc:
        write_json({"ok": False, "error": type(exc).__name__, "message": type(exc).__name__})
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
