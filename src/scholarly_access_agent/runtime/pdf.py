from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Mapping

from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from scholarly_access_agent.core.urls import looks_like_pdf_url, pdf_url_rank
from scholarly_access_agent.providers.snu.login import (
    BOT_CHALLENGE_MESSAGE,
    PageSnapshot,
    detect_bot_challenge,
    detect_login_required,
    is_bot_challenge_response,
)
from scholarly_access_agent.providers.snu.proxy import SnuProxyProvider
from scholarly_access_agent.runtime.browser import (
    DEFAULT_PROFILE_DIR,
    BrowserRuntimeUnavailable,
    _load_sync_playwright,
    capture_page_snapshot,
)
from scholarly_access_agent.runtime.storage import ensure_private_profile, load_saved_cookies


DEFAULT_DOWNLOAD_DIR = Path.home() / ".local/share/snu-library-scholarly-access/downloads"
DEFAULT_TIMEOUT_SECONDS = 30
MAX_RESPONSE_BYTES = 50 * 1024 * 1024
USER_AGENT = "scholarly-access-agent/0.1"
# How many ranked PDF candidates to attempt before giving up on a page.
MAX_PDF_CANDIDATE_ATTEMPTS = 4


@dataclass(frozen=True)
class PdfCandidate:
    href: str
    text: str
    context: str = ""


@dataclass(frozen=True)
class PdfDownloadResult:
    ok: bool
    provider: str
    source_url: str
    status: str
    download_dir: str
    pdf_url: str | None = None
    output_path: str | None = None
    bytes_written: int | None = None
    reason: str | None = None
    message: str | None = None
    candidates: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "ok": self.ok,
            "provider": self.provider,
            "source_url": self.source_url,
            "status": self.status,
            "download_dir": self.download_dir,
        }
        optional: dict[str, object] = {
            "pdf_url": self.pdf_url,
            "output_path": self.output_path,
            "bytes_written": self.bytes_written,
            "reason": self.reason,
            "message": self.message,
        }
        payload.update(
            {key: value for key, value in optional.items() if value is not None}
        )
        if self.candidates:
            payload["candidates"] = self.candidates
        return payload


@dataclass(frozen=True)
class PdfDiscoverResult:
    ok: bool
    provider: str
    source_url: str
    status: str
    candidates: list[dict[str, str]] = field(default_factory=list)
    reason: str | None = None
    message: str | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "ok": self.ok,
            "provider": self.provider,
            "source_url": self.source_url,
            "status": self.status,
        }
        optional: dict[str, object] = {
            "reason": self.reason,
            "message": self.message,
        }
        payload.update(
            {key: value for key, value in optional.items() if value is not None}
        )
        if self.candidates:
            payload["candidates"] = self.candidates
        return payload


def download_pdf(
    source_url: str,
    *,
    provider: SnuProxyProvider | None = None,
    pdf_url: str | None = None,
    download_dir: Path = DEFAULT_DOWNLOAD_DIR,
    profile_dir: Path = DEFAULT_PROFILE_DIR,
    browser_channel: str | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    headless: bool = True,
) -> PdfDownloadResult:
    provider = provider or SnuProxyProvider()
    resolved_download_dir = (download_dir or DEFAULT_DOWNLOAD_DIR).resolve()
    resolved_profile_dir = (profile_dir or DEFAULT_PROFILE_DIR).resolve()
    source_url = resolve_doi_url(source_url, timeout_seconds=min(timeout_seconds, 20))
    source_url, pdf_url = _split_pdf_endpoint(source_url, pdf_url)

    if not provider.supports_url(source_url):
        return _failure(
            provider=provider,
            source_url=source_url,
            download_dir=resolved_download_dir,
            status="unsupported",
            reason="unsupported_domain",
            message="The URL host is not in the configured provider domain list.",
        )

    if pdf_url:
        return _download_pdf_direct(
            source_url, pdf_url, provider, resolved_download_dir, timeout_seconds,
            resolved_profile_dir,
        )

    # Hosts whose article pages show bot checks to a headless browser while the
    # derived PDF endpoint serves the bytes: try that endpoint before opening the page.
    if urlparse(source_url).netloc.lower() in _DIRECT_FIRST_HOSTS:
        for candidate in derive_candidates_from_source(source_url, source_url)[:1]:
            first = _download_pdf_direct(
                source_url, candidate.href, provider, resolved_download_dir, timeout_seconds,
                resolved_profile_dir,
            )
            if first.ok:
                return first

    proxy_url = provider.proxied_url(source_url)

    playwright_factory = _try_load_playwright()
    if playwright_factory is None:
        return _download_via_urllib(
            source_url, proxy_url, provider, resolved_download_dir, timeout_seconds,
        )

    return _download_via_playwright(
        source_url, proxy_url, provider, resolved_download_dir,
        resolved_profile_dir, browser_channel, timeout_seconds, headless,
        playwright_factory,
    )


_DIRECT_FIRST_HOSTS = ("journals.aps.org",)
_DOI_RESOLVER_HOSTS = ("doi.org", "dx.doi.org", "www.doi.org", "link.aps.org")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401 - stop at each hop
        return None


def resolve_doi_url(url: str, *, timeout_seconds: int = 20, max_hops: int = 4) -> str:
    """Turn `doi:10.x/...`, `https://doi.org/10.x/...` or `link.aps.org/doi/...` into the
    publisher's article URL by following redirects without a browser (only the DOI is sent).
    Any other URL, or a failed lookup, is returned unchanged."""

    text = url.strip()
    if text.lower().startswith("doi:"):
        text = "https://doi.org/" + text[4:].strip()
    elif re.match(r"^10\.\d{4,}/\S+$", text):
        text = "https://doi.org/" + text
    if urlparse(text).netloc.lower() not in _DOI_RESOLVER_HOSTS:
        return url
    opener = build_opener(_NoRedirect)
    current = text
    for _ in range(max_hops):
        try:
            opener.open(Request(current, method="HEAD", headers={"User-Agent": "Mozilla/5.0"}),
                        timeout=timeout_seconds)
            return current
        except HTTPError as exc:
            location = exc.headers.get("Location") if exc.code in (301, 302, 303, 307, 308) else None
            if not location:
                return current if current != text else url
            current = urljoin(current, location)
            if urlparse(current).netloc.lower() not in _DOI_RESOLVER_HOSTS:
                return current
        except (URLError, OSError, ValueError):
            return url
    return current


def _split_pdf_endpoint(source_url: str, pdf_url: str | None) -> tuple[str, str | None]:
    """An APS `/<journal>/pdf/<DOI>` link given as the source is fetched as the PDF of its
    abstract page: opening the PDF link as a page meets the bot check, fetching it does not."""
    match = re.match(r"^(https?://journals\.aps\.org)/([a-z]+)/pdf/(10\.\d{4,}/.+?)/?$", source_url, re.I)
    if match and not pdf_url:
        return f"{match.group(1)}/{match.group(2)}/abstract/{match.group(3)}", source_url
    return source_url, pdf_url


def discover_pdfs(
    source_url: str,
    *,
    provider: SnuProxyProvider | None = None,
    profile_dir: Path = DEFAULT_PROFILE_DIR,
    browser_channel: str | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    headless: bool = True,
) -> PdfDiscoverResult:
    provider = provider or SnuProxyProvider()
    resolved_profile_dir = (profile_dir or DEFAULT_PROFILE_DIR).resolve()

    if not provider.supports_url(source_url):
        return _discover_failure(
            provider=provider,
            source_url=source_url,
            status="unsupported",
            reason="unsupported_domain",
            message="The URL host is not in the configured provider domain list.",
        )

    proxy_url = provider.proxied_url(source_url)

    playwright_factory = _try_load_playwright()
    if playwright_factory is None:
        return _discover_via_urllib(
            source_url, proxy_url, provider, timeout_seconds,
        )

    return _discover_via_playwright(
        source_url, proxy_url, provider, resolved_profile_dir,
        browser_channel, timeout_seconds, headless, playwright_factory,
    )


# ---------------------------------------------------------------------------
# PDF download helpers
# ---------------------------------------------------------------------------


def _download_pdf_direct(
    source_url: str,
    pdf_url: str,
    provider: SnuProxyProvider,
    download_dir: Path,
    timeout_seconds: int,
    profile_dir: Path = DEFAULT_PROFILE_DIR,
) -> PdfDownloadResult:
    """Download a specific PDF URL without page discovery."""
    playwright_factory = _try_load_playwright()
    if playwright_factory is not None:
        try:
            return _download_pdf_direct_playwright(
                source_url, pdf_url, provider, download_dir,
                timeout_seconds, playwright_factory, profile_dir,
            )
        except Exception:
            pass

    try:
        pdf = _fetch(pdf_url, timeout_seconds=timeout_seconds)
    except HTTPError as exc:
        return _http_failure(provider, source_url, download_dir, exc)
    except URLError as exc:
        return _failure(
            provider=provider,
            source_url=source_url,
            download_dir=download_dir,
            status="download_failed",
            pdf_url=pdf_url,
            reason="download_failed",
            message=type(exc).__name__,
        )

    if not _is_pdf_response(pdf.url, pdf.headers, pdf.body):
        return _failure(
            provider=provider,
            source_url=source_url,
            download_dir=download_dir,
            status="download_failed",
            pdf_url=pdf.url,
            reason="download_failed",
            message="The provided PDF URL did not return PDF content.",
        )

    return _save_pdf(provider, source_url, pdf.url, pdf.body, download_dir)


def _download_pdf_direct_playwright(
    source_url: str,
    pdf_url: str,
    provider: SnuProxyProvider,
    download_dir: Path,
    timeout_seconds: int,
    playwright_factory,
    profile_dir: Path = DEFAULT_PROFILE_DIR,
) -> PdfDownloadResult:
    timeout_ms = timeout_seconds * 1000
    # Must reuse the persistent profile: the proxy session lives in its cookies.
    # Launching a throwaway context here meant --pdf-url always fetched as an
    # anonymous visitor and got an HTML paywall page back instead of the PDF.
    resolved_profile_dir = (profile_dir or DEFAULT_PROFILE_DIR).resolve()
    ensure_private_profile(resolved_profile_dir)
    with playwright_factory() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(resolved_profile_dir), headless=True,
        )
        try:
            cookies = load_saved_cookies(resolved_profile_dir)
            if cookies:
                context.add_cookies(cookies)
            api = context.request
            pdf_resp = api.get(pdf_url, timeout=timeout_ms)
            pdf_headers = dict(pdf_resp.headers)
            pdf_body = pdf_resp.body()

            if not pdf_resp.ok:
                return _failure(
                    provider=provider,
                    source_url=source_url,
                    download_dir=download_dir,
                    status="download_failed",
                    pdf_url=pdf_resp.url,
                    reason="download_failed",
                    message=f"HTTP {pdf_resp.status}: {pdf_resp.status_text}",
                )

            if not _is_pdf_response(pdf_resp.url, pdf_headers, pdf_body):
                return _failure(
                    provider=provider,
                    source_url=source_url,
                    download_dir=download_dir,
                    status="download_failed",
                    pdf_url=pdf_resp.url,
                    reason="download_failed",
                    message="The provided PDF URL did not return PDF content.",
                )

            return _save_pdf(provider, source_url, pdf_resp.url, pdf_body, download_dir)
        finally:
            context.close()


def _download_via_urllib(
    source_url: str,
    proxy_url: str,
    provider: SnuProxyProvider,
    download_dir: Path,
    timeout_seconds: int,
) -> PdfDownloadResult:
    try:
        first = _fetch(proxy_url, timeout_seconds=timeout_seconds)
    except HTTPError as exc:
        return _http_failure(provider, source_url, download_dir, exc)
    except URLError as exc:
        return _failure(
            provider=provider,
            source_url=source_url,
            download_dir=download_dir,
            status="download_failed",
            reason="download_failed",
            message=type(exc).__name__,
        )

    if _is_pdf_response(first.url, first.headers, first.body):
        return _save_pdf(provider, source_url, first.url, first.body, download_dir)

    page = _parse_html(first.body, first.headers)
    first_snapshot = PageSnapshot(
        url=first.url,
        title=page.title,
        body_text=page.text,
        has_password_field=page.has_password_field,
        has_content_access=bool(page.all_pdf_candidates(first.url)),
    )
    if detect_bot_challenge(first_snapshot).required:
        return _blocked_failure(provider, source_url, download_dir)
    login = detect_login_required(first_snapshot)
    if login.required:
        return _failure(
            provider=provider,
            source_url=source_url,
            download_dir=download_dir,
            status="login_required",
            reason=login.reason or "login_required",
            message=login.message or "Login is required before PDF download.",
        )

    candidates = _main_candidates(page.all_pdf_candidates(first.url))
    if not candidates:
        return _failure(
            provider=provider,
            source_url=source_url,
            download_dir=download_dir,
            status="no_pdf_found",
            reason="no_pdf_found",
            message="No downloadable PDF link was found on the page.",
        )

    candidate_url = candidates[0].href

    try:
        pdf = _fetch(candidate_url, timeout_seconds=timeout_seconds)
    except HTTPError as exc:
        return _http_failure(provider, source_url, download_dir, exc)
    except URLError as exc:
        return _failure(
            provider=provider,
            source_url=source_url,
            download_dir=download_dir,
            status="download_failed",
            pdf_url=candidate_url,
            reason="download_failed",
            message=type(exc).__name__,
        )

    if not _is_pdf_response(pdf.url, pdf.headers, pdf.body):
        return _failure(
            provider=provider,
            source_url=source_url,
            download_dir=download_dir,
            status="download_failed",
            pdf_url=pdf.url,
            reason="download_failed",
            message="The discovered PDF link did not return PDF content.",
        )

    return _save_pdf(provider, source_url, pdf.url, pdf.body, download_dir)


def _download_via_playwright(
    source_url: str,
    proxy_url: str,
    provider: SnuProxyProvider,
    download_dir: Path,
    profile_dir: Path,
    browser_channel: str | None,
    timeout_seconds: int,
    headless: bool,
    playwright_factory,
) -> PdfDownloadResult:
    timeout_ms = timeout_seconds * 1000
    ensure_private_profile(profile_dir)

    with playwright_factory() as p:
        launch_options: dict[str, object] = {
            "user_data_dir": str(profile_dir),
            "headless": headless,
        }
        if browser_channel:
            launch_options["channel"] = browser_channel

        context = p.chromium.launch_persistent_context(**launch_options)
        try:
            cookies = load_saved_cookies(profile_dir)
            if cookies:
                context.add_cookies(cookies)
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(timeout_ms)

            try:
                response = page.goto(
                    proxy_url, wait_until="domcontentloaded", timeout=timeout_ms,
                )
                _wait_for_page_ready(page, timeout_ms)
            except Exception as exc:
                return _failure(
                    provider=provider,
                    source_url=source_url,
                    download_dir=download_dir,
                    status="download_failed",
                    reason="navigation_failed",
                    message=type(exc).__name__,
                )

            snapshot = capture_page_snapshot(page)
            # A challenge page explains a failure but does not end the attempt: some
            # publishers serve the PDF endpoint while the article page shows a check.
            page_challenge = detect_bot_challenge(snapshot).required
            login = (detect_login_required(snapshot) if not page_challenge
                     else detect_login_required(PageSnapshot(url=snapshot.url)))
            if login.required:
                # Open-access publishers (PLOS, Frontiers, MDPI, PeerJ ...) are not
                # served by the library proxy at all -- proxying them just bounces to
                # the SNU login page -- yet the article is freely readable. So when
                # the proxy route dead-ends, retry the original URL without the proxy.
                if login.required and _try_direct_access(page, source_url, timeout_ms):
                    snapshot = capture_page_snapshot(page)
                    login = detect_login_required(snapshot)

                if login.required:
                    return _failure(
                        provider=provider,
                        source_url=source_url,
                        download_dir=download_dir,
                        status="login_required",
                        reason="login_required",
                        message="Complete manual login with open-url --wait-for-login, then retry.",
                    )


            content_type = (
                response.headers.get("content-type", "") if response else ""
            ).lower()
            if "application/pdf" in content_type:
                body = response.body() if response else b""
                if _looks_like_pdf_body(body):
                    return _save_pdf(
                        provider,
                        source_url,
                        response.url if response else page.url,
                        body,
                        download_dir,
                    )

            page_obj = _parse_html(
                page.content().encode("utf-8"),
                {"content-type": "text/html; charset=utf-8"},
            )

            candidates = page_obj.all_pdf_candidates(page.url)

            # Also collect Playwright-level link context
            pw_candidates = _discover_pdf_links_playwright(page)
            if pw_candidates:
                candidates = pw_candidates

            # Platforms that build the PDF link in JS expose nothing to scrape;
            # derive their endpoints from the article URL instead.
            if not candidates:
                candidates = derive_candidates_from_source(source_url, page.url)
                _trace(f"[download] derived {len(candidates)} candidates from source URL")

            if not candidates:
                if page_challenge:
                    return _blocked_failure(provider, source_url, download_dir)
                return _failure(
                    provider=provider,
                    source_url=source_url,
                    download_dir=download_dir,
                    status="no_pdf_found",
                    reason="no_pdf_found",
                    message="No downloadable PDF link was found on the page.",
                )

            candidates = _main_candidates(candidates)

            # Try candidates in rank order. The first link on the page is often a
            # viewer wrapper that returns HTML (Wiley's /doi/pdf/ is the classic
            # case), so stopping at the first one loses articles that are in fact
            # fully available.
            api = context.request
            last_status: int | None = None
            last_url: str | None = None
            last_challenge = False
            for candidate in candidates[:MAX_PDF_CANDIDATE_ATTEMPTS]:
                try:
                    pdf_resp = api.get(candidate.href, timeout=timeout_ms)
                except Exception as exc:
                    _trace(f"[download] candidate failed: {type(exc).__name__}")
                    continue
                last_status, last_url = pdf_resp.status, pdf_resp.url
                if not pdf_resp.ok:
                    try:
                        head = pdf_resp.body()[:20000]
                    except Exception:
                        head = b""
                    last_challenge = is_bot_challenge_response(
                        pdf_resp.status, dict(pdf_resp.headers), head)
                    continue
                pdf_body = pdf_resp.body()
                if _is_pdf_response(pdf_resp.url, dict(pdf_resp.headers), pdf_body):
                    return _save_pdf(
                        provider, source_url, pdf_resp.url, pdf_body, download_dir,
                    )

            if last_challenge or page_challenge:
                return _blocked_failure(provider, source_url, download_dir,
                                        candidates=_candidates_to_dicts(candidates))

            if last_status in {401, 403}:
                return _failure(
                    provider=provider,
                    source_url=source_url,
                    download_dir=download_dir,
                    status="login_required",
                    reason="login_required",
                    message=f"HTTP {last_status} suggests login or access approval is required.",
                    candidates=_candidates_to_dicts(candidates),
                )

            return _failure(
                provider=provider,
                source_url=source_url,
                download_dir=download_dir,
                status="download_failed",
                pdf_url=last_url,
                reason="download_failed",
                message=(
                    f"None of the {min(len(candidates), MAX_PDF_CANDIDATE_ATTEMPTS)} "
                    "PDF candidates returned PDF content."
                ),
                candidates=_candidates_to_dicts(candidates),
            )
        finally:
            context.close()


# ---------------------------------------------------------------------------
# PDF discovery helpers
# ---------------------------------------------------------------------------


def _discover_via_urllib(
    source_url: str,
    proxy_url: str,
    provider: SnuProxyProvider,
    timeout_seconds: int,
) -> PdfDiscoverResult:
    try:
        first = _fetch(proxy_url, timeout_seconds=timeout_seconds)
    except HTTPError as exc:
        return _discover_failure(
            provider=provider,
            source_url=source_url,
            status="download_failed",
            reason="download_failed",
            message=f"HTTP {exc.code}: {exc.reason}",
        )
    except URLError as exc:
        return _discover_failure(
            provider=provider,
            source_url=source_url,
            status="download_failed",
            reason="download_failed",
            message=type(exc).__name__,
        )

    if _is_pdf_response(first.url, first.headers, first.body):
        candidates = [
            {"href": first.url, "text": "(direct PDF)", "context": ""}
        ]
        return PdfDiscoverResult(
            ok=True,
            provider=provider.provider_id,
            source_url=source_url,
            status="discovered",
            candidates=candidates,
        )

    page = _parse_html(first.body, first.headers)
    login = detect_login_required(
        PageSnapshot(
            url=first.url,
            title=page.title,
            body_text=page.text,
            has_password_field=page.has_password_field,
            has_content_access=bool(page.all_pdf_candidates(first.url)),
        )
    )
    if login.required:
        return _discover_failure(
            provider=provider,
            source_url=source_url,
            status="login_required",
            reason="login_required",
            message=login.message or "Login is required before PDF discovery.",
        )

    html_candidates = page.all_pdf_candidates(first.url)
    candidates = _candidates_to_dicts(html_candidates)

    if not candidates:
        return _discover_failure(
            provider=provider,
            source_url=source_url,
            status="no_pdf_found",
            reason="no_pdf_found",
            message="No downloadable PDF link was found on the page.",
        )

    return PdfDiscoverResult(
        ok=True,
        provider=provider.provider_id,
        source_url=source_url,
        status="discovered",
        candidates=candidates,
    )


def _discover_via_playwright(
    source_url: str,
    proxy_url: str,
    provider: SnuProxyProvider,
    profile_dir: Path,
    browser_channel: str | None,
    timeout_seconds: int,
    headless: bool,
    playwright_factory,
) -> PdfDiscoverResult:
    timeout_ms = timeout_seconds * 1000
    ensure_private_profile(profile_dir)

    with playwright_factory() as p:
        _trace("[discover] playwright loaded")

        launch_options: dict[str, object] = {
            "user_data_dir": str(profile_dir),
            "headless": headless,
        }
        if browser_channel:
            launch_options["channel"] = browser_channel

        _trace("[discover] launching persistent context ...")
        context = p.chromium.launch_persistent_context(**launch_options)
        _trace("[discover] context launched")
        try:
            cookies = load_saved_cookies(profile_dir)
            if cookies:
                context.add_cookies(cookies)
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(timeout_ms)
            _trace(f"[discover] navigating to proxy URL (timeout={timeout_ms}ms) ...")

            try:
                page.goto(
                    proxy_url, wait_until="domcontentloaded", timeout=timeout_ms,
                )
                _trace("[discover] domcontentloaded fired, waiting for page ready ...")
                _wait_for_page_ready(page, timeout_ms)
                _trace("[discover] page ready")
            except Exception as exc:
                _trace(f"[discover] navigation failed: {type(exc).__name__}")
                return _discover_failure(
                    provider=provider,
                    source_url=source_url,
                    status="download_failed",
                    reason="navigation_failed",
                    message=type(exc).__name__,
                )

            _trace("[discover] capturing page snapshot ...")
            snapshot = capture_page_snapshot(page)
            if detect_bot_challenge(snapshot).required:
                _trace("[discover] bot challenge page")
                derived = _candidates_to_dicts(derive_candidates_from_source(source_url, page.url))
                if derived:
                    return PdfDiscoverResult(
                        ok=True,
                        provider=provider.provider_id,
                        source_url=source_url,
                        status="discovered",
                        candidates=derived,
                    )
                return _discover_failure(
                    provider=provider,
                    source_url=source_url,
                    status="blocked",
                    reason="bot_challenge",
                    message=BOT_CHALLENGE_MESSAGE,
                )
            login = detect_login_required(snapshot)
            _trace(f"[discover] login_required={login.required}")
            if login.required:
                return _discover_failure(
                    provider=provider,
                    source_url=source_url,
                    status="login_required",
                    reason="login_required",
                    message="Complete manual login with open-url --wait-for-login, then retry.",
                )

            _trace("[discover] running JS pdf link discovery ...")
            candidates = _discover_pdf_links_playwright(page)
            _trace(f"[discover] JS discovery found {len(candidates)} candidates")

            # Fall back to HTML-parsed candidates
            if not candidates:
                _trace("[discover] falling back to HTML content parse ...")
                page_obj = _parse_html(
                    page.content().encode("utf-8"),
                    {"content-type": "text/html; charset=utf-8"},
                )
                candidates = page_obj.all_pdf_candidates(page.url)
                _trace(f"[discover] HTML parse found {len(candidates)} candidates")

            candidate_dicts = _candidates_to_dicts(candidates)

            if not candidate_dicts:
                return _discover_failure(
                    provider=provider,
                    source_url=source_url,
                    status="no_pdf_found",
                    reason="no_pdf_found",
                    message="No downloadable PDF link was found on the page.",
                )

            return PdfDiscoverResult(
                ok=True,
                provider=provider.provider_id,
                source_url=source_url,
                status="discovered",
                candidates=candidate_dicts,
            )
        finally:
            context.close()


def _try_direct_access(page: Any, source_url: str, timeout_ms: int) -> bool:
    """Navigate to the publisher URL without the proxy. True if a page loaded.

    The library proxy only carries subscribed content; open-access publishers are
    absent from it, so the proxy route redirects to the SNU login page even though
    the article needs no authentication at all. Going direct is the correct route
    for those. Access is still judged afterwards by the usual snapshot checks.
    """
    try:
        _trace("[direct] proxy route dead-ended, retrying without proxy ...")
        page.goto(source_url, wait_until="domcontentloaded", timeout=timeout_ms)
        _wait_for_page_ready(page, timeout_ms)
        return True
    except Exception as exc:
        _trace(f"[direct] direct navigation failed: {type(exc).__name__}")
        return False


def _trace(msg: str) -> None:
    """Write a timestamped trace message to stderr (never stdout, to keep MCP clean)."""
    ts = time.monotonic()
    sys.stderr.write(f"[{ts:07.2f}] {msg}\n")
    sys.stderr.flush()


def _wait_for_page_ready(page: Any, timeout_ms: int) -> None:
    """Wait for page to settle after navigation.

    Uses ``load`` state (not ``networkidle``) because publisher pages often have
    persistent connections (analytics, websockets, polling) that prevent the
    page from ever reaching network-idle.
    """
    _trace("[wait] waiting for 'load' state ...")
    try:
        page.wait_for_load_state("load", timeout=min(timeout_ms, 15_000))
        _trace("[wait] 'load' state reached")
    except Exception:
        _trace("[wait] 'load' state timed out, continuing")
    # Extra settle time for JS-rendered content (React/Vue shadow DOM, etc.)
    _trace("[wait] settle delay 4s ...")
    page.wait_for_timeout(4_000)
    _trace("[wait] settle done")


def _discover_pdf_links_playwright(page: Any) -> list[PdfCandidate]:
    """Extract all PDF candidate links with context via a single JS evaluation."""
    _trace("[js-discover] running page.evaluate() ...")
    try:
        raw = page.evaluate(
            """() => {
                const results = [];
                const links = document.querySelectorAll('a[href]');
                for (const link of links) {
                    const href = link.href || '';
                    if (!href || href.startsWith('javascript:') || href.startsWith('mailto:') || href.startsWith('#'))
                        continue;
                    const text = (link.textContent || '').trim();
                    // Publisher full-text endpoints rarely end in ".pdf"
                    // (Wiley /doi/pdfdirect/, Elsevier /pdfft, Springer /content/pdf/,
                    // IEEE /stamp/stamp.jsp ...), so match those shapes too.
                    // Ranking/filtering happens in Python via pdf_url_rank.
                    const h = href.toLowerCase();
                    const isPdf = /\\.pdf($|\\?)/.test(h)
                        || /\\/pdfdirect\\/|\\/pdfft|\\/content\\/pdf\\/|\\/articlepdf\\/|\\/stamp\\/stamp\\.jsp|type=printable|\\/article-pdf\\//.test(h)
                        || /\\/doi\\/epdf\\/|\\/doi\\/reader\\/|\\/epdf/.test(h)
                        || /\\/doi\\/pdf\\/|\\/pdf\\/|[?&]download=true/.test(h)
                        || (text.toLowerCase().includes('pdf') && h.includes('pdf'));
                    if (!isPdf) continue;
                    const parent = link.closest('li, div, p, section, article');
                    const context = (parent?.textContent || text).trim().slice(0, 300);
                    results.push({ href, text, context });
                }
                return results;
            }"""
        )
    except Exception as exc:
        _trace(f"[js-discover] evaluate failed: {type(exc).__name__}")
        return []

    candidates: list[PdfCandidate] = []
    for item in raw:
        candidates.append(
            PdfCandidate(
                href=str(item.get("href", "")),
                text=str(item.get("text", "")),
                context=str(item.get("context", "")),
            )
        )
    _trace(f"[js-discover] evaluate returned {len(candidates)} raw candidates")
    return rank_pdf_candidates(candidates)


def _candidates_to_dicts(candidates: list[PdfCandidate]) -> list[dict[str, str]]:
    return [{"href": c.href, "text": c.text, "context": c.context} for c in candidates]


# ---------------------------------------------------------------------------
# Shared primitives
# ---------------------------------------------------------------------------


def _try_load_playwright():
    try:
        return _load_sync_playwright()
    except BrowserRuntimeUnavailable:
        return None


@dataclass(frozen=True)
class _FetchResult:
    url: str
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True)
class _Link:
    href: str
    text: str


class _HtmlPage:
    def __init__(
        self,
        *,
        title: str,
        text: str,
        links: list[_Link],
        has_password_field: bool,
    ) -> None:
        self.title = title
        self.text = text
        self.links = links
        self.has_password_field = has_password_field

    def all_pdf_candidates(self, base_url: str) -> list[PdfCandidate]:
        results: list[PdfCandidate] = []
        for link in self.links:
            href = link.href.strip()
            if not href or href.startswith(("#", "javascript:", "mailto:")):
                continue
            absolute = urljoin(base_url, href)
            if _looks_like_pdf_url(absolute):
                results.append(PdfCandidate(href=absolute, text=link.text))
            elif "pdf" in link.text.lower() and "pdf" in urlparse(absolute).path.lower():
                results.append(PdfCandidate(href=absolute, text=link.text))
        return rank_pdf_candidates(results)


# (viewer -> direct) rewrites, applied to the page's own links.
# Several platforms only ever link the in-browser viewer; the byte-serving
# endpoint exists but is never present in the DOM, so it has to be derived.
_DIRECT_VARIANT_REWRITES = (
    ("/doi/epdf/", "/doi/pdfdirect/"),    # Wiley reader   -> bytes
    ("/doi/pdf/", "/doi/pdfdirect/"),     # Wiley wrapper  -> bytes
    ("/doi/reader/", "/doi/pdf/"),        # SAGE reader    -> bytes
    ("/articles/abs/", "/articles/pdf/"),
)


def derive_candidates_from_source(source_url: str, page_url: str) -> list[PdfCandidate]:
    """Synthesise PDF candidates from the article URL when the DOM exposes none.

    Some platforms build the PDF link in JavaScript or hide it behind a viewer
    component, so ``a[href]`` scraping finds nothing even though the article is
    accessible. Their PDF endpoints are, however, derivable from the article URL.
    Returned candidates are still verified by magic bytes before being saved.

    Both URLs are used: the landing URL carries the proxied host (needed for
    subscribed content), while the original URL still identifies the publisher when
    the proxy redirected somewhere unrelated, such as its own login page.
    """
    out: list[PdfCandidate] = []
    seen: set[str] = set()
    for url in (page_url, source_url):
        if not url:
            continue
        for candidate in _derive_for_url(url):
            if candidate.href not in seen:
                seen.add(candidate.href)
                out.append(candidate)
    return out


def _derive_for_url(page_url: str) -> list[PdfCandidate]:
    parsed = urlparse(page_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path
    host = parsed.netloc.lower()
    out: list[str] = []

    if "sciencedirect" in host or "elsevier" in host:
        match = re.search(r"/pii/([A-Z0-9]+)", path, flags=re.IGNORECASE)
        if match:
            out.append(f"{origin}/science/article/pii/{match.group(1)}/pdfft?isDTMRedir=true")
    elif "journals.aps.org" in host:
        # APS article pages build the PDF link client-side; /<journal>/pdf/<DOI> serves the bytes.
        match = re.match(r"/([a-z]+)/(?:abstract|article|full)/(10\.\d{4,}/.+?)/?$", path, flags=re.IGNORECASE)
        if match:
            out.append(f"{origin}/{match.group(1)}/pdf/{match.group(2)}")
    elif "ieee" in host:
        match = re.search(r"/document/(\d+)", path)
        if match:
            out.append(f"{origin}/stamp/stamp.jsp?arnumber={match.group(1)}")
    elif "tandfonline" in host:
        doi = re.search(r"/doi/(?:full|abs)/(.+)$", path)
        if doi:
            out.append(f"{origin}/doi/pdf/{doi.group(1)}?download=true")
            out.append(f"{origin}/doi/epdf/{doi.group(1)}")
    # Open-access platforms: the PDF is free but the link is rendered client-side.
    elif "plos" in host:
        doi = re.search(r"id=([^&]+)", parsed.query) or re.search(r"/article/(.+)$", path)
        if doi:
            journal = re.match(r"/([a-z]+)/", path)
            section = journal.group(1) if journal else "plosone"
            out.append(f"{origin}/{section}/article/file?id={doi.group(1)}&type=printable")
    elif "frontiersin" in host:
        doi = re.search(r"/articles/(10\.\d{4,}/[^/]+)", path)
        if doi:
            out.append(f"{origin}/articles/{doi.group(1)}/pdf")
    elif "mdpi" in host:
        out.append(f"{origin}{path.rstrip('/')}/pdf")
    elif "peerj" in host:
        out.append(f"{origin}{path.rstrip('/')}.pdf")

    return [PdfCandidate(href=href, text="(derived)", context="") for href in out]


def derive_direct_variants(candidates: list[PdfCandidate]) -> list[PdfCandidate]:
    """Add byte-serving variants derived from viewer links.

    Wiley is the motivating case: an article page links only /doi/pdf/ (an HTML
    viewer wrapper) and /doi/epdf/, while the actual PDF lives at /doi/pdfdirect/.
    Without this the download fails even though the article is fully accessible.
    """
    seen = {candidate.href for candidate in candidates}
    derived: list[PdfCandidate] = []
    for candidate in candidates:
        for viewer, direct in _DIRECT_VARIANT_REWRITES:
            if viewer in candidate.href:
                variant = candidate.href.replace(viewer, direct)
                if variant not in seen:
                    seen.add(variant)
                    derived.append(
                        PdfCandidate(
                            href=variant,
                            text=candidate.text,
                            context=candidate.context,
                        )
                    )
    return candidates + derived


def rank_pdf_candidates(candidates: list[PdfCandidate]) -> list[PdfCandidate]:
    """Order candidates so byte-serving endpoints are tried before viewer wrappers.

    Supplementary material is pushed to the very back: a "Supporting Information"
    PDF is a real PDF, so it survives the URL filter and would otherwise be picked
    ahead of the article itself when it appears earlier in the DOM.
    """
    def sort_key(index_and_candidate: tuple[int, PdfCandidate]) -> tuple[int, int, int]:
        index, candidate = index_and_candidate
        rank = pdf_url_rank(candidate.href)
        rank = 1 if rank is None else rank
        return (1 if _is_supplementary(candidate) else 0, rank, index)

    candidates = derive_direct_variants(candidates)
    ordered = sorted(enumerate(candidates), key=sort_key)
    return [candidate for _, candidate in ordered]


_SUPPLEMENTARY_MARKERS = (
    "supplementary", "supporting information", "supplemental",
    "appendix", " esi", "(esi", "data s", "table s", "figure s",
)


def _is_supplementary(candidate: PdfCandidate) -> bool:
    haystack = f"{candidate.text} {candidate.context}".lower()
    if any(marker in haystack for marker in _SUPPLEMENTARY_MARKERS):
        return True
    return bool(re.search(r"\bs\d+\b", haystack))


class _PdfLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.links: list[_Link] = []
        self.has_password_field = False
        self._in_title = False
        self._current_href: str | None = None
        self._current_text: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attr_map = {key.lower(): value or "" for key, value in attrs}
        if tag.lower() == "title":
            self._in_title = True
        elif tag.lower() == "a" and attr_map.get("href"):
            self._current_href = attr_map["href"]
            self._current_text = []
        elif tag.lower() == "input":
            input_type = attr_map.get("type", "").lower()
            if input_type == "password":
                self.has_password_field = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False
        elif tag.lower() == "a" and self._current_href is not None:
            self.links.append(
                _Link(self._current_href, " ".join(self._current_text).strip())
            )
            self._current_href = None
            self._current_text = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text:
            return
        self.text_parts.append(text)
        if self._in_title:
            self.title_parts.append(text)
        if self._current_href is not None:
            self._current_text.append(text)

    def page(self) -> _HtmlPage:
        return _HtmlPage(
            title=" ".join(self.title_parts).strip(),
            text=" ".join(self.text_parts).strip(),
            links=self.links,
            has_password_field=self.has_password_field,
        )


def _fetch(url: str, *, timeout_seconds: int) -> _FetchResult:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout_seconds) as response:
        body = _read_limited(response, MAX_RESPONSE_BYTES)
        return _FetchResult(
            url=response.geturl(),
            headers=dict(response.headers.items()),
            body=body,
        )


def _read_limited(response: object, max_bytes: int) -> bytes:
    body = response.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise URLError(f"response exceeded {max_bytes} bytes")
    return body


def _parse_html(body: bytes, headers: Mapping[str, str]) -> _HtmlPage:
    parser = _PdfLinkParser()
    parser.feed(body.decode(_charset(headers), errors="replace"))
    return parser.page()


def _charset(headers: Mapping[str, str]) -> str:
    content_type = _header(headers, "content-type")
    match = re.search(r"charset=([^;\s]+)", content_type, flags=re.IGNORECASE)
    return match.group(1) if match else "utf-8"


def _is_pdf_response(
    url: str, headers: Mapping[str, str], body: bytes
) -> bool:
    content_type = _header(headers, "content-type").lower()
    if "application/pdf" in content_type:
        return True
    return _looks_like_pdf_url(url) and _looks_like_pdf_body(body)


def _looks_like_pdf_url(url: str) -> bool:
    # Delegates to the shared matcher, which knows the publisher endpoint shapes
    # that do not end in ".pdf". Body bytes are still checked separately, so a
    # broader URL match cannot cause an HTML page to be saved as a PDF.
    return looks_like_pdf_url(url)


def _looks_like_pdf_body(body: bytes) -> bool:
    return body.lstrip().startswith(b"%PDF")


def _save_pdf(
    provider: SnuProxyProvider,
    source_url: str,
    pdf_url: str,
    body: bytes,
    download_dir: Path,
) -> PdfDownloadResult:
    if not _looks_like_pdf_body(body):
        return _failure(
            provider=provider,
            source_url=source_url,
            download_dir=download_dir,
            status="download_failed",
            pdf_url=pdf_url,
            reason="download_failed",
            message="The response was labelled as PDF but did not contain PDF bytes.",
        )

    download_dir.mkdir(parents=True, exist_ok=True)
    output_path = _available_path(download_dir / _filename_for_pdf_url(pdf_url))
    output_path.write_bytes(body)
    return PdfDownloadResult(
        ok=True,
        provider=provider.provider_id,
        source_url=source_url,
        status="downloaded",
        pdf_url=pdf_url,
        download_dir=str(download_dir),
        output_path=str(output_path),
        bytes_written=len(body),
    )


def _filename_for_pdf_url(pdf_url: str) -> str:
    parsed = urlparse(pdf_url)
    name = unquote(Path(parsed.path).name) or "article.pdf"
    if not name.lower().endswith(".pdf"):
        name = f"{name}.pdf"
    return _safe_filename(name)


def _safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "article.pdf"


def _available_path(path: Path) -> Path:
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    for index in range(1, 1000):
        candidate = path.with_name(f"{stem}-{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not find an available filename for {path}")


def _http_failure(
    provider: SnuProxyProvider,
    source_url: str,
    download_dir: Path,
    exc: HTTPError,
) -> PdfDownloadResult:
    try:
        head = exc.read(20000) if exc.fp else b""
    except Exception:
        head = b""
    if is_bot_challenge_response(exc.code, dict(exc.headers or {}), head):
        return _blocked_failure(provider, source_url, download_dir)
    if exc.code in {401, 403}:
        return _failure(
            provider=provider,
            source_url=source_url,
            download_dir=download_dir,
            status="login_required",
            reason="login_required",
            message=f"HTTP {exc.code} suggests login or access approval is required.",
        )
    return _failure(
        provider=provider,
        source_url=source_url,
        download_dir=download_dir,
        status="download_failed",
        reason="download_failed",
        message=f"HTTP {exc.code}: {exc.reason}",
    )


def _blocked_failure(provider, source_url, download_dir, **extra) -> PdfDownloadResult:
    return _failure(
        provider=provider,
        source_url=source_url,
        download_dir=download_dir,
        status="blocked",
        reason="bot_challenge",
        message=BOT_CHALLENGE_MESSAGE,
        **extra,
    )


def _failure(
    *,
    provider: SnuProxyProvider,
    source_url: str,
    download_dir: Path,
    status: str,
    reason: str,
    message: str,
    pdf_url: str | None = None,
    candidates: list[dict[str, str]] | None = None,
) -> PdfDownloadResult:
    return PdfDownloadResult(
        ok=False,
        provider=provider.provider_id,
        source_url=source_url,
        status=status,
        download_dir=str(download_dir),
        pdf_url=pdf_url,
        reason=reason,
        message=message,
        candidates=candidates or [],
    )


def _discover_failure(
    *,
    provider: SnuProxyProvider,
    source_url: str,
    status: str,
    reason: str,
    message: str,
) -> PdfDiscoverResult:
    return PdfDiscoverResult(
        ok=False,
        provider=provider.provider_id,
        source_url=source_url,
        status=status,
        reason=reason,
        message=message,
    )


def _header(headers: Mapping[str, str], name: str) -> str:
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return ""


def _main_candidates(candidates: list[PdfCandidate]) -> list[PdfCandidate]:
    """Never substitute a supplement when the main paper download fails."""
    return [c for c in candidates if not _is_supplementary(c)]
