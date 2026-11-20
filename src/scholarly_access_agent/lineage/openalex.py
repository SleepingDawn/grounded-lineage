"""Minimal OpenAlex client for the lineage workflow (stdlib only).

- OPENALEX_API_KEY is read from the environment and, on Windows, from the saved user
  variable, so a key saved after the client started is still picked up.
- The key never appears in error messages: failures report status and filter only.
- A long Retry-After means the daily budget is spent; QuotaExhausted is raised instead of
  sleeping for hours. Callers keep their caches, so rerunning resumes.
"""
from __future__ import annotations

import json
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
    "counts_by_year", "abstract_inverted_index", "ids", "keywords",
])
REF_FIELDS = "id,doi,title,publication_year,cited_by_count,authorships,referenced_works"


class QuotaExhausted(RuntimeError):
    pass


class OpenAlexError(RuntimeError):
    pass


def short(wid: str) -> str:
    return wid.rsplit("/", 1)[-1]


def api_key() -> str | None:
    from .workspace import user_env

    return user_env("OPENALEX_API_KEY")


def _request(params: dict, timeout: int = 60) -> tuple[int, dict, dict]:
    url = API + "?" + urlencode(params)
    req = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=timeout, context=_context()) as resp:
            return resp.status, dict(resp.headers), json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:  # status codes are handled by the caller
        return exc.code, dict(exc.headers or {}), {}


def get(params: dict, tries: int = 8, sleep=time.sleep) -> dict:
    key = api_key()
    if key:
        params = {**params, "api_key": key}
    status = None
    for i in range(tries):
        try:
            status, headers, body = _request(params)
        except (URLError, TimeoutError, OSError):
            status, headers, body = None, {}, {}
        if status == 200:
            sleep(0.12)  # stay under ~10 requests/s
            return body
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


def fetch_many(ids, fields: str = FIELDS, on_chunk=None) -> dict:
    out: dict = {}
    ids = sorted({short(i) for i in ids})
    for n, k in enumerate(range(0, len(ids), 50)):
        d = get({"filter": "openalex_id:" + "|".join(ids[k:k + 50]), "per-page": 50, "select": fields})
        for w in d["results"]:
            out[short(w["id"])] = w
        if on_chunk and n % 20 == 19:
            on_chunk(out)
    return out


def fetch_citing(wid: str, limit: int | None = None) -> dict:
    """All citing works, or only the `limit` most-cited ones."""
    params = {"filter": f"cites:{short(wid)}", "select": FIELDS}
    if limit:
        d = get({**params, "per-page": min(200, limit), "sort": "cited_by_count:desc"})
        return {short(w["id"]): w for w in d["results"][:limit]}
    out, cursor = {}, "*"
    while cursor:
        d = get({**params, "per-page": 200, "cursor": cursor})
        for w in d["results"]:
            out[short(w["id"])] = w
        cursor = d["meta"].get("next_cursor")
        if not d["results"]:
            break
    return out


def check_query(q: str) -> str:
    if "," in q:
        raise ValueError("commas break OpenAlex filter syntax; use OR between terms instead")
    return q


def search(q: str, limit: int, select: str = FIELDS, prefer_relevance: bool = True) -> dict:
    """Title+abstract boolean search; most relevant first when OpenAlex allows it."""
    base = {"filter": f"title_and_abstract.search:{check_query(q)}", "per-page": min(200, limit), "select": select}
    if prefer_relevance:
        try:
            return get({**base, "sort": "relevance_score:desc"}, tries=2)
        except OpenAlexError:
            pass
    return get({**base, "sort": "cited_by_count:desc"})
