from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from scholarly_access_agent.core.urls import (
    any_domain_matches,
    build_proxy_url,
    host_for_url,
)
from scholarly_access_agent.providers.snu.domains import (
    current_domains,
    load_domains,
)


SNU_PROXY_BASE = "https://libproxy.snu.ac.kr/link.n2s?url="


@dataclass(frozen=True)
class SnuProxyProvider:
    # Read at construction, so a domain added with add_domain applies without restarting the server.
    domains: tuple[str, ...] = field(default_factory=lambda: current_domains())
    proxy_base: str = SNU_PROXY_BASE
    provider_id: str = "snu"

    @classmethod
    def from_domains_file(cls, path: Path) -> "SnuProxyProvider":
        return cls(domains=load_domains(path))

    def supports_url(self, url: str) -> bool:
        return any_domain_matches(host_for_url(url), self.domains)

    def proxied_url(self, url: str) -> str:
        return build_proxy_url(url, self.proxy_base)
