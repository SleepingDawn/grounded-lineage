from __future__ import annotations

import re
from urllib.parse import quote, urlparse


def host_for_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"Expected an absolute http(s) URL, got: {url}")
    return normalize_host(parsed.hostname or "")


def normalize_host(host: str) -> str:
    host = host.strip().lower().rstrip(".")
    if host.startswith("www."):
        return host[4:]
    return host


def domain_matches(host: str, pattern: str) -> bool:
    normalized_host = normalize_host(host)
    normalized_pattern = normalize_host(pattern)

    if normalized_pattern.startswith("*."):
        bare = normalized_pattern[2:]
        return normalized_host == bare or normalized_host.endswith(f".{bare}")

    return normalized_host == normalized_pattern or normalized_host.endswith(
        f".{normalized_pattern}"
    )


def any_domain_matches(host: str, patterns: list[str] | tuple[str, ...]) -> bool:
    return any(domain_matches(host, pattern) for pattern in patterns)


def build_proxy_url(url: str, proxy_base: str) -> str:
    host_for_url(url)
    return f"{proxy_base}{quote(url, safe='')}"


# ---------------------------------------------------------------------------
# PDF URL recognition
#
# Publisher PDF endpoints mostly do NOT end in ".pdf", so matching on the
# extension alone misses the real full-text link on most major platforms.
# Patterns below were verified against live proxied pages.
# ---------------------------------------------------------------------------

# Endpoints that serve actual PDF bytes.
_PDF_DIRECT_PATTERNS = (
    r"\.pdf($|\?)",              # generic
    r"/pdfdirect/",              # Wiley
    r"/pdfft",                   # Elsevier / ScienceDirect
    r"/content/pdf/",            # Springer
    r"/articlepdf/",             # RSC
    r"/stamp/stamp\.jsp",        # IEEE
    r"type=printable",           # PLOS
    r"/article-pdf/",            # Oxford University Press
)

# Endpoints that render an in-browser PDF *viewer* (HTML), not the bytes.
# Still worth keeping as candidates, but only after the direct ones.
_PDF_VIEWER_PATTERNS = (
    r"/doi/epdf/",               # Wiley / Taylor & Francis reader
    r"/doi/reader/",             # SAGE reader
    r"/epdf",
)

# Generic "probably a PDF" endpoints -- real bytes on some platforms, a viewer
# wrapper on others (e.g. Wiley's /doi/pdf/ is a wrapper, SAGE's is the bytes).
_PDF_GENERIC_PATTERNS = (
    r"/doi/pdf/",
    r"/pdf/",
    r"[?&]download=true",
)


def looks_like_pdf_url(url: str) -> bool:
    """True if the URL plausibly serves or wraps a full-text PDF."""
    return pdf_url_rank(url) is not None


def pdf_url_rank(url: str) -> int | None:
    """Preference rank for a PDF candidate; lower is better, None means not a PDF.

    0 = serves PDF bytes, 1 = generic/ambiguous, 2 = known HTML viewer wrapper.
    Callers should try candidates in rank order rather than blindly taking the
    first link on the page.
    """
    lowered = url.lower()
    if _matches_any(lowered, _PDF_DIRECT_PATTERNS):
        return 0
    if _matches_any(lowered, _PDF_VIEWER_PATTERNS):
        return 2
    if _matches_any(lowered, _PDF_GENERIC_PATTERNS):
        return 1
    return None


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)
