from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class PageSnapshot:
    url: str
    title: str = ""
    body_text: str = ""
    has_password_field: bool = False
    # True when the page exposes full-text affordances (PDF links, article body).
    # Used to override the word-based login heuristics -- see detect_login_required.
    has_content_access: bool = False


@dataclass(frozen=True)
class LoginDetection:
    required: bool
    reason: str | None = None
    message: str | None = None


SNU_LOGIN_URL_MARKERS = ("login", "signin", "signon", "sso", "auth")
SNU_LOGIN_HOSTS = frozenset({
    "lib.snu.ac.kr", "libproxy.snu.ac.kr", "sso.snu.ac.kr", "my.snu.ac.kr",
})
SNU_TEXT_MARKERS = (
    "snu",
    "seoul national university",
    "\uc11c\uc6b8\ub300\ud559\uad50",
)
LOGIN_TEXT_MARKERS = ("login", "log in", "sign in", "\ub85c\uadf8\uc778")
PASSWORD_TEXT_MARKERS = ("password", "passwd", "\ube44\ubc00\ubc88\ud638")


def detect_login_required(snapshot: PageSnapshot) -> LoginDetection:
    url = snapshot.url.lower()
    text = f"{snapshot.title}\n{snapshot.body_text}".lower()
    combined = f"{url}\n{text}"

    # 1. Hard signal: we actually landed on the SNU login / SSO page.
    #    This is the only fully reliable indicator, so it is checked first.
    if _is_snu_login_url(url):
        return _login_required()

    # 2. Access-granted override.
    #    On a *successfully proxied* publisher page the word-based heuristics below
    #    are unreliable in both directions:
    #      - the proxy injects the institution name ("Seoul National University")
    #        into every page it serves, so SNU_TEXT_MARKERS matches on success;
    #      - publisher headers/footers carry "Login" / "Sign in" / "Password" links
    #        (and often a collapsed login form with a real password input) even when
    #        the full text is fully available.
    #    Together those made every Wiley article page read as a login wall.
    #    So when the page exposes full-text affordances, trust that over the words.
    if snapshot.has_content_access:
        return LoginDetection(required=False)

    # 3. Weak signals -- only consulted when the page showed no content at all.
    if snapshot.has_password_field and _contains_any(combined, SNU_TEXT_MARKERS):
        return _login_required()

    if (
        _contains_any(text, SNU_TEXT_MARKERS)
        and _contains_any(text, LOGIN_TEXT_MARKERS)
        and (snapshot.has_password_field or _contains_any(text, PASSWORD_TEXT_MARKERS))
    ):
        return _login_required()

    return LoginDetection(required=False)


# --- bot-challenge / bot-block pages ------------------------------------------
# Markers adapted from SleepingDawn/paper_download landing_classifier.py. A challenge is
# reported, never solved or bypassed. It explains a failure: the downloader still tries
# PDF endpoints the server serves without a challenge (APS serves its PDF endpoint while
# the article page shows "Just a moment...", observed 2026-11-20).
CHALLENGE_URL_MARKERS = (
    "__cf_chl_rt_tk=",
    "__cf_chl_",
    "/cdn-cgi/challenge",
    "/cdn-cgi/l/chk_captcha",
    "challenges.cloudflare.com",
    "cf-turnstile",
    "/captcha/",
    "validate.perfdrive.com",
)
CHALLENGE_TITLES = (
    "just a moment",
    "attention required",
    "please wait",
    "잠시만 기다리십시오",  # Cloudflare (ko), observed on ScienceDirect
    "잠시만 기다려 주세요",
)
CHALLENGE_TEXT_MARKERS = (
    "verify you are human",
    "are you a robot",
    "are you human",
    "checking if the site connection is secure",
    "checking your browser",
    "unusual traffic",
    "enable javascript and cookies to continue",
    "cloudflare ray id",
    "performing security verification",
    "cloudflare_error_1000",  # Cloudflare 1000-series block box (ScienceDirect, observed 2026-11-20)
    "사람인지 확인",  # "verify you are human" (ko)
)
BOT_CHALLENGE_MESSAGE = (
    "Publisher bot check (e.g. Cloudflare) blocked automated access. This is not an SNU login "
    "problem and renewing the login does not help; it is not bypassed. Use the open-copy "
    "fallbacks in publisher-routes.md (HAL / author manuscript, PMC, arXiv)."
)


def detect_bot_challenge(snapshot: PageSnapshot) -> LoginDetection:
    """A publisher bot-check page (Cloudflare and similar), as opposed to a login wall.

    The challenge URL tokens are decisive. Titles and texts count only when the page shows
    no full-text affordances, since article pages may mention "captcha" in passing.
    """
    url = snapshot.url.lower()
    if _contains_any(url, CHALLENGE_URL_MARKERS):
        return _bot_challenge()
    if snapshot.has_content_access:
        return LoginDetection(required=False)
    title = snapshot.title.strip().lower().rstrip(".… ")
    if any(title.startswith(marker) for marker in CHALLENGE_TITLES):
        return _bot_challenge()
    if _contains_any(snapshot.body_text.lower(), CHALLENGE_TEXT_MARKERS):
        return _bot_challenge()
    return LoginDetection(required=False)


def is_bot_challenge_response(status: int | None, headers: dict | None, body: bytes = b"") -> bool:
    """True for an HTTP response that is a bot check rather than an access denial.

    Cloudflare marks challenge responses with ``cf-mitigated: challenge``; a 403/503 from
    Cloudflare whose body carries challenge markup counts too.
    """
    lowered = {str(k).lower(): str(v).lower() for k, v in (headers or {}).items()}
    if "challenge" in lowered.get("cf-mitigated", ""):
        return True
    if status in {403, 503} and "cloudflare" in lowered.get("server", ""):
        head = body[:20000].decode("utf-8", errors="ignore").lower()
        return any(m in head for m in CHALLENGE_URL_MARKERS + CHALLENGE_TEXT_MARKERS + ("just a moment",))
    return False


def _bot_challenge() -> LoginDetection:
    return LoginDetection(required=True, reason="bot_challenge", message=BOT_CHALLENGE_MESSAGE)


def _is_snu_login_url(url: str) -> bool:
    """True only for SNU's own login/SSO pages.

    The proxy rewrites every publisher host to ``<publisher>-ssl.libproxy.snu.ac.kr``,
    so *every* proxied URL contains "snu.ac.kr". Matching markers anywhere in the URL
    therefore misfires on any article whose path happens to contain "login", "auth",
    "sso" and so on. Rewritten publisher hosts are excluded before matching, and the
    markers are matched against the host and path only (never the query string, which
    carries the encoded target URL on the proxy entry point).
    """
    parsed = urlparse(url if "://" in url else f"https://{url}")
    try:
        port = parsed.port
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or host not in SNU_LOGIN_HOSTS
    ):
        return False
    return _contains_any(f"{host}{parsed.path.lower()}", SNU_LOGIN_URL_MARKERS)


def _login_required() -> LoginDetection:
    return LoginDetection(
        required=True,
        reason="login_required",
        message=(
            "SNU proxy appears to require user login. Complete login in the "
            "persistent browser profile, then retry."
        ),
    )


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)
