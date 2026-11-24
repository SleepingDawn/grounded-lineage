"""Minimal OpenAlex client for the lineage workflow (stdlib only).

- OPENALEX_API_KEY is read from the environment and, on Windows, from the saved user
  variable, so a key saved after the client started is still picked up.
- The key never appears in error messages: failures report status and filter only.
- A long Retry-After means the daily budget is spent; QuotaExhausted is raised instead of
  sleeping for hours. Callers keep their caches, so rerunning resumes.
"""
from __future__ import annotations

import json
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from scholarly_access_agent.runtime.public import _context

API = "https://api.openalex.org/works"
USER_AGENT = "snu-research-agent-lineage"
FIELDS = ",".join([
    "id", "doi", "title", "publication_year", "cited_by_count",
    "referenced_works", "authorships", "primary_location", "type",
    "counts_by_year", "abstract_inverted_index", "ids", "keywords", "language",
])
REF_FIELDS = "id,doi,title,publication_year,cited_by_count,authorships,referenced_works"


class QuotaExhausted(RuntimeError):
    pass


class OpenAlexError(RuntimeError):
    pass


class NotFound(OpenAlexError):
    """HTTP 404: the record does not exist, so the request is not retried."""


def short(wid: str) -> str:
    return wid.rsplit("/", 1)[-1]


def api_key() -> str | None:
    from .workspace import user_env

    return user_env("OPENALEX_API_KEY")


def _request(params: dict, timeout: int = 60, endpoint: str = "works") -> tuple[int, dict, dict]:
    url = (API if endpoint == "works" else API.rsplit("/", 1)[0] + "/" + endpoint) + "?" + urlencode(params)
    req = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=timeout, context=_context()) as resp:
            return resp.status, dict(resp.headers), json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:  # status codes are handled by the caller
        return exc.code, dict(exc.headers or {}), {}


_THROTTLE = threading.Lock()
_last_start = [0.0]
MIN_INTERVAL = 0.11  # seconds between request starts across threads (~9 requests/s)


def _throttle(sleep) -> None:
    """Space request starts so parallel callers (query-test batches) stay under the rate limit."""
    with _THROTTLE:
        wait = MIN_INTERVAL - (time.monotonic() - _last_start[0])
        if wait > 0:
            sleep(wait)
        _last_start[0] = time.monotonic()


def get(params: dict, tries: int = 8, sleep=time.sleep, endpoint: str = "works") -> dict:
    """GET one OpenAlex list endpoint ("works" by default; "sources" for journals)."""
    key = api_key()
    if key:
        params = {**params, "api_key": key}
    status = None
    for i in range(tries):
        _throttle(sleep)
        try:
            status, headers, body = _request(params) if endpoint == "works" else _request(params, endpoint=endpoint)
        except (URLError, TimeoutError, OSError):
            status, headers, body = None, {}, {}
        if status == 200:
            sleep(0.12)  # stay under ~10 requests/s
            return body
        if status == 404:
            raise NotFound(f"OpenAlex has no record at {endpoint}")
        if status == 429:
            wait = float(headers.get("Retry-After") or min(60, 2 ** (i + 1)))
            if wait > 120:
                raise QuotaExhausted(
                    f"OpenAlex daily quota exhausted; retry in about {wait/3600:.1f} h "
                    "(or set OPENALEX_API_KEY). Cached progress is kept, so rerunning resumes.")
            print(f"  rate-limited, waiting {wait:.0f}s", flush=True)
            sleep(wait)
        else:
            sleep(2 * (i + 1))
    raise OpenAlexError(f"OpenAlex request failed (HTTP {status}) after {tries} tries "
                        f"(filter={str(params.get('filter', ''))[:80]!r})")


def get_work(wid: str) -> dict:
    """One work from the entity endpoint (/works/<ID>), which also serves records the
    filter index has not caught up with yet; raises NotFound when there is none."""
    return get({}, endpoint=f"works/{short(wid)}")


def fetch_many(ids, fields: str = FIELDS, on_chunk=None, progress=None) -> dict:
    """Works by OpenAlex ID, 50 per request. on_chunk(out) every 20 requests; progress(done, total) after each."""
    out: dict = {}
    ids = sorted({short(i) for i in ids})
    for n, k in enumerate(range(0, len(ids), 50)):
        d = get({"filter": "openalex_id:" + "|".join(ids[k:k + 50]), "per-page": 50, "select": fields})
        for w in d["results"]:
            out[short(w["id"])] = w
        if progress:
            progress(min(k + 50, len(ids)), len(ids))
        if on_chunk and n % 20 == 19:
            on_chunk(out)
    return out


RECENT_SHARE = 0.5  # share of a capped list taken newest-first


def top_mixed(params: dict, limit: int) -> tuple[dict, int]:
    """Up to `limit` works for `params`: half most-cited, half newest; and the total hit count.

    A cap ranked by citations alone drops recent work, which has had no time to be cited.
    Newest works that are already in the cited half free their slots for the next most-cited.
    """
    if limit <= 0:
        return {}, 0
    n_recent = int(limit * RECENT_SHARE)
    n_cited = limit - n_recent
    per_page = min(200, limit)
    d = get({**params, "per-page": per_page, "sort": "cited_by_count:desc"})
    cited = d.get("results", [])
    total = d.get("meta", {}).get("count", len(cited))
    newest = get({**params, "per-page": per_page, "sort": "publication_date:desc"}).get("results", []) if n_recent else []
    out: dict = {}
    for w in cited[:n_cited]:
        out[short(w["id"])] = w
    for w in newest + cited[n_cited:]:
        if len(out) >= limit:
            break
        out.setdefault(short(w["id"]), w)
    return out, total


def fetch_citing(wid: str, limit: int | None = None) -> dict:
    """All citing works, or `limit` of them: half most-cited, half newest."""
    params = {"filter": f"cites:{short(wid)}", "select": FIELDS}
    if limit:
        return top_mixed(params, limit)[0]
    out, cursor = {}, "*"
    while cursor:
        d = get({**params, "per-page": 200, "cursor": cursor})
        for w in d["results"]:
            out[short(w["id"])] = w
        cursor = d["meta"].get("next_cursor")
        if not d["results"]:
            break
    return out


SPLIT_HINT = ("Windows PowerShell 5.1 drops the double quotes inside a quoted argument and splits it into words "
              "when it calls a native program, so one query arrives as several. Run lineage commands from Bash "
              "(Git Bash) on Windows, or write each inner double quote as \\\" in PowerShell.")


def check_query(q: str) -> str:
    if "," in q:
        raise ValueError("commas break OpenAlex filter syntax; use OR between terms instead")
    if q.count('"') % 2:
        raise ValueError(f"unbalanced double quote in query {q!r}. {SPLIT_HINT}")
    depth = 0
    for part in q.split('"')[::2]:  # parentheses outside "quoted phrases"
        for ch in part:
            depth += {"(": 1, ")": -1}.get(ch, 0)
            if depth < 0:
                break
        if depth < 0:
            break
    if depth:
        raise ValueError(f"unbalanced parentheses in query {q!r}. {SPLIT_HINT}")
    return q


def split_warning(queries: list, labels: list) -> str:
    """Several single-word queries with fewer labels than queries: the shell probably split one query."""
    bare = [q for q in queries if len(q.split()) == 1]
    if len(queries) >= 3 and len(bare) >= 2 and len(labels) < len(queries):
        return (f"warning: {len(queries)} queries ({len(bare)} of them single words) but {len(labels)} label(s); "
                f"if you meant fewer queries, the shell split them. {SPLIT_HINT}")
    return ""


def search(q: str, limit: int, select: str = FIELDS, prefer_relevance: bool = True) -> dict:
    """Title+abstract boolean search; most relevant first when OpenAlex allows it."""
    base = {"filter": f"title_and_abstract.search:{check_query(q)}", "per-page": min(200, limit), "select": select}
    if prefer_relevance:
        try:
            return get({**base, "sort": "relevance_score:desc"}, tries=2)
        except OpenAlexError:
            pass
    works, total = top_mixed({k: v for k, v in base.items() if k != "per-page"}, limit)
    return {"results": list(works.values()), "meta": {"count": total}}


def norm_doi(doi: str) -> str:
    """'https://doi.org/10.1103/X' / 'doi:10.1103/x' -> '10.1103/x' (DOIs are case-insensitive)."""
    d = doi.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
        if d.lower().startswith(prefix):
            d = d[len(prefix):]
    return d.lower()


def resolve_dois(dois) -> dict:
    """{normalised DOI: OpenAlex short ID} for the DOIs OpenAlex knows (50 per request)."""
    dois = sorted({norm_doi(d) for d in dois if d.strip()})
    out: dict = {}
    for k in range(0, len(dois), 50):
        chunk = [d for d in dois[k:k + 50] if "," not in d and "|" not in d]
        if not chunk:
            continue
        r = get({"filter": "doi:" + "|".join(chunk), "per-page": 50, "select": "id,doi"})
        for w in r.get("results", []):
            if w.get("doi"):
                out[norm_doi(w["doi"])] = short(w["id"])
    return out
