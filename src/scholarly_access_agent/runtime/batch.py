from __future__ import annotations

import asyncio
import os
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable
from urllib.parse import urlparse

from scholarly_access_agent.providers.snu.login import (
    PageSnapshot,
    detect_login_required,
)
from scholarly_access_agent.providers.snu.proxy import SnuProxyProvider
from scholarly_access_agent.runtime.browser import DEFAULT_PROFILE_DIR
from scholarly_access_agent.runtime.pdf import (
    DEFAULT_DOWNLOAD_DIR,
    DEFAULT_TIMEOUT_SECONDS,
    MAX_PDF_CANDIDATE_ATTEMPTS,
    PdfCandidate,
    derive_candidates_from_source,
    rank_pdf_candidates,
)
from scholarly_access_agent.runtime.storage import load_saved_cookies


@dataclass(frozen=True)
class BatchJob:
    id: str
    url: str
    filename: str

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "BatchJob":
        job_id = str(payload.get("id", "")).strip()
        url = str(payload.get("url", "")).strip()
        filename = str(payload.get("filename", "")).strip()
        if not job_id:
            raise ValueError("Each batch job requires a non-empty 'id'.")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"Job {job_id!r} has an invalid absolute URL.")
        _validate_filename(filename, job_id)
        return cls(id=job_id, url=url, filename=filename)


@dataclass(frozen=True)
class BatchRun:
    results: list[dict[str, object]]
    summary: dict[str, object]


ResultCallback = Callable[[dict[str, object]], None]
JobWorker = Callable[[BatchJob], Awaitable[dict[str, object]]]


async def schedule_jobs(
    jobs: Iterable[BatchJob],
    worker: JobWorker,
    *,
    concurrency: int,
    per_host_concurrency: int,
    on_result: ResultCallback | None = None,
) -> BatchRun:
    """Run jobs with global and per-source-host bounds.

    A login_required result freezes new work. Tasks that already entered the
    worker are allowed to finish; queued tasks are reported as not_started so a
    caller can checkpoint and safely resume the same input later.
    """
    job_list = list(jobs)
    if concurrency < 1 or per_host_concurrency < 1:
        raise ValueError("Concurrency values must be positive integers.")

    global_sem = asyncio.Semaphore(concurrency)
    host_sems: dict[str, asyncio.Semaphore] = {}
    login_pause = asyncio.Event()

    async def run_one(job: BatchJob) -> dict[str, object]:
        host = (urlparse(job.url).hostname or "").lower()
        host_sem = host_sems.setdefault(
            host, asyncio.Semaphore(per_host_concurrency)
        )
        async with global_sem:
            async with host_sem:
                if login_pause.is_set():
                    result = _base_result(
                        job,
                        ok=False,
                        status="not_started",
                        reason="login_required",
                        message="Batch paused before this job started.",
                    )
                else:
                    started = time.monotonic()
                    try:
                        result = await worker(job)
                    except Exception as exc:  # isolate one paper from the batch
                        result = _base_result(
                            job,
                            ok=False,
                            status="download_failed",
                            reason=type(exc).__name__,
                            message=str(exc),
                        )
                    result["elapsed_ms"] = round(
                        (time.monotonic() - started) * 1000
                    )
                    if result.get("status") == "login_required":
                        login_pause.set()
                if on_result:
                    on_result(result)
                return result

    results = await asyncio.gather(*(run_one(job) for job in job_list))
    succeeded = sum(bool(result.get("ok")) for result in results)
    not_started = sum(result.get("status") == "not_started" for result in results)
    login_required = any(
        result.get("status") == "login_required" for result in results
    )
    summary: dict[str, object] = {
        "event": "summary",
        "total": len(results),
        "succeeded": succeeded,
        "failed": len(results) - succeeded - not_started,
        "not_started": not_started,
        "login_required": login_required,
    }
    return BatchRun(results=results, summary=summary)


async def download_many(
    jobs: Iterable[BatchJob],
    *,
    provider: SnuProxyProvider | None = None,
    download_dir: Path = DEFAULT_DOWNLOAD_DIR,
    profile_dir: Path = DEFAULT_PROFILE_DIR,
    browser_channel: str | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    headless: bool = True,
    concurrency: int = 1,
    per_host_concurrency: int = 1,
    on_result: ResultCallback | None = None,
    playwright_factory: Callable[[], Any] | None = None,
) -> BatchRun:
    provider = provider or SnuProxyProvider()
    resolved_download_dir = download_dir.resolve()
    resolved_profile_dir = profile_dir.resolve()
    resolved_download_dir.mkdir(parents=True, exist_ok=True)
    resolved_profile_dir.mkdir(parents=True, exist_ok=True)

    if playwright_factory is None:
        from playwright.async_api import async_playwright

        playwright_factory = async_playwright

    async with playwright_factory() as playwright:
        options: dict[str, object] = {
            "user_data_dir": str(resolved_profile_dir),
            "headless": headless,
        }
        if browser_channel:
            options["channel"] = browser_channel
        context = await playwright.chromium.launch_persistent_context(**options)
        try:
            cookies = load_saved_cookies(resolved_profile_dir)
            if cookies:
                await context.add_cookies(cookies)

            async def worker(job: BatchJob) -> dict[str, object]:
                return await _download_one(
                    job,
                    context=context,
                    provider=provider,
                    download_dir=resolved_download_dir,
                    timeout_seconds=timeout_seconds,
                )

            return await schedule_jobs(
                jobs,
                worker,
                concurrency=concurrency,
                per_host_concurrency=per_host_concurrency,
                on_result=on_result,
            )
        finally:
            await context.close()


async def _download_one(
    job: BatchJob,
    *,
    context: Any,
    provider: SnuProxyProvider,
    download_dir: Path,
    timeout_seconds: int,
) -> dict[str, object]:
    if not provider.supports_url(job.url):
        return _base_result(
            job,
            ok=False,
            status="unsupported",
            reason="unsupported_domain",
            message="The URL host is not in the configured provider domain list.",
        )

    destination = download_dir / job.filename
    if _valid_pdf_file(destination):
        return _base_result(
            job,
            ok=True,
            status="already_exists",
            output_path=str(destination),
            bytes_written=destination.stat().st_size,
        )

    timeout_ms = timeout_seconds * 1000
    page = await context.new_page()
    try:
        page.set_default_timeout(timeout_ms)
        candidates, response, login_required = await _open_and_discover(
            page, provider.proxied_url(job.url), job.url, timeout_ms
        )

        if login_required:
            # Fully open-access publishers may not be routed by the proxy at all.
            # Try the source page once; if it still cannot expose content, stop the
            # batch so the persistent SNU session can be refreshed by the user.
            candidates, response, direct_login = await _open_and_discover(
                page, job.url, job.url, timeout_ms
            )
            if direct_login or not candidates:
                return _base_result(
                    job,
                    ok=False,
                    status="login_required",
                    reason="login_required",
                    message=(
                        "The SNU proxy session requires login. Refresh the "
                        "persistent profile, then resume this batch."
                    ),
                )

        if response is not None:
            content_type = str(
                response.headers.get("content-type", "")
            ).lower()
            if "application/pdf" in content_type:
                body = await response.body()
                if _looks_like_pdf(body):
                    _atomic_save(destination, body)
                    return _base_result(
                        job,
                        ok=True,
                        status="downloaded",
                        pdf_url=response.url,
                        output_path=str(destination),
                        bytes_written=len(body),
                    )

        if not candidates:
            return _base_result(
                job,
                ok=False,
                status="no_pdf_found",
                reason="no_pdf_found",
                message="No downloadable PDF link was found on the page.",
            )

        last_status: int | None = None
        last_url: str | None = None
        for candidate in candidates[:MAX_PDF_CANDIDATE_ATTEMPTS]:
            try:
                pdf_response = await context.request.get(
                    candidate.href, timeout=timeout_ms
                )
            except Exception:
                continue
            last_status = pdf_response.status
            last_url = pdf_response.url
            if not pdf_response.ok:
                continue
            body = await pdf_response.body()
            if _looks_like_pdf(body):
                _atomic_save(destination, body)
                return _base_result(
                    job,
                    ok=True,
                    status="downloaded",
                    pdf_url=pdf_response.url,
                    output_path=str(destination),
                    bytes_written=len(body),
                )

        if last_status in {401, 403}:
            return _base_result(
                job,
                ok=False,
                status="login_required",
                reason="login_required",
                message=f"HTTP {last_status} suggests login or access is required.",
                pdf_url=last_url,
            )
        return _base_result(
            job,
            ok=False,
            status="download_failed",
            reason="download_failed",
            message="No ranked PDF candidate returned PDF bytes.",
            pdf_url=last_url,
        )
    finally:
        await page.close()


async def _open_and_discover(
    page: Any,
    navigation_url: str,
    source_url: str,
    timeout_ms: int,
) -> tuple[list[PdfCandidate], Any | None, bool]:
    try:
        response = await page.goto(
            navigation_url, wait_until="domcontentloaded", timeout=timeout_ms
        )
        try:
            await page.wait_for_load_state("load", timeout=min(timeout_ms, 15_000))
        except Exception:
            pass
        await page.wait_for_timeout(4_000)
    except Exception:
        return [], None, False

    candidates = await _discover_candidates(page)
    if not candidates:
        candidates = rank_pdf_candidates(
            derive_candidates_from_source(source_url, str(page.url))
        )
    snapshot = await _capture_snapshot(page, bool(candidates))
    login = detect_login_required(snapshot)
    return candidates, response, login.required


async def _discover_candidates(page: Any) -> list[PdfCandidate]:
    try:
        raw = await page.eval_on_selector_all(
            "a[href]",
            """links => links.map(link => {
                const parent = link.closest('li, div, p, section, article');
                return {
                    href: link.href || '',
                    text: (link.textContent || '').trim(),
                    context: (parent?.textContent || link.textContent || '')
                        .trim().slice(0, 300)
                };
            })""",
        )
    except Exception:
        return []

    candidates: list[PdfCandidate] = []
    for item in raw or []:
        href = str(item.get("href", ""))
        lowered = href.lower()
        text = str(item.get("text", ""))
        if (
            re.search(r"\.pdf($|\?)", lowered)
            or re.search(
                r"/pdfdirect/|/pdfft|/content/pdf/|/articlepdf/|"
                r"/stamp/stamp\.jsp|type=printable|/article-pdf/|"
                r"/doi/epdf/|/doi/reader/|/epdf|/doi/pdf/|/pdf/|"
                r"[?&]download=true",
                lowered,
            )
            or ("pdf" in text.lower() and "pdf" in lowered)
        ):
            candidates.append(
                PdfCandidate(
                    href=href,
                    text=text,
                    context=str(item.get("context", "")),
                )
            )
    return rank_pdf_candidates(candidates)


async def _capture_snapshot(page: Any, has_content_access: bool) -> PageSnapshot:
    try:
        title = await page.title()
    except Exception:
        title = ""
    try:
        body = str(await page.text_content("body", timeout=1_000) or "")
    except Exception:
        body = ""
    try:
        has_password = await page.locator("input[type='password']").count() > 0
    except Exception:
        has_password = False
    return PageSnapshot(
        url=str(page.url),
        title=title,
        body_text=body,
        has_password_field=has_password,
        has_content_access=has_content_access,
    )


def _validate_filename(filename: str, job_id: str) -> None:
    if not filename or filename in {".", ".."}:
        raise ValueError(f"Job {job_id!r} requires a filename.")
    if Path(filename).name != filename or "/" in filename or "\\" in filename:
        raise ValueError(f"Job {job_id!r} filename must be a basename.")
    if not filename.lower().endswith(".pdf"):
        raise ValueError(f"Job {job_id!r} filename must end in .pdf.")
    if any(ord(char) < 32 for char in filename):
        raise ValueError(f"Job {job_id!r} filename contains control characters.")


def _valid_pdf_file(path: Path) -> bool:
    try:
        if path.stat().st_size < 20_000:
            return False
        with path.open("rb") as handle:
            return handle.read(5) == b"%PDF-"
    except OSError:
        return False


def _looks_like_pdf(body: bytes) -> bool:
    return len(body) >= 20_000 and body.lstrip().startswith(b"%PDF")


def _atomic_save(destination: Path, body: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.name}.{uuid.uuid4().hex}.part"
    )
    try:
        temporary.write_bytes(body)
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _base_result(
    job: BatchJob,
    *,
    ok: bool,
    status: str,
    reason: str | None = None,
    message: str | None = None,
    pdf_url: str | None = None,
    output_path: str | None = None,
    bytes_written: int | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "event": "result",
        "id": job.id,
        "source_url": job.url,
        "filename": job.filename,
        "ok": ok,
        "status": status,
    }
    optional: dict[str, object | None] = {
        "reason": reason,
        "message": message,
        "pdf_url": pdf_url,
        "output_path": output_path,
        "bytes_written": bytes_written,
    }
    payload.update({key: value for key, value in optional.items() if value is not None})
    return payload
