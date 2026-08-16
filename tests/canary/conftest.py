"""Fixtures for the upstream-version canary tier.

The canary tests hit docs.paloaltonetworks.com directly to catch the case
where Palo Alto releases a new major version but the crawler's hard-coded
candidate_versions list doesn't know about it.

These tests are explicitly off by default (marker ``canary`` is excluded
in pyproject.toml addopts) and are designed to tolerate network flakes:
each probe retries a few times and the network errors are reported
distinctly from "URL 404-ed" errors.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass

import pytest

DOCS_BASE = "https://docs.paloaltonetworks.com"
REQUEST_TIMEOUT = 15  # seconds
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 2.0


@dataclass
class ProbeResult:
    url: str
    status: int | None
    error: str | None

    @property
    def exists(self) -> bool:
        return self.status is not None and 200 <= self.status < 400

    @property
    def was_network_error(self) -> bool:
        return self.status is None


def _probe_url(path: str) -> ProbeResult:
    """HTTP GET a URL with retries. Returns status code or error.

    We use GET rather than HEAD because some CDNs mishandle HEAD requests
    against SPA routes and return 404 for URLs that actually exist.
    """
    url = f"{DOCS_BASE}{path}"
    last_error: str | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "bugdb-canary/1.0"})
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                return ProbeResult(url=url, status=resp.status, error=None)
        except urllib.error.HTTPError as e:
            # HTTP 4xx/5xx is a real answer — return it, don't retry.
            return ProbeResult(url=url, status=e.code, error=None)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_error = f"{type(e).__name__}: {e}"
            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(BACKOFF_SECONDS * (2**attempt))
    return ProbeResult(url=url, status=None, error=last_error)


@pytest.fixture(scope="session")
def probe() -> callable:
    """Return the URL-probe helper so tests can call it directly."""
    return _probe_url


@pytest.fixture(scope="session")
def live_sitemap():
    """Parsed docs.paloaltonetworks.com sitemap, or skip on network failure.

    Session-scoped: the sitemap is ~4.5 MB, fetch it once per run.
    """
    from bugdb.sitemap import SitemapIndex

    last_error: str | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            req = urllib.request.Request(
                f"{DOCS_BASE}/sitemap.xml", headers={"User-Agent": "bugdb-canary/1.0"}
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                return SitemapIndex.from_xml(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_error = f"{type(e).__name__}: {e}"
            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(BACKOFF_SECONDS * (2**attempt))
    pytest.skip(f"could not fetch sitemap: {last_error}")
