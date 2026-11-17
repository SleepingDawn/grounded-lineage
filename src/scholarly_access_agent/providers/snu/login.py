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
