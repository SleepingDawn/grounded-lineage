"""Find a paper's versions and readable copies from its DOI without an LLM.

  scholarly-access-agent resolve <DOI | doi:... | https://doi.org/...> [--email ADDR] [--json]

Crossref gives the bibliographic record (venue type, publisher, PDF links, preprint
relations); Unpaywall gives the open copies; the DOI's landing host gives the publisher
route. Output is a ranked `routes` list: published open copy first, then the subscription
route when publisher policy allows it, then accepted manuscripts and preprints with a
suggested `preprint_fallback_reason`. Only the DOI (and the Unpaywall contact address,
a generic one by default) leaves the machine. One source failing never stops the others;
failures are listed under `errors`.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any, Callable
from urllib.parse import quote, unquote, urlparse
from urllib.request import Request, urlopen

from scholarly_access_agent.refs import DOI_RE, TYPE_TO_VENUE

CROSSREF = "https://api.crossref.org/works/"
UNPAYWALL = "https://api.unpaywall.org/v2/"
DEFAULT_EMAIL = "unpaywall-client@example.org"
USER_AGENT = "scholarly-access-agent resolve"
TIMEOUT = 20

ARXIV_DOI = re.compile(r"^10\.48550/arxiv\.(.+)$", re.I)
ARXIV_PATH = re.compile(r"/(?:abs|pdf|html)/([A-Za-z\-.]+/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?", re.I)
HANDLE_PATH = re.compile(r"/handle/(\d+(?:\.\d+)*)/([^/?#]+)")
PMC_HOSTS = {"pmc.ncbi.nlm.nih.gov", "www.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov", "europepmc.org"}
POLICY_BLOCKED = "open copy only (publisher AI-use limits)"
BOT_CHECK = "bot check seen 2026-11; prefer a published open copy"
VERSION_RANK = {"publishedVersion": 0, "acceptedVersion": 1, "submittedVersion": 2}

FetchJson = Callable[[str], Any]
Landing = Callable[[str], str]


def normalize_doi(text: str) -> str:
    value = unquote(text.strip())
    value = re.sub(r"^doi:\s*", "", value, flags=re.I)
    match = DOI_RE.search(value)
    if not match:
        raise ValueError(f"Not a DOI: {text!r}")
    return match.group(0).rstrip(".,;)")


def fetch_json(url: str, timeout: int = TIMEOUT) -> Any:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def landing_url(doi: str) -> str:
    from scholarly_access_agent.runtime.pdf import resolve_doi_url

    return resolve_doi_url("https://doi.org/" + doi, timeout_seconds=TIMEOUT)


def _host(url: str | None) -> str:
    host = (urlparse(url or "").hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _in_domains(url: str | None, domains: tuple[str, ...]) -> bool | None:
    from scholarly_access_agent.core.urls import any_domain_matches

    host = _host(url)
    return any_domain_matches(host, domains) if host else None


def arxiv_from(value: str | None) -> str | None:
    if not value:
        return None
    value = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value.strip(), flags=re.I)
    match = ARXIV_DOI.match(value)
    if match:
        return match.group(1)
    if _host(value).endswith("arxiv.org"):
        found = ARXIV_PATH.search(urlparse(value).path.removesuffix(".pdf"))
        return found.group(1) if found else None
    if re.fullmatch(r"\d{4}\.\d{4,5}(v\d+)?|[A-Za-z\-.]+/\d{7}", value.strip()):
        return re.sub(r"v\d+$", "", value.strip())
    return None


# ---------------------------------------------------------------------------
# Sources


def parse_crossref(message: dict) -> dict[str, Any]:
    authors = message.get("author") or []
    first = authors[0] if authors and isinstance(authors[0], dict) else {}
    issued = (message.get("issued") or message.get("published") or {}).get("date-parts") or [[None]]
    year = issued[0][0] if issued and issued[0] else None
    ctype = message.get("type") or ""
    links = [
        {"url": link.get("URL"), "content_type": link.get("content-type"),
         "intended_application": link.get("intended-application")}
        for link in message.get("link") or [] if isinstance(link, dict) and link.get("URL")
    ]
    relations: dict[str, list[str]] = {}
    preprints: list[str] = []
    for kind in ("has-preprint", "is-preprint-of"):
        for item in (message.get("relation") or {}).get(kind) or []:
            ident = str(item.get("id", ""))
            relations.setdefault(kind, []).append(ident)
            found = arxiv_from(ident)
            if kind == "has-preprint" and found:
                preprints.append(found)
    return {
        "title": (message.get("title") or [""])[0],
        "first_author": " ".join(filter(None, [first.get("given"), first.get("family")])) or first.get("name", ""),
        "first_author_family": first.get("family", ""),
        "year": year,
        "container": (message.get("container-title") or [""])[0],
        "type": ctype,
        "venue_type": TYPE_TO_VENUE.get(ctype, ctype or None),
        "publisher": message.get("publisher", ""),
        "landing_url": ((message.get("resource") or {}).get("primary") or {}).get("URL"),
        "pdf_links": [link for link in links if "pdf" in str(link["content_type"]).lower()
                      or link["url"].lower().split("?")[0].endswith(".pdf")],
        "relations": relations,
        "arxiv_ids": preprints,
    }


def parse_unpaywall(data: dict) -> dict[str, Any]:
    locations = []
    for loc in data.get("oa_locations") or []:
        if not isinstance(loc, dict):
            continue
        locations.append({
            "host_type": loc.get("host_type"), "version": loc.get("version"),
            "license": loc.get("license"), "url_for_pdf": loc.get("url_for_pdf"),
            "url": loc.get("url") or loc.get("url_for_landing_page") or loc.get("url_for_pdf"),
            "repository_institution": loc.get("repository_institution"),
        })
    best = next((i for i, loc in enumerate(locations) if loc["version"] == "publishedVersion"), None)
    for i, loc in enumerate(locations):
        loc["best_published"] = i == best
    return {"is_oa": data.get("is_oa"), "oa_status": data.get("oa_status"), "locations": locations}


def dspace_bitstream(handle_url: str, fetch: FetchJson) -> str | None:
    """Handle page -> item -> ORIGINAL bundle -> first (PDF) bitstream content link (DSpace 7 REST)."""
    parsed = urlparse(handle_url)
    match = HANDLE_PATH.search(parsed.path)
    if not match:
        return None
    base = f"{parsed.scheme}://{parsed.netloc}"
    item = fetch(f"{base}/server/api/pid/find?id={match.group(1)}/{match.group(2)}")
    bundles_href = (((item or {}).get("_links") or {}).get("bundles") or {}).get("href")
    if not bundles_href:
        return None
    bundles = ((fetch(bundles_href) or {}).get("_embedded") or {}).get("bundles") or []
    original = next((b for b in bundles if str(b.get("name", "")).upper() == "ORIGINAL"), None)
    href = (((original or {}).get("_links") or {}).get("bitstreams") or {}).get("href")
    if not href:
        return None
    streams = ((fetch(href) or {}).get("_embedded") or {}).get("bitstreams") or []
    streams = sorted(streams, key=lambda s: not str(s.get("name", "")).lower().endswith(".pdf"))
    for stream in streams:
        content = ((stream.get("_links") or {}).get("content") or {}).get("href")
        if content:
            return content
    return None


# ---------------------------------------------------------------------------
# Routes


def publisher_hint(url: str | None, domains: tuple[str, ...]) -> dict[str, Any]:
    host = _host(url)
    if not host or host.endswith("doi.org"):
        return {"note": "publisher landing page not resolved"}
    if host == "journals.aps.org":
        return {"tool": "download_pdf", "url": url, "note": "download_pdf fetches the APS PDF endpoint first"}
    if any(h in host for h in ("sciencedirect.com", "elsevier.com")) or host.endswith(("springer.com", "nature.com")):
        return {"policy": POLICY_BLOCKED}
    if host in ("pubs.aip.org", "pubs.acs.org"):
        return {"tool": "download_pdf", "url": url, "note": BOT_CHECK}
    if host.endswith("arxiv.org"):
        found = arxiv_from(url)
        return {"tool": "read_url", "url": f"https://arxiv.org/abs/{found}" if found else url}
    if host in PMC_HOSTS:
        return {"tool": "read_url", "url": url}
    if _in_domains(url, domains):
        return {"tool": "download_pdf", "url": url}
    return {"note": "host not in the snu-library domain list; needs add_domain (user approval)"}


def open_copy_route(loc: dict, fetch: FetchJson, domains: tuple[str, ...], errors: dict) -> dict[str, Any]:
    url, pdf = loc.get("url"), loc.get("url_for_pdf")
    route: dict[str, Any] = {key: loc.get(key) for key in ("version", "host_type", "license", "repository_institution")}
    route["source"] = "unpaywall"
    found = arxiv_from(url) or arxiv_from(pdf)
    if found:
        return {**route, "tool": "read_url", "url": f"https://arxiv.org/abs/{found}", "arxiv_id": found}
    if _host(url) in PMC_HOSTS:
        return {**route, "tool": "read_url", "url": url}
    from scholarly_access_agent.runtime.public import is_public_url

    handle = next((u for u in (url, pdf) if u and HANDLE_PATH.search(urlparse(u).path)), None)
    if handle and (not pdf or HANDLE_PATH.search(urlparse(pdf).path) and "/bitstream" not in pdf):
        try:
            content = dspace_bitstream(handle, fetch)
        except Exception as exc:  # one repository failing must not stop the rest
            content = None
            errors[f"dspace:{_host(handle)}"] = type(exc).__name__
        route.update(tool="download_pdf", url=handle, pdf_url=content or pdf, dspace=True)
        if not content:
            route["note"] = "DSpace bitstream not found; open the handle page"
    else:
        route.update(tool="download_pdf", url=url or pdf, pdf_url=pdf)
    if route.get("pdf_url") is None:
        route.pop("pdf_url", None)
    target = route.get("pdf_url") or route["url"]
    if target and is_public_url(target):
        route["direct_fetch"] = True
    elif _host(route["url"]).endswith("doi.org"):
        route["note"] = "repository DOI link: resolve it to the repository page first"
    else:
        inside = _in_domains(route["url"], domains)
        route["in_snu_domains"] = inside
        if inside is False:
            route["note"] = (route.get("note", "") + "; " if route.get("note") else "") + \
                "host not in the snu-library domain list; needs add_domain (user approval)"
    return route


def fallback_reason(published_open: bool, subscription: dict | None) -> str:
    if published_open:
        return "supplement only: the journal version has an open copy; read it first"
    if subscription and subscription.get("tool"):
        return "use only if the subscription route fails; record which (access_restricted or retrieval error)"
    if subscription and subscription.get("policy"):
        return "journal version access-restricted for AI use (publisher policy); no open published copy"
    return "journal version unavailable: no open published copy and no usable subscription route"


def build_routes(crossref: dict | None, unpaywall: dict | None, landing: str | None,
                 fetch: FetchJson, domains: tuple[str, ...], errors: dict,
                 arxiv_ids: list[str] | None = None) -> list[dict[str, Any]]:
    locations = (unpaywall or {}).get("locations") or []
    opened = [open_copy_route(loc, fetch, domains, errors) for loc in locations]
    published = [r for r in opened if r.get("version") == "publishedVersion" and not r.get("arxiv_id")]
    published.sort(key=lambda r: r.get("host_type") != "repository")  # repository first, stable otherwise
    for route in published:
        route["kind"] = "published_open"

    routes: list[dict[str, Any]] = list(published)
    subscription = None
    if landing or (crossref or {}).get("landing_url"):
        hint = publisher_hint(landing or crossref["landing_url"], domains)
        kind = "landing_open" if hint.get("tool") == "read_url" else "subscription"
        subscription = {"kind": kind, "version": "publishedVersion", "source": "landing",
                        "landing_url": landing or crossref["landing_url"], **hint}
        if hint.get("tool"):
            routes.append(subscription)

    reason = fallback_reason(bool(published), subscription)
    rest = [r for r in opened if all(r is not p for p in published)]
    rest.sort(key=lambda r: (bool(r.get("arxiv_id")), VERSION_RANK.get(r.get("version") or "", 3)))
    seen_arxiv = {r.get("arxiv_id") for r in rest if r.get("arxiv_id")}
    for found in (arxiv_ids or []) + ((crossref or {}).get("arxiv_ids") or []):
        if found not in seen_arxiv:
            seen_arxiv.add(found)
            rest.append({"version": "submittedVersion", "source": "crossref relation", "arxiv_id": found,
                         "tool": "read_url", "url": f"https://arxiv.org/abs/{found}"})
    kinds = {"acceptedVersion": "accepted_manuscript", "submittedVersion": "preprint"}
    for route in rest:
        route["kind"] = "preprint" if route.get("arxiv_id") else kinds.get(route.get("version"), "other_open_copy")
        route["preprint_fallback_reason"] = reason
        routes.append(route)
    if subscription and all(subscription is not r for r in routes):
        if subscription.get("policy"):
            if not published:  # a blocked subscription route matters only when no published copy is open
                routes.append({**subscription, "kind": "subscription_blocked"})
        else:
            routes.append({**subscription, "kind": "subscription_unavailable"})
    unique: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    for route in routes:  # Unpaywall often lists the same arXiv/repository copy several times
        key = (route.get("tool"), route.get("url") or route.get("landing_url"), route.get("pdf_url"))
        if key not in seen:
            seen.add(key)
            unique.append(route)
    routes = unique
    for rank, route in enumerate(routes, 1):
        route["rank"] = rank
    return routes


def resolve(doi_text: str, *, email: str = DEFAULT_EMAIL, fetch: FetchJson = fetch_json,
            landing: Landing = landing_url, domains: tuple[str, ...] | None = None) -> dict[str, Any]:
    doi = normalize_doi(doi_text)
    if domains is None:
        from scholarly_access_agent.providers.snu.domains import current_domains
        domains = current_domains()
    errors: dict[str, str] = {}
    crossref = unpaywall = None
    try:
        message = fetch(CROSSREF + quote(doi, safe="/"))
        crossref = parse_crossref(message.get("message", message) if isinstance(message, dict) else {})
    except Exception as exc:
        errors["crossref"] = type(exc).__name__
    try:
        unpaywall = parse_unpaywall(fetch(f"{UNPAYWALL}{quote(doi, safe='/')}?email={quote(email)}") or {})
    except Exception as exc:
        errors["unpaywall"] = type(exc).__name__
    resolved = None
    try:
        resolved = landing(doi)
        if _host(resolved).endswith("doi.org"):
            errors["landing"] = "unresolved"
            resolved = None
    except Exception as exc:
        errors["landing"] = type(exc).__name__
    own_arxiv = arxiv_from(doi)  # an arXiv DOI (DataCite): Crossref has no record for it
    routes = build_routes(crossref, unpaywall, resolved, fetch, domains, errors,
                          [own_arxiv] if own_arxiv else None)
    return {"ok": crossref is not None or unpaywall is not None or bool(routes), "doi": doi, "landing_url": resolved,
            "crossref": crossref, "unpaywall": unpaywall, "routes": routes, "errors": errors}


def format_table(result: dict[str, Any]) -> str:
    cr = result.get("crossref") or {}
    lines = [f"DOI {result['doi']}"]
    if cr:
        lines.append(f"{cr.get('first_author_family') or cr.get('first_author')} ({cr.get('year')}) "
                     f"{cr.get('title', '')[:90]}")
        lines.append(f"{cr.get('container') or '-'} | venue_type {cr.get('venue_type')} | {cr.get('publisher') or '-'}")
    lines.append(f"{'#':<3}{'kind':<24}{'version':<18}{'tool':<14}url / note")
    for route in result["routes"]:
        target = route.get("url") or route.get("landing_url") or ""
        extra = [route[k] for k in ("policy", "note") if route.get(k)]
        if route.get("pdf_url"):
            extra.insert(0, "pdf " + route["pdf_url"])
        if route.get("preprint_fallback_reason"):
            extra.append("fallback: " + route["preprint_fallback_reason"])
        lines.append(f"{route['rank']:<3}{route['kind']:<24}{str(route.get('version') or '-'):<18}"
                     f"{str(route.get('tool') or '-'):<14}{target}")
        lines.extend("     " + item for item in extra)
    if not result["routes"]:
        lines.append("   (no routes found)")
    if result["errors"]:
        lines.append("errors: " + ", ".join(f"{k}={v}" for k, v in result["errors"].items()))
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="scholarly-access-agent resolve", description=__doc__.split("\n\n")[0])
    ap.add_argument("doi", help="DOI, doi:10.x/..., or https://doi.org/10.x/...")
    ap.add_argument("--email", default=DEFAULT_EMAIL, help="Unpaywall contact address (default: a generic one)")
    ap.add_argument("--json", action="store_true", help="print the full JSON result")
    args = ap.parse_args(argv)
    try:
        result = resolve(args.doi, email=args.email)
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}) if args.json else str(exc))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=1) if args.json else format_table(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
