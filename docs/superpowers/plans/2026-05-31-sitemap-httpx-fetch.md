# Sitemap-driven httpx fetch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Playwright-based `bugdb fetch` pipeline with an `httpx`-based one driven by `sitemap.xml`, persist a manifest so weekly CI runs only refetch URLs whose `<lastmod>` changed, and switch Cortex XDR from shadow-DOM scraping to the FluidTopics `khub` JSON API.

**Architecture:** A small `Transport` layer abstracts page fetching. `HttpxDocsTransport` covers `docs.paloaltonetworks.com` (raw HTML + the `<div style="display:inline">` foster-parenting unwrap fix). `FluidTopicsTransport` covers `docs-cortex.paloaltonetworks.com` via `/api/khub/`. A new `SitemapIndex` module parses `sitemap.xml` once per run, routes URLs to product IDs, and exposes `<lastmod>` so the existing crawlers can skip unchanged URLs. A `FetchManifest` JSON file (sibling of `bugdb.json`) persists the last-seen `<lastmod>` per URL so weekly CI fetches do O(changed-pages) work instead of O(all-pages).

**Tech Stack:** Python 3.12, `httpx[http2]`, `lxml`, `beautifulsoup4`, `pydantic`, `pytest`, `pytest-asyncio`, `respx` (HTTP mocking).

**Out of scope for this plan:** Removing Playwright entirely from `pyproject.toml` (we keep it as a fallback transport behind a CLI flag until parity is fully proven). Site builder changes. Release-notes generation.

**Reference report:** `docs/perf-exploration.md` — measured numbers, raw evidence for every claim below.

---

## File Structure

**Create:**
- `src/bugdb/transport/__init__.py` — `Transport` protocol + factory.
- `src/bugdb/transport/base.py` — `Transport` protocol, `FetchedPage` dataclass.
- `src/bugdb/transport/httpx_transport.py` — `HttpxDocsTransport` (httpx HTTP/2 + redirects + unwrap fix + global backoff + retries).
- `src/bugdb/transport/fluidtopics_transport.py` — `FluidTopicsTransport` (khub API client + topic-tree walk → synthetic HTML for the existing parser).
- `src/bugdb/transport/playwright_transport.py` — thin wrapper over the *current* `BaseCrawler` browser logic, kept as a feature-flagged fallback (`--use-browser`).
- `src/bugdb/sitemap.py` — `SitemapIndex` (parse `sitemap.xml`, classify URLs by product, expose `<lastmod>`).
- `src/bugdb/fetch_manifest.py` — `FetchManifest` Pydantic model + JSON load/save + `should_skip(url, lastmod)`.
- `tests/fixtures/sitemap-sample.xml` — minimal sitemap fixture for tests.
- `tests/fixtures/inline-div-table.html` — minimal AEM table with the inline-`<div>` quirk.
- `tests/fixtures/fluidtopics/maps.json`, `topics.json`, `content-addressed-issues.html` — recorded responses for unit tests.
- `tests/test_transport_httpx.py`
- `tests/test_transport_fluidtopics.py`
- `tests/test_sitemap.py`
- `tests/test_fetch_manifest.py`
- `scripts/parity_check.py` — load old `bugdb.json` (committed copy) vs new run, diff per-product/per-version issue counts, exit non-zero if new is materially lower.

**Modify:**
- `src/bugdb/crawlers/base.py`
  - Replace direct Playwright use with a `Transport` instance injected via constructor.
  - Add `Transport`-agnostic `_fetch_html(url)` and `_fetch_topic_tree(map_id)` methods.
  - Add the `<div style="display: inline">` unwrap step inside `_parse_issues_page` before tables are extracted.
- `src/bugdb/crawlers/products/panos.py`
  - `discover_versions` and `discover_version_pages` driven by `SitemapIndex` instead of probing URLs.
- `src/bugdb/crawlers/products/plugins.py`
  - `discover_versions` driven by `SitemapIndex` where the index page no longer needs JS-rendered navigation.
- `src/bugdb/crawlers/products/cortex_xdr.py`
  - Replace `_fetch_cortex_page_with_semaphore` with `FluidTopicsTransport` traversal.
- `src/bugdb/crawlers/registry.py`
  - Each `_crawl_*_async` accepts an optional `transport_factory` and `sitemap` argument so the CLI can build one shared instance per run.
- `src/bugdb/cli.py`
  - `fetch` builds a single `SitemapIndex` and `FetchManifest`, passes them to crawlers, writes the manifest back on success.
  - New flag: `--use-browser` (default `False`) keeps the Playwright path available as escape hatch.
  - New flag: `--no-manifest` (default `False`) disables manifest read/write for debugging.
- `pyproject.toml`
  - Add `httpx[http2]>=0.27`, `respx>=0.21` (test dep).
  - Leave `playwright` as a runtime dep until the next PR.

**Delete:** Nothing yet. After parity, a follow-up PR can remove the shadow-DOM helpers and the Playwright dep.

---

## Phase 1 — Tests-first scaffolding for the new modules

### Task 1: `Transport` protocol + `FetchedPage` dataclass

**Files:**
- Create: `src/bugdb/transport/__init__.py`
- Create: `src/bugdb/transport/base.py`
- Create: `tests/test_transport_base.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_transport_base.py
from bugdb.transport.base import FetchedPage, Transport


def test_fetched_page_holds_url_status_and_html():
    p = FetchedPage(url="https://x/y", status_code=200, html="<table></table>", lastmod=None)
    assert p.url == "https://x/y"
    assert p.status_code == 200
    assert p.html == "<table></table>"
    assert p.lastmod is None


def test_transport_protocol_requires_fetch_and_close():
    # Protocol has the expected methods
    assert hasattr(Transport, "fetch")
    assert hasattr(Transport, "aclose")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_transport_base.py -v`
Expected: `ModuleNotFoundError: No module named 'bugdb.transport'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/bugdb/transport/__init__.py
from bugdb.transport.base import FetchedPage, Transport

__all__ = ["FetchedPage", "Transport"]
```

```python
# src/bugdb/transport/base.py
"""Transport protocol for fetching release-notes pages."""

from dataclasses import dataclass
from typing import Optional, Protocol


@dataclass(frozen=True)
class FetchedPage:
    """Result of a single page fetch.

    `html` is always a serialized HTML string the existing BeautifulSoup-based
    parsers can consume. `lastmod` is the sitemap timestamp if known (None for
    transports that don't carry one, e.g. FluidTopics topic content).
    """

    url: str
    status_code: int
    html: str
    lastmod: Optional[str] = None


class Transport(Protocol):
    """Async fetch transport for release-notes pages."""

    async def fetch(self, url: str) -> FetchedPage:
        """Fetch a single URL and return the page."""

    async def aclose(self) -> None:
        """Release any held resources (connections, browser, etc.)."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_transport_base.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/bugdb/transport/ tests/test_transport_base.py
git commit -m "feat(transport): add Transport protocol and FetchedPage dataclass"
```

---

### Task 2: `HttpxDocsTransport` — happy path

**Files:**
- Create: `src/bugdb/transport/httpx_transport.py`
- Create: `tests/test_transport_httpx.py`
- Create: `tests/fixtures/inline-div-table.html`

- [ ] **Step 1: Add `respx` and `httpx[http2]` to test deps and install**

```bash
uv add 'httpx[http2]>=0.27'
uv add --dev 'respx>=0.21'
uv sync
```

- [ ] **Step 2: Write a minimal fixture that reproduces the AEM quirk**

```html
<!-- tests/fixtures/inline-div-table.html -->
<!DOCTYPE html>
<html><body>
<table class="table">
  <thead><tr><th>Issue ID</th><th>Description</th></tr></thead>
  <tbody class="tbody"><div style="display: inline;">
    <tr class="row"><div style="display: inline;">
      <td><div class="p"><b>PAN-1</b></div></td>
      <td><div class="p">Description one.</div></td>
    </div></tr>
    <tr class="row"><div style="display: inline;">
      <td><div class="p"><b>PAN-2</b></div></td>
      <td><div class="p">Description two.</div></td>
    </div></tr>
  </div></tbody>
</table>
</body></html>
```

- [ ] **Step 3: Write the failing tests**

```python
# tests/test_transport_httpx.py
from pathlib import Path

import httpx
import pytest
import respx

from bugdb.transport.httpx_transport import HttpxDocsTransport

FIXTURE = (Path(__file__).parent / "fixtures" / "inline-div-table.html").read_text()


@pytest.mark.asyncio
@respx.mock
async def test_fetch_returns_html_for_200():
    respx.get("https://docs.paloaltonetworks.com/page").mock(
        return_value=httpx.Response(200, text="<html><body>ok</body></html>")
    )
    async with HttpxDocsTransport(concurrency=2) as t:
        page = await t.fetch("https://docs.paloaltonetworks.com/page")
    assert page.status_code == 200
    assert "ok" in page.html


@pytest.mark.asyncio
@respx.mock
async def test_fetch_unwraps_inline_div_inside_tables():
    respx.get("https://docs.paloaltonetworks.com/issues").mock(
        return_value=httpx.Response(200, text=FIXTURE)
    )
    async with HttpxDocsTransport(concurrency=2) as t:
        page = await t.fetch("https://docs.paloaltonetworks.com/issues")
    # After unwrap, tbody contains <tr> directly, parseable by lxml without
    # a browser. We assert the *output* HTML no longer has the inline-div
    # marker between tbody/tr.
    assert "<tbody" in page.html
    assert 'style="display: inline"' not in page.html.lower().replace(" ", "")
    # And BS4 with recursive=False now sees the rows.
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(page.html, "lxml")
    tbody = soup.find("tbody")
    assert tbody is not None
    assert len(tbody.find_all("tr", recursive=False)) == 2


@pytest.mark.asyncio
@respx.mock
async def test_fetch_propagates_404():
    respx.get("https://docs.paloaltonetworks.com/missing").mock(
        return_value=httpx.Response(404, text="not found")
    )
    async with HttpxDocsTransport(concurrency=2) as t:
        page = await t.fetch("https://docs.paloaltonetworks.com/missing")
    assert page.status_code == 404


@pytest.mark.asyncio
@respx.mock
async def test_fetch_retries_on_5xx():
    route = respx.get("https://docs.paloaltonetworks.com/flaky").mock(
        side_effect=[
            httpx.Response(503, text="busy"),
            httpx.Response(200, text="ok"),
        ]
    )
    async with HttpxDocsTransport(concurrency=2, max_retries=3, retry_base_delay=0.01) as t:
        page = await t.fetch("https://docs.paloaltonetworks.com/flaky")
    assert page.status_code == 200
    assert route.call_count == 2
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `uv run pytest tests/test_transport_httpx.py -v`
Expected: `ModuleNotFoundError: No module named 'bugdb.transport.httpx_transport'`

- [ ] **Step 5: Implement `HttpxDocsTransport`**

```python
# src/bugdb/transport/httpx_transport.py
"""HTTP transport for docs.paloaltonetworks.com using httpx."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from bugdb.transport.base import FetchedPage

logger = logging.getLogger(__name__)

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; bugdb/1.0; +https://dependencyhell.net/bugdb)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
}

# Status codes worth retrying. 408 = request timeout, 429 = rate limit.
_RETRY_STATUS = {408, 429, 500, 502, 503, 504}


class HttpxDocsTransport:
    """Transport implementation backed by httpx with the inline-div unwrap fix.

    `docs.paloaltonetworks.com` serves issue pages where the table body is
    wrapped in `<div style="display: inline">`. Real browsers move the div
    out via HTML5 foster-parenting; lxml does not, which breaks
    `tbody.find_all('tr', recursive=False)`. We unwrap those divs in-place
    before handing the HTML to the existing parsers.
    """

    def __init__(
        self,
        *,
        concurrency: int = 15,
        max_retries: int = 3,
        retry_base_delay: float = 1.0,
        timeout: float = 20.0,
    ) -> None:
        limits = httpx.Limits(max_keepalive_connections=concurrency,
                              max_connections=concurrency + 5)
        self._client = httpx.AsyncClient(
            http2=True,
            follow_redirects=True,
            headers=_DEFAULT_HEADERS,
            limits=limits,
            timeout=timeout,
        )
        self._sem = asyncio.Semaphore(concurrency)
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay

    async def __aenter__(self) -> "HttpxDocsTransport":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def fetch(self, url: str) -> FetchedPage:
        async with self._sem:
            last_exc: Optional[Exception] = None
            for attempt in range(self._max_retries):
                try:
                    resp = await self._client.get(url)
                except httpx.HTTPError as exc:
                    last_exc = exc
                    await self._sleep_backoff(attempt)
                    continue
                if resp.status_code in _RETRY_STATUS and attempt < self._max_retries - 1:
                    logger.info("retrying %s after %s", url, resp.status_code)
                    await self._sleep_backoff(attempt)
                    continue
                html = _fix_inline_div_tables(resp.text)
                return FetchedPage(
                    url=str(resp.url),
                    status_code=resp.status_code,
                    html=html,
                )
            if last_exc is not None:
                raise last_exc
            return FetchedPage(url=url, status_code=resp.status_code, html=resp.text)

    async def _sleep_backoff(self, attempt: int) -> None:
        await asyncio.sleep(self._retry_base_delay * (2 ** attempt))


def _fix_inline_div_tables(html: str) -> str:
    """Unwrap `<div style="display: inline">` elements inside `<table>`.

    See class docstring for rationale.
    """
    if 'display: inline' not in html and 'display:inline' not in html:
        return html
    soup = BeautifulSoup(html, "lxml")
    changed = False
    for div in soup.select(
        'table div[style*="display: inline"], table div[style*="display:inline"]'
    ):
        div.unwrap()
        changed = True
    if not changed:
        return html
    return str(soup)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_transport_httpx.py -v`
Expected: all 4 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add src/bugdb/transport/httpx_transport.py tests/test_transport_httpx.py \
        tests/fixtures/inline-div-table.html pyproject.toml uv.lock
git commit -m "feat(transport): add HttpxDocsTransport with inline-div unwrap fix"
```

---

### Task 3: `SitemapIndex` — parse, classify, expose `<lastmod>`

**Files:**
- Create: `src/bugdb/sitemap.py`
- Create: `tests/test_sitemap.py`
- Create: `tests/fixtures/sitemap-sample.xml`

- [ ] **Step 1: Write the fixture**

```xml
<!-- tests/fixtures/sitemap-sample.xml -->
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://docs.paloaltonetworks.com/pan-os/11-2/pan-os-release-notes/pan-os-11-2-3-known-and-addressed-issues/pan-os-11-2-3-known-issues</loc>
    <lastmod>2026-03-01</lastmod>
  </url>
  <url>
    <loc>https://docs.paloaltonetworks.com/pan-os/11-2/pan-os-release-notes/pan-os-11-2-3-known-and-addressed-issues/pan-os-11-2-3-addressed-issues</loc>
    <lastmod>2026-03-01</lastmod>
  </url>
  <url>
    <loc>https://docs.paloaltonetworks.com/globalprotect/6-2/globalprotect-app-release-notes/globalprotect-app-6-2-known-and-addressed-issues/globalprotect-app-6-2-8-known-and-addressed-issues</loc>
    <lastmod>2026-04-15</lastmod>
  </url>
  <url>
    <loc>https://docs.paloaltonetworks.com/pan-os/11-2/pan-os-release-notes/features-introduced-in-pan-os</loc>
    <lastmod>2026-02-01</lastmod>
  </url>
</urlset>
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_sitemap.py
from pathlib import Path

from bugdb.sitemap import SitemapEntry, SitemapIndex

FIXTURE = Path(__file__).parent / "fixtures" / "sitemap-sample.xml"


def test_parse_extracts_all_entries():
    idx = SitemapIndex.from_xml(FIXTURE.read_text())
    assert len(idx.all_entries()) == 4


def test_issue_urls_filters_only_known_or_addressed_pages():
    idx = SitemapIndex.from_xml(FIXTURE.read_text())
    urls = {e.url for e in idx.issue_urls()}
    assert any("pan-os-11-2-3-known-issues" in u for u in urls)
    assert any("pan-os-11-2-3-addressed-issues" in u for u in urls)
    assert any("globalprotect-app-6-2-8-known-and-addressed-issues" in u for u in urls)
    assert not any("features-introduced-in-pan-os" in u for u in urls)


def test_classify_by_product_prefix_matches_panos():
    idx = SitemapIndex.from_xml(FIXTURE.read_text())
    panos = list(idx.for_product("panos"))
    assert len(panos) == 2
    assert all("/pan-os/" in e.url for e in panos)


def test_classify_by_product_prefix_matches_globalprotect():
    idx = SitemapIndex.from_xml(FIXTURE.read_text())
    gp = list(idx.for_product("globalprotect"))
    assert len(gp) == 1
    assert "/globalprotect/" in gp[0].url


def test_extract_major_version_from_url():
    idx = SitemapIndex.from_xml(FIXTURE.read_text())
    entries = list(idx.for_product("panos"))
    versions = {e.major_version for e in entries}
    assert versions == {"11-2"}


def test_lastmod_is_parsed():
    idx = SitemapIndex.from_xml(FIXTURE.read_text())
    e = next(iter(idx.for_product("globalprotect")))
    assert e.lastmod == "2026-04-15"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_sitemap.py -v`
Expected: `ModuleNotFoundError: No module named 'bugdb.sitemap'`

- [ ] **Step 4: Implement `SitemapIndex`**

```python
# src/bugdb/sitemap.py
"""Sitemap-driven URL discovery for bugdb.

The Palo Alto Networks documentation portals expose a `/sitemap.xml` with
every release-notes URL and a `<lastmod>` timestamp. Parsing the sitemap
once per run is dramatically cheaper than the JS-rendered version-index
crawl the legacy code does, and it also gives us a free incremental gate:
skip URLs whose `<lastmod>` matches the manifest entry from the last run.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

from lxml import etree

logger = logging.getLogger(__name__)

# Map of product_id -> (URL path substring required to belong to that product).
# Mirrors `PRODUCT_CRAWLERS` keys in `bugdb.crawlers.registry`. New products
# are added here when they grow a crawler.
_PRODUCT_PREFIXES: dict[str, tuple[str, ...]] = {
    "panos": ("/pan-os/",),
    "globalprotect": ("/globalprotect/",),
    "prisma-access": ("/prisma-access/",),
    "prisma-access-agent": ("/gp-app-for-prisma-access/", "/prisma-access-agent/"),
    "prisma-sdwan": ("/prisma-sd-wan/",),
    "cloud-ngfw-azure": ("/cloud-ngfw/azure/",),
    "cloud-ngfw-aws": ("/cloud-ngfw/aws/",),
    "remote-browser-isolation": ("/remote-browser-isolation/",),
    "ai-runtime-security": ("/ai-runtime-security/",),
    "strata-logging-service": ("/strata-logging-service/",),
    "device-security": ("/iot-security/", "/device-security/"),
    "adem": ("/autonomous-dem/",),
    "scm": ("/strata-cloud-manager/",),
    "sdwan-plugin": ("/panorama/plugins/sd-wan/",),
    "vm-series-plugin": ("/plugins/vm-series-and-panorama-plugins-release-notes/vm-series-plugin",),
    "plugin-aws": ("/plugins/vm-series-and-panorama-plugins-release-notes/panorama-plugin-for-aws",),
    "plugin-azure": ("/plugins/vm-series-and-panorama-plugins-release-notes/panorama-plugin-for-azure",),
    "plugin-gcp": ("/plugins/vm-series-and-panorama-plugins-release-notes/panorama-plugin-for-gcp",),
    "plugin-vmware-nsx": ("/plugins/vm-series-and-panorama-plugins-release-notes/panorama-plugin-for-nsx",),
    "plugin-vmware-vcenter": ("/plugins/vm-series-and-panorama-plugins-release-notes/panorama-plugin-for-vmware-vcenter",),
    "plugin-kubernetes": ("/plugins/vm-series-and-panorama-plugins-release-notes/panorama-plugin-for-kubernetes",),
    "plugin-cisco-aci": ("/plugins/vm-series-and-panorama-plugins-release-notes/panorama-plugin-for-cisco-aci",),
    "plugin-cisco-trustsec": ("/plugins/vm-series-and-panorama-plugins-release-notes/panorama-plugin-for-cisco-trustsec",),
    "plugin-ztp": ("/plugins/vm-series-and-panorama-plugins-release-notes/zero-touch-provisioning-ztp-plugin",),
    "plugin-clustering": ("/plugins/vm-series-and-panorama-plugins-release-notes/panorama-plugin-for-clustering",),
}

_ISSUE_MARKERS = ("known-issues", "addressed-issues", "known-and-addressed", "fixed-issues")

# Major version pattern as it appears in URLs, e.g. "/11-2/" or "/6-2-8/".
_MAJOR_VERSION_RE = re.compile(r"/(\d+-\d+)(?:[/-]|$)")


@dataclass(frozen=True)
class SitemapEntry:
    """One `<url>` from the sitemap, with derived fields."""

    url: str
    lastmod: Optional[str]
    product_id: Optional[str]
    major_version: Optional[str]
    is_issue_page: bool


@dataclass
class SitemapIndex:
    """In-memory index of a sitemap.xml document."""

    _entries: list[SitemapEntry] = field(default_factory=list)

    @classmethod
    def from_xml(cls, xml: str) -> "SitemapIndex":
        # Strip namespace by parsing locally and using local-name() lookups.
        # The PAN sitemap uses the standard sitemap-0.9 namespace.
        root = etree.fromstring(xml.encode("utf-8"))
        ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        entries: list[SitemapEntry] = []
        for url_el in root.findall("s:url", ns):
            loc = url_el.findtext("s:loc", default="", namespaces=ns).strip()
            if not loc:
                continue
            lastmod = url_el.findtext("s:lastmod", default=None, namespaces=ns)
            entries.append(_classify(loc, lastmod))
        logger.debug("parsed sitemap: %d entries", len(entries))
        return cls(_entries=entries)

    def all_entries(self) -> list[SitemapEntry]:
        return list(self._entries)

    def issue_urls(self) -> Iterable[SitemapEntry]:
        return (e for e in self._entries if e.is_issue_page)

    def for_product(self, product_id: str) -> Iterable[SitemapEntry]:
        return (
            e for e in self._entries
            if e.is_issue_page and e.product_id == product_id
        )


def _classify(url: str, lastmod: Optional[str]) -> SitemapEntry:
    lower = url.lower()
    product_id: Optional[str] = None
    for pid, prefixes in _PRODUCT_PREFIXES.items():
        if any(p.lower() in lower for p in prefixes):
            product_id = pid
            break
    is_issue_page = any(m in lower for m in _ISSUE_MARKERS)
    m = _MAJOR_VERSION_RE.search(url)
    major_version = m.group(1) if m else None
    return SitemapEntry(
        url=url,
        lastmod=lastmod.strip() if isinstance(lastmod, str) else lastmod,
        product_id=product_id,
        major_version=major_version,
        is_issue_page=is_issue_page,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_sitemap.py -v`
Expected: all 6 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/bugdb/sitemap.py tests/test_sitemap.py tests/fixtures/sitemap-sample.xml
git commit -m "feat(sitemap): add SitemapIndex with product classification and lastmod"
```

---

### Task 4: `FetchManifest` — persisted `<lastmod>` per URL

**Files:**
- Create: `src/bugdb/fetch_manifest.py`
- Create: `tests/test_fetch_manifest.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_fetch_manifest.py
import json
from pathlib import Path

from bugdb.fetch_manifest import FetchManifest, ManifestEntry


def test_load_missing_file_returns_empty_manifest(tmp_path: Path):
    m = FetchManifest.load(tmp_path / "manifest.json")
    assert len(m.entries) == 0


def test_should_skip_returns_false_when_url_unknown(tmp_path: Path):
    m = FetchManifest.load(tmp_path / "manifest.json")
    assert m.should_skip("https://x/y", lastmod="2026-01-01") is False


def test_should_skip_returns_true_when_lastmod_matches(tmp_path: Path):
    p = tmp_path / "manifest.json"
    m = FetchManifest(entries={"https://x/y": ManifestEntry(lastmod="2026-01-01")})
    assert m.should_skip("https://x/y", lastmod="2026-01-01") is True


def test_should_skip_returns_false_when_lastmod_differs(tmp_path: Path):
    m = FetchManifest(entries={"https://x/y": ManifestEntry(lastmod="2026-01-01")})
    assert m.should_skip("https://x/y", lastmod="2026-02-01") is False


def test_should_skip_returns_false_when_no_recorded_lastmod(tmp_path: Path):
    m = FetchManifest(entries={"https://x/y": ManifestEntry(lastmod=None)})
    assert m.should_skip("https://x/y", lastmod="2026-01-01") is False


def test_round_trip_save_load(tmp_path: Path):
    p = tmp_path / "manifest.json"
    m = FetchManifest(entries={
        "https://x/y": ManifestEntry(lastmod="2026-01-01"),
        "https://x/z": ManifestEntry(lastmod=None),
    })
    m.save(p)
    loaded = FetchManifest.load(p)
    assert loaded.entries == m.entries


def test_record_updates_entry(tmp_path: Path):
    m = FetchManifest()
    m.record("https://x/y", lastmod="2026-03-01")
    assert m.entries["https://x/y"].lastmod == "2026-03-01"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_fetch_manifest.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement the manifest**

```python
# src/bugdb/fetch_manifest.py
"""Persisted record of last-seen <lastmod> per URL.

Stored alongside the data JSON (e.g. `assets/bugdb.manifest.json`).
Read at the start of a fetch, mutated during the fetch as URLs are
processed, and rewritten on success. Lets weekly CI runs skip URLs
whose sitemap timestamp hasn't moved.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class ManifestEntry(BaseModel):
    lastmod: Optional[str] = None


class FetchManifest(BaseModel):
    entries: dict[str, ManifestEntry] = Field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "FetchManifest":
        if not path.exists():
            return cls()
        return cls.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.model_dump(mode="json"), indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def should_skip(self, url: str, lastmod: Optional[str]) -> bool:
        """Return True iff this URL's content is known unchanged.

        We require both a stored lastmod and a current lastmod, and they
        must match. Missing data on either side means "fetch to be safe".
        """
        if lastmod is None:
            return False
        prev = self.entries.get(url)
        if prev is None or prev.lastmod is None:
            return False
        return prev.lastmod == lastmod

    def record(self, url: str, lastmod: Optional[str]) -> None:
        self.entries[url] = ManifestEntry(lastmod=lastmod)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_fetch_manifest.py -v`
Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bugdb/fetch_manifest.py tests/test_fetch_manifest.py
git commit -m "feat(manifest): add FetchManifest with should_skip() based on sitemap lastmod"
```

---

## Phase 2 — Wire `HttpxDocsTransport` into `BaseCrawler`

### Task 5: `BaseCrawler` accepts an injected `Transport`

**Files:**
- Modify: `src/bugdb/crawlers/base.py`
- Modify: `src/bugdb/crawlers/__init__.py` (no functional change, may need re-exports)
- Modify: `tests/test_crawler.py` (the `MockBrowser`/`MockPage` rig must continue to work)

- [ ] **Step 1: Write a failing test that pins the new constructor shape**

Add to `tests/test_crawler.py`:

```python
def test_base_crawler_accepts_injected_transport():
    """Allow tests and the CLI to inject a fetch transport instead of Playwright."""
    from bugdb.transport.base import FetchedPage, Transport

    class StubTransport:
        async def fetch(self, url: str) -> FetchedPage:
            return FetchedPage(url=url, status_code=200, html="<html></html>")
        async def aclose(self) -> None:
            pass

    from bugdb.crawlers.base import BaseCrawler
    c = BaseCrawler(transport=StubTransport())
    assert c._transport is not None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_crawler.py::test_base_crawler_accepts_injected_transport -v`
Expected: `TypeError: __init__() got an unexpected keyword argument 'transport'`.

- [ ] **Step 3: Modify `BaseCrawler.__init__` to accept an optional transport**

In `src/bugdb/crawlers/base.py`, change `__init__` (around `base.py:44-79`) to accept `transport`:

```python
def __init__(
    self,
    *,
    transport: Optional["Transport"] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    max_retries: int = 3,
    retry_delay: float = 2.0,
):
    """Initialize the crawler.

    When `transport` is provided, page fetches use it and no Playwright
    browser is launched. When `transport` is None the legacy Playwright
    path is used (kept temporarily so existing tests and the
    `--use-browser` flag continue to work).
    """
    self._transport = transport
    self.headless = headless
    self.verbose = verbose
    self.debug = debug
    self.max_concurrency = max_concurrency
    self.max_retries = max_retries
    self.retry_delay = retry_delay
    self._playwright = None
    self._browser: Optional[Browser] = None
    self._semaphore: Optional[asyncio.Semaphore] = None
    self._global_backoff_until: float = 0.0
    self._backoff_lock: Optional[asyncio.Lock] = None
    if debug:
        configure_logging(debug=True)
```

Import `Transport` for the type hint at the top of the file:

```python
from bugdb.transport.base import Transport
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_crawler.py::test_base_crawler_accepts_injected_transport -v`
Expected: PASS.

- [ ] **Step 5: Run the full test suite to ensure no regressions**

Run: `uv run pytest tests/test_crawler.py -x`
Expected: PASS (we haven't changed any behavior path yet).

- [ ] **Step 6: Commit**

```bash
git add src/bugdb/crawlers/base.py tests/test_crawler.py
git commit -m "refactor(base): accept injected Transport, default None preserves Playwright"
```

---

### Task 6: Route `_fetch_page_with_semaphore` through the transport when present

**Files:**
- Modify: `src/bugdb/crawlers/base.py`
- Modify: `tests/test_crawler.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_crawler.py`:

```python
class TestBaseCrawlerTransportRouting:
    """When a Transport is injected, _fetch_page_with_semaphore must use it."""

    @pytest.mark.asyncio
    async def test_uses_transport_when_present(self):
        from bugdb.transport.base import FetchedPage
        from bugdb.crawlers.base import BaseCrawler

        calls = []

        class StubTransport:
            async def fetch(self, url: str) -> FetchedPage:
                calls.append(url)
                return FetchedPage(
                    url=url,
                    status_code=200,
                    html="<html><body><table>"
                         "<thead><tr><th>Issue ID</th><th>Description</th></tr></thead>"
                         "<tbody><tr><td>PAN-1</td><td>x</td></tr></tbody>"
                         "</table></body></html>",
                )
            async def aclose(self) -> None: ...

        c = BaseCrawler(transport=StubTransport(), max_concurrency=2)
        # Required for backoff in the transport path:
        c._semaphore = asyncio.Semaphore(2)
        c._backoff_lock = asyncio.Lock()

        soup = await c._fetch_page_with_semaphore("https://docs/x")
        assert calls == ["https://docs/x"]
        assert soup.find("table") is not None

    @pytest.mark.asyncio
    async def test_404_raises_with_transport(self):
        from bugdb.transport.base import FetchedPage
        from bugdb.crawlers.base import BaseCrawler

        class Stub:
            async def fetch(self, url):
                return FetchedPage(url=url, status_code=404, html="not found")
            async def aclose(self): ...

        c = BaseCrawler(transport=Stub(), max_concurrency=1)
        c._semaphore = asyncio.Semaphore(1)
        c._backoff_lock = asyncio.Lock()

        with pytest.raises(Exception) as excinfo:
            await c._fetch_page_with_semaphore("https://docs/missing")
        assert "404" in str(excinfo.value)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_crawler.py::TestBaseCrawlerTransportRouting -v`
Expected: both tests fail (today's code unconditionally calls `self._new_page()`).

- [ ] **Step 3: Update `_fetch_page_with_semaphore` to branch on transport**

In `src/bugdb/crawlers/base.py`, replace the body of `_fetch_page_with_semaphore` (`base.py:191-249`):

```python
async def _fetch_page_with_semaphore(
    self, url: str, wait_time: int = 3000
) -> BeautifulSoup:
    """Fetch a page using the injected transport, or fall back to Playwright."""
    if self._transport is not None:
        return await self._fetch_via_transport(url)
    return await self._fetch_via_browser(url, wait_time)


async def _fetch_via_transport(self, url: str) -> BeautifulSoup:
    last_error: Optional[Exception] = None
    for attempt in range(self.max_retries):
        await self._wait_for_global_backoff()
        async with self._semaphore:
            try:
                page = await self._transport.fetch(url)
            except Exception as e:
                last_error = e
                if self._is_connection_refused_error(e):
                    await self._trigger_global_backoff()
                logger.warning(
                    "transport fetch failed for %s (attempt %d/%d): %s",
                    url, attempt + 1, self.max_retries, e,
                )
            else:
                if page.status_code == 200:
                    return BeautifulSoup(page.html, "lxml")
                if page.status_code in (404, 410):
                    raise RuntimeError(f"HTTP {page.status_code} for {url}")
                last_error = RuntimeError(f"HTTP {page.status_code} for {url}")
                logger.warning("transport %s for %s", page.status_code, url)
        if attempt < self.max_retries - 1:
            await asyncio.sleep(self.retry_delay * (2 ** attempt))
    assert last_error is not None
    raise last_error
```

Rename the existing body to `_fetch_via_browser`:

```python
async def _fetch_via_browser(self, url: str, wait_time: int) -> BeautifulSoup:
    # <previous body of _fetch_page_with_semaphore unchanged>
```

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `uv run pytest tests/test_crawler.py::TestBaseCrawlerTransportRouting -v`
Expected: PASS.

- [ ] **Step 5: Run the entire suite**

Run: `uv run pytest tests/test_crawler.py -x`
Expected: PASS (legacy `_fetch_via_browser` path is unchanged so existing fixtures still drive `MockBrowser`).

- [ ] **Step 6: Commit**

```bash
git add src/bugdb/crawlers/base.py tests/test_crawler.py
git commit -m "refactor(base): route _fetch_page_with_semaphore through Transport when injected"
```

---

### Task 7: `BaseCrawler.__aenter__/__aexit__` skip Playwright when transport injected

**Files:**
- Modify: `src/bugdb/crawlers/base.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_crawler.py
@pytest.mark.asyncio
async def test_aenter_skips_playwright_when_transport_injected():
    from bugdb.transport.base import FetchedPage
    from bugdb.crawlers.base import BaseCrawler

    class Stub:
        async def fetch(self, url): return FetchedPage(url=url, status_code=200, html="")
        async def aclose(self): self.closed = True

    stub = Stub()
    async with BaseCrawler(transport=stub) as c:
        assert c._browser is None
        assert c._semaphore is not None
    assert getattr(stub, "closed", False)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_crawler.py::test_aenter_skips_playwright_when_transport_injected -v`
Expected: fails — current `__aenter__` always launches Chromium.

- [ ] **Step 3: Update `__aenter__` / `__aexit__`**

```python
async def __aenter__(self):
    self._semaphore = asyncio.Semaphore(self.max_concurrency)
    self._backoff_lock = asyncio.Lock()
    if self._transport is None:
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.headless)
    return self

async def __aexit__(self, exc_type, exc_val, exc_tb):
    if self._transport is not None:
        await self._transport.aclose()
        return
    if self._browser:
        await self._browser.close()
    if self._playwright:
        await self._playwright.stop()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_crawler.py::test_aenter_skips_playwright_when_transport_injected -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bugdb/crawlers/base.py tests/test_crawler.py
git commit -m "refactor(base): skip Playwright launch when Transport is injected"
```

---

### Task 8: Make `_parse_issues_page` resilient to the inline-div quirk

This is a belt-and-braces fix: even if a transport forgets to unwrap, the
parser should still work. Cheap defensive measure for the Playwright path
too.

**Files:**
- Modify: `src/bugdb/crawlers/base.py`

- [ ] **Step 1: Write a parser-level test**

```python
# tests/test_crawler.py
def test_parse_issues_table_handles_inline_div_quirk():
    from bs4 import BeautifulSoup
    from bugdb.crawlers.base import BaseCrawler

    html = """
    <table>
      <thead><tr><th>Issue ID</th><th>Description</th></tr></thead>
      <tbody><div style="display: inline;">
        <tr><div style="display: inline;">
          <td>PAN-99</td><td>quirky</td>
        </div></tr>
      </div></tbody>
    </table>
    """
    soup = BeautifulSoup(html, "lxml")
    c = BaseCrawler.__new__(BaseCrawler)
    issues = c._parse_issues_table(soup.find("table"))
    assert len(issues) == 1
    assert issues[0].bug_id == "PAN-99"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_crawler.py::test_parse_issues_table_handles_inline_div_quirk -v`
Expected: fails — current parser returns `[]`.

- [ ] **Step 3: Add an unwrap step at the top of `_parse_issues_table`**

In `src/bugdb/crawlers/base.py`, near the top of `_parse_issues_table` (`base.py:416`):

```python
def _parse_issues_table(self, table) -> list[Issue]:
    # AEM emits <table>...<tbody><div style="display:inline"><tr>...; browsers
    # foster-parent the div out, lxml does not. Unwrap defensively here so the
    # rest of the parser can rely on direct tbody>tr nesting.
    for d in table.select(
        'div[style*="display: inline"], div[style*="display:inline"]'
    ):
        d.unwrap()
    issues = []
    ...
```

Apply the same `for d in ... unwrap()` block to `_parse_issues_table_with_feature` (`base.py:535`).

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_crawler.py::test_parse_issues_table_handles_inline_div_quirk -v`
Expected: PASS.

- [ ] **Step 5: Re-run full crawler tests**

Run: `uv run pytest tests/test_crawler.py -x`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/bugdb/crawlers/base.py tests/test_crawler.py
git commit -m "fix(base): unwrap inline-display divs in _parse_issues_table"
```

---

## Phase 3 — Sitemap-driven discovery for PAN-OS and plugins

### Task 9: `PANOSCrawler.discover_versions` and `discover_version_pages` from sitemap

**Files:**
- Modify: `src/bugdb/crawlers/products/panos.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_crawler.py (PANOS section)
def test_panos_discover_versions_from_sitemap():
    from bugdb.sitemap import SitemapIndex
    from bugdb.crawlers.products.panos import PANOSCrawler

    xml = """<?xml version="1.0"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://docs.paloaltonetworks.com/pan-os/11-2/pan-os-release-notes/pan-os-11-2-3-known-and-addressed-issues/pan-os-11-2-3-known-issues</loc></url>
      <url><loc>https://docs.paloaltonetworks.com/pan-os/11-2/pan-os-release-notes/pan-os-11-2-3-known-and-addressed-issues/pan-os-11-2-3-addressed-issues</loc></url>
      <url><loc>https://docs.paloaltonetworks.com/pan-os/12-1/pan-os-release-notes/pan-os-12-1-1-known-and-addressed-issues/pan-os-12-1-1-known-issues</loc></url>
    </urlset>"""
    idx = SitemapIndex.from_xml(xml)
    c = PANOSCrawler.__new__(PANOSCrawler)
    c._sitemap = idx
    versions = c.discover_versions_from_sitemap()
    assert versions == ["12-1", "11-2"]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_crawler.py::test_panos_discover_versions_from_sitemap -v`
Expected: `AttributeError: ... 'discover_versions_from_sitemap'`.

- [ ] **Step 3: Add sitemap-based discovery**

In `src/bugdb/crawlers/products/panos.py`, add:

```python
def discover_versions_from_sitemap(self) -> list[str]:
    """Return major versions present in the sitemap, newest first."""
    if self._sitemap is None:
        return []
    versions = {
        e.major_version
        for e in self._sitemap.for_product(self.product_id)
        if e.major_version
    }
    return sorted(versions, key=lambda v: [int(x) for x in v.split("-")], reverse=True)


def discover_version_pages_from_sitemap(
    self, major_version: str
) -> list["VersionInfo"]:
    """Build VersionInfo entries from sitemap URLs for one major version."""
    if self._sitemap is None:
        return []
    by_version: dict[str, "VersionInfo"] = {}
    for entry in self._sitemap.for_product(self.product_id):
        if entry.major_version != major_version:
            continue
        # Derive the version string (e.g. "11.2.3" or "11.2.3-h1") from the URL.
        ver = self._extract_version_from_url(entry.url)
        if not ver:
            continue
        vi = by_version.setdefault(
            ver,
            VersionInfo(version=ver, known_issues_urls=[], addressed_issues_urls=[]),
        )
        lower = entry.url.lower()
        path = entry.url.replace("https://docs.paloaltonetworks.com", "")
        if path.endswith(".html"):
            path = path[:-5]
        if "known" in lower and "addressed" not in lower:
            if path not in vi.known_issues_urls:
                vi.known_issues_urls.append(path)
        elif "addressed" in lower and "known" not in lower:
            if path not in vi.addressed_issues_urls:
                vi.addressed_issues_urls.append(path)
        elif "known-and-addressed" in lower:
            # Index page that wraps both — treat as both for compatibility.
            if path not in vi.known_issues_urls:
                vi.known_issues_urls.append(path)
            if path not in vi.addressed_issues_urls:
                vi.addressed_issues_urls.append(path)
    return sorted(
        by_version.values(),
        key=lambda v: self._version_sort_key(v.version),
        reverse=True,
    )
```

Update `__init__` to accept the sitemap:

```python
def __init__(self, *args, sitemap=None, **kwargs):
    super().__init__(*args, **kwargs)
    self._sitemap = sitemap
```

Update `crawl(...)` so it prefers sitemap discovery when `self._sitemap is
not None`:

```python
async def crawl(self, major_versions=None, skip_versions=None):
    skip_versions = skip_versions or set()
    all_failed_fetches: list[FailedFetch] = []

    if self._sitemap is not None:
        if major_versions is None:
            major_versions = self.discover_versions_from_sitemap()
        all_product_versions = []
        for mv in major_versions:
            version_infos = self.discover_version_pages_from_sitemap(mv)
            version_infos = [vi for vi in version_infos if vi.version not in skip_versions]
            if not version_infos:
                continue
            pvs, failed = await self._crawl_versions_parallel(version_infos, self.product_id)
            all_product_versions.extend(pvs)
            all_failed_fetches.extend(failed)
    else:
        # Legacy probe-based path — unchanged
        ...  # keep existing implementation as the else branch
    ...
```

(Wrap the existing implementation into the `else` branch.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_crawler.py::test_panos_discover_versions_from_sitemap -v`
Expected: PASS.

- [ ] **Step 5: Run the rest of the PAN-OS tests**

Run: `uv run pytest tests/test_crawler.py -k panos -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/bugdb/crawlers/products/panos.py tests/test_crawler.py
git commit -m "feat(panos): sitemap-driven version discovery, falls back to legacy probe"
```

---

### Task 10: Same pattern for `PluginCrawler` and the other URL-list-based products

Loop the pattern from Task 9 across the products whose discovery is also
just "find URLs matching this product prefix and parse them": GlobalProtect,
Prisma Access, Prisma SD-WAN, Cloud NGFW, ADEM, SCM, SD-WAN plugin, all
`plugin-*`. Each one becomes a small, ~30-line change that:

1. Adds `sitemap=None` to `__init__`.
2. Adds `discover_*_from_sitemap()` methods analogous to PAN-OS.
3. Branches `crawl()` to use the sitemap path when `self._sitemap is not None`.

**Files:**
- Modify: `src/bugdb/crawlers/products/globalprotect.py`
- Modify: `src/bugdb/crawlers/products/prisma_access.py`
- Modify: `src/bugdb/crawlers/products/prisma_access_agent.py`
- Modify: `src/bugdb/crawlers/products/prisma_sdwan.py`
- Modify: `src/bugdb/crawlers/products/cloud_ngfw.py` (both AWS + Azure classes)
- Modify: `src/bugdb/crawlers/products/saas.py` (RBI, AI-RT, SLS)
- Modify: `src/bugdb/crawlers/products/device_security.py`
- Modify: `src/bugdb/crawlers/products/adem.py`
- Modify: `src/bugdb/crawlers/products/scm.py`
- Modify: `src/bugdb/crawlers/products/sdwan_plugin.py`
- Modify: `src/bugdb/crawlers/products/plugins.py`

- [ ] **Step 1: For each product crawler, add a test mirroring `test_panos_discover_versions_from_sitemap`**

Use the same fixture pattern, just with the product-specific URL prefix.
For products without a major-version concept (ADEM, SCM, SaaS), the test
asserts `discover_issue_urls_from_sitemap()` returns the expected URL list.

- [ ] **Step 2: Implement each product crawler's sitemap branch following the PAN-OS pattern**

Keep the legacy probe-based code as the `else` branch so we still have an
escape hatch when a product's sitemap entries look weird.

- [ ] **Step 3: Run all crawler tests after each product**

```bash
uv run pytest tests/test_crawler.py -k <product> -v
```

- [ ] **Step 4: Commit per product**

```bash
git commit -m "feat(<product>): sitemap-driven discovery"
```

(11 small commits beats one giant commit; each one is independently
revertable if the product's sitemap data turns out to be incomplete.)

---

## Phase 4 — Cortex XDR via FluidTopics

### Task 11: `FluidTopicsTransport`

**Files:**
- Create: `src/bugdb/transport/fluidtopics_transport.py`
- Create: `tests/test_transport_fluidtopics.py`
- Create: `tests/fixtures/fluidtopics/maps.json`
- Create: `tests/fixtures/fluidtopics/topics.json`
- Create: `tests/fixtures/fluidtopics/content-addressed-issues.html`

- [ ] **Step 1: Record minimal fixtures**

`tests/fixtures/fluidtopics/maps.json` — trimmed to one Cortex XDR Agent
release-notes map plus one unrelated map so filtering can be tested:

```json
[
  {
    "title": "Cortex XDR Agent Release Notes",
    "id": "abc123",
    "mapApiEndpoint": "/api/khub/maps/abc123",
    "metadata": [
      {"key": "Product", "label": "Product", "values": ["Cortex XDR"]}
    ]
  },
  {
    "title": "Unrelated Doc",
    "id": "zzz999",
    "mapApiEndpoint": "/api/khub/maps/zzz999",
    "metadata": [{"key": "Product", "label": "Product", "values": ["Other"]}]
  }
]
```

`tests/fixtures/fluidtopics/topics.json`:

```json
[
  {
    "title": "Cortex XDR Agent 9.1 Release Information",
    "id": "t-9-1",
    "contentApiEndpoint": "/api/khub/maps/abc123/topics/t-9-1/content",
    "readerUrl": "/r/Cortex-XDR/Cortex-XDR-Agent-Release-Notes/Cortex-XDR-Agent-9.1-Release-Information",
    "breadcrumb": ["Cortex XDR Agent 9.1 Release Information"],
    "metadata": [
      {"key": "Version", "label": "Version", "values": ["9.1"]},
      {"key": "publicationDate", "label": "Last date published", "values": ["2026-05-12"]}
    ]
  },
  {
    "title": "Addressed issues in Cortex XDR agent 9.1.1",
    "id": "t-9-1-1-addr",
    "contentApiEndpoint": "/api/khub/maps/abc123/topics/t-9-1-1-addr/content",
    "readerUrl": "/r/Cortex-XDR/Cortex-XDR-Agent-Release-Notes/Addressed-issues-in-Cortex-XDR-agent-9.1.1",
    "breadcrumb": ["..."],
    "metadata": [{"key": "Version", "label": "Version", "values": ["9.1.1"]}]
  }
]
```

`tests/fixtures/fluidtopics/content-addressed-issues.html`:

```html
<div class="ft_node_extractor content-locale-en-US">
<p>The following issues have been resolved in this release.</p>
<table>
  <thead><tr><th>ISSUE</th><th>PLATFORM</th><th>DESCRIPTION</th></tr></thead>
  <tbody>
    <tr><td><p>CPATR-1</p></td><td><p>Windows</p></td><td><p>Fixed A.</p></td></tr>
    <tr><td><p>CPATR-2</p></td><td><p>Linux</p></td><td><p>Fixed B.</p></td></tr>
  </tbody>
</table>
</div>
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_transport_fluidtopics.py
import json
from pathlib import Path

import httpx
import pytest
import respx

from bugdb.transport.fluidtopics_transport import FluidTopicsTransport

FX = Path(__file__).parent / "fixtures" / "fluidtopics"


@pytest.mark.asyncio
@respx.mock
async def test_lists_maps_filtered_by_product():
    respx.get("https://docs-cortex.paloaltonetworks.com/api/khub/maps").mock(
        return_value=httpx.Response(200, text=(FX / "maps.json").read_text())
    )
    async with FluidTopicsTransport() as t:
        maps = await t.list_maps(product="Cortex XDR")
    assert len(maps) == 1
    assert maps[0]["id"] == "abc123"


@pytest.mark.asyncio
@respx.mock
async def test_lists_topics_in_a_map():
    respx.get(
        "https://docs-cortex.paloaltonetworks.com/api/khub/maps/abc123/topics"
    ).mock(return_value=httpx.Response(200, text=(FX / "topics.json").read_text()))
    async with FluidTopicsTransport() as t:
        topics = await t.list_topics(map_id="abc123")
    assert {tp["id"] for tp in topics} == {"t-9-1", "t-9-1-1-addr"}


@pytest.mark.asyncio
@respx.mock
async def test_fetch_topic_content_returns_html_fragment():
    respx.get(
        "https://docs-cortex.paloaltonetworks.com/api/khub/maps/abc123/topics/t-9-1-1-addr/content"
    ).mock(return_value=httpx.Response(
        200, headers={"content-type": "text/html"},
        text=(FX / "content-addressed-issues.html").read_text(),
    ))
    async with FluidTopicsTransport() as t:
        page = await t.fetch_topic(map_id="abc123", topic_id="t-9-1-1-addr")
    assert page.status_code == 200
    assert "CPATR-1" in page.html
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_transport_fluidtopics.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 4: Implement the transport**

```python
# src/bugdb/transport/fluidtopics_transport.py
"""Cortex docs API client (FluidTopics khub).

The Cortex docs portal is a FluidTopics SPA whose content endpoints are
public JSON+HTML at /api/khub/. This replaces the Playwright shadow-DOM
walk in the legacy CortexXDRCrawler.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import httpx

from bugdb.transport.base import FetchedPage

logger = logging.getLogger(__name__)

CORTEX_BASE = "https://docs-cortex.paloaltonetworks.com"
_HEADERS = {
    "User-Agent": "bugdb/1.0",
    "Accept": "application/json,text/html;q=0.9",
}


class FluidTopicsTransport:
    """High-level wrapper around the relevant khub endpoints.

    Exposes higher-level methods (`list_maps`, `list_topics`, `fetch_topic`)
    rather than the bare Transport.fetch protocol because Cortex crawling
    needs traversal, not a flat URL fetch. The shared `fetch` method is
    still implemented so the FluidTopics client is callable from anywhere
    a Transport is expected.
    """

    def __init__(self, *, concurrency: int = 10, timeout: float = 20.0) -> None:
        self._client = httpx.AsyncClient(
            http2=True,
            follow_redirects=False,
            headers=_HEADERS,
            timeout=timeout,
            limits=httpx.Limits(max_keepalive_connections=concurrency,
                                max_connections=concurrency + 5),
        )
        self._sem = asyncio.Semaphore(concurrency)

    async def __aenter__(self) -> "FluidTopicsTransport":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def fetch(self, url: str) -> FetchedPage:
        async with self._sem:
            resp = await self._client.get(url)
        return FetchedPage(url=url, status_code=resp.status_code, html=resp.text)

    async def list_maps(self, *, product: Optional[str] = None) -> list[dict]:
        resp = await self._client.get(f"{CORTEX_BASE}/api/khub/maps")
        resp.raise_for_status()
        maps = resp.json()
        if product is None:
            return maps
        return [m for m in maps if _matches_product(m, product)]

    async def list_topics(self, *, map_id: str) -> list[dict]:
        resp = await self._client.get(f"{CORTEX_BASE}/api/khub/maps/{map_id}/topics")
        resp.raise_for_status()
        return resp.json()

    async def fetch_topic(self, *, map_id: str, topic_id: str) -> FetchedPage:
        url = f"{CORTEX_BASE}/api/khub/maps/{map_id}/topics/{topic_id}/content"
        async with self._sem:
            resp = await self._client.get(url)
        return FetchedPage(url=url, status_code=resp.status_code, html=resp.text)


def _matches_product(map_obj: dict, product: str) -> bool:
    for entry in map_obj.get("metadata", []):
        if entry.get("key") != "Product":
            continue
        if product in entry.get("values", []):
            return True
    return False
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_transport_fluidtopics.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/bugdb/transport/fluidtopics_transport.py \
        tests/test_transport_fluidtopics.py tests/fixtures/fluidtopics/
git commit -m "feat(transport): add FluidTopicsTransport (khub API for Cortex docs)"
```

---

### Task 12: Rewire `CortexXDRCrawler` over `FluidTopicsTransport`

**Files:**
- Modify: `src/bugdb/crawlers/products/cortex_xdr.py`

- [ ] **Step 1: Write a test that drives the new code path with stubbed transport**

```python
# tests/test_crawler.py
class TestCortexXDRViaFluidTopics:
    @pytest.mark.asyncio
    async def test_crawl_returns_issues_from_topics(self):
        from bugdb.transport.base import FetchedPage
        from bugdb.crawlers.products.cortex_xdr import CortexXDRCrawler

        # Stub FluidTopics client
        class Stub:
            async def list_maps(self, *, product=None):
                return [{"id": "abc", "title": "Cortex XDR Agent Release Notes",
                         "metadata": [{"key": "Product", "values": ["Cortex XDR"]}]}]
            async def list_topics(self, *, map_id):
                return [
                    {"title": "Addressed issues in Cortex XDR agent 9.1",
                     "id": "addr-9-1",
                     "contentApiEndpoint": "/api/khub/maps/abc/topics/addr-9-1/content",
                     "metadata": [{"key": "Version", "values": ["9.1"]}]},
                    {"title": "Cortex XDR agent known limitations",
                     "id": "kl-9-1",
                     "contentApiEndpoint": "/api/khub/maps/abc/topics/kl-9-1/content",
                     "metadata": [{"key": "Version", "values": ["9.1"]}]},
                ]
            async def fetch_topic(self, *, map_id, topic_id):
                if topic_id == "addr-9-1":
                    return FetchedPage(url="", status_code=200, html=
                        "<div><table><thead><tr><th>ISSUE</th><th>DESCRIPTION</th></tr></thead>"
                        "<tbody><tr><td>CPATR-1</td><td>fixed A</td></tr></tbody></table></div>")
                return FetchedPage(url="", status_code=200, html=
                    "<div><table><thead><tr><th>ISSUE</th><th>DESCRIPTION</th></tr></thead>"
                    "<tbody><tr><td>CPATR-99</td><td>known X</td></tr></tbody></table></div>")
            async def aclose(self): ...

        crawler = CortexXDRCrawler(fluidtopics=Stub(), transport=Stub())
        # NOTE: pass the same Stub as Transport too because BaseCrawler
        # short-circuits Playwright when transport is set.
        crawler._semaphore = asyncio.Semaphore(2)
        crawler._backoff_lock = asyncio.Lock()
        result = await crawler.crawl()
        product = result.product
        assert product.id == "cortex-xdr"
        # 9.1 known and addressed issues both surface
        assert len(product.versions) == 1
        v = product.versions[0]
        assert v.version == "9.1"
        assert {i.bug_id for i in v.addressed_issues} == {"CPATR-1"}
        assert {i.bug_id for i in v.known_issues} == {"CPATR-99"}
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_crawler.py::TestCortexXDRViaFluidTopics -v`
Expected: fails — `CortexXDRCrawler` doesn't accept `fluidtopics=`.

- [ ] **Step 3: Refactor `CortexXDRCrawler.crawl` to traverse maps→topics→content**

Add to `CortexXDRCrawler`:

```python
def __init__(self, *args, fluidtopics=None, **kwargs):
    super().__init__(*args, **kwargs)
    self._fluidtopics = fluidtopics


async def crawl(self, major_versions=None, skip_versions=None) -> CrawlResult:
    if self._fluidtopics is None:
        # Legacy shadow-DOM path remains for `--use-browser`
        return await self._legacy_crawl(major_versions, skip_versions)

    skip_versions = skip_versions or set()
    failed_fetches: list[FailedFetch] = []

    maps = await self._fluidtopics.list_maps(product="Cortex XDR")
    # Pick maps whose title matches release notes
    rn_maps = [m for m in maps if "Release Notes" in m.get("title", "")]
    versions_data: dict[str, tuple[list[Issue], list[Issue], Optional[str]]] = {}

    for m in rn_maps:
        topics = await self._fluidtopics.list_topics(map_id=m["id"])
        for t in topics:
            ver = _extract_version_from_metadata(t) or self._extract_cortex_xdr_version(t.get("title", ""))
            if ver is None or ver in skip_versions:
                continue
            title_lower = t.get("title", "").lower()
            is_addressed = "addressed" in title_lower or "fixed" in title_lower
            is_known = "known" in title_lower and ("issue" in title_lower or "limitation" in title_lower)
            if not (is_addressed or is_known):
                continue
            try:
                page = await self._fluidtopics.fetch_topic(map_id=m["id"], topic_id=t["id"])
            except Exception as exc:
                failed_fetches.append(FailedFetch(
                    url=t.get("contentApiEndpoint", ""), error=str(exc),
                    product=self.product_id, version=ver,
                    issue_type="addressed" if is_addressed else "known",
                ))
                continue
            if page.status_code != 200:
                continue
            soup = BeautifulSoup(page.html, "lxml")
            known, addressed = self._parse_cortex_xdr_release_page(soup)
            # Distribute based on which topic this was
            kk, aa, date = versions_data.setdefault(ver, ([], [], _extract_publication_date(t)))
            if is_addressed:
                aa.extend(addressed if addressed else known)
            else:
                kk.extend(known if known else addressed)

    product_versions: list[ProductVersion] = []
    for ver, (known, addressed, date) in versions_data.items():
        if known or addressed:
            product_versions.append(ProductVersion(
                version=ver, release_date=date,
                known_issues=self._deduplicate_issues(known),
                addressed_issues=self._deduplicate_issues(addressed),
            ))
    product_versions.sort(key=lambda v: self._version_sort_key(v.version), reverse=True)
    return CrawlResult(
        product=Product(id=self.product_id, name=self.product_name, versions=product_versions),
        failed_fetches=failed_fetches,
    )


async def _legacy_crawl(self, major_versions, skip_versions):
    # <existing crawl body, unchanged>
```

Add helpers at module level:

```python
def _extract_version_from_metadata(topic: dict) -> Optional[str]:
    for entry in topic.get("metadata", []):
        if entry.get("key") == "Version" and entry.get("values"):
            return entry["values"][0]
    return None


def _extract_publication_date(topic: dict) -> Optional[str]:
    for entry in topic.get("metadata", []):
        if entry.get("key") in ("publicationDate", "Last date published") and entry.get("values"):
            return entry["values"][0]
    return None
```

- [ ] **Step 4: Run the new test to verify it passes**

Run: `uv run pytest tests/test_crawler.py::TestCortexXDRViaFluidTopics -v`
Expected: PASS.

- [ ] **Step 5: Run the full Cortex test suite**

Run: `uv run pytest tests/test_crawler.py -k cortex -v`
Expected: existing legacy tests still pass (they exercise `_legacy_crawl`).

- [ ] **Step 6: Commit**

```bash
git add src/bugdb/crawlers/products/cortex_xdr.py tests/test_crawler.py
git commit -m "feat(cortex): crawl Cortex XDR via FluidTopics API, legacy path preserved"
```

---

## Phase 5 — CLI: build one transport + sitemap + manifest per run

### Task 13: `bugdb fetch` wires sitemap, transports, and manifest

**Files:**
- Modify: `src/bugdb/cli.py`
- Modify: `src/bugdb/crawlers/registry.py`

- [ ] **Step 1: Write an end-to-end CLI test using `respx` for the sitemap**

```python
# tests/test_cli.py
import json
from pathlib import Path

import httpx
import respx
from typer.testing import CliRunner

from bugdb.cli import app


@respx.mock
def test_fetch_uses_sitemap_and_writes_manifest(tmp_path: Path):
    # Minimal sitemap with one URL we can parse.
    respx.get("https://docs.paloaltonetworks.com/sitemap.xml").mock(
        return_value=httpx.Response(200, text="""<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url>
            <loc>https://docs.paloaltonetworks.com/pan-os/11-2/pan-os-release-notes/pan-os-11-2-3-known-and-addressed-issues/pan-os-11-2-3-known-issues</loc>
            <lastmod>2026-04-01</lastmod>
          </url>
        </urlset>""")
    )
    respx.get(
        "https://docs.paloaltonetworks.com/pan-os/11-2/pan-os-release-notes/pan-os-11-2-3-known-and-addressed-issues/pan-os-11-2-3-known-issues"
    ).mock(return_value=httpx.Response(200, text="""
        <html><body>
        <table>
          <thead><tr><th>Issue ID</th><th>Description</th></tr></thead>
          <tbody><tr><td>PAN-42</td><td>desc</td></tr></tbody>
        </table>
        </body></html>"""))

    out = tmp_path / "bugdb.json"
    manifest_path = tmp_path / "bugdb.manifest.json"

    runner = CliRunner()
    result = runner.invoke(app, [
        "fetch", "panos",
        "-o", str(out),
        "--manifest", str(manifest_path),
    ])
    assert result.exit_code == 0, result.output
    data = json.loads(out.read_text())
    assert len(data["products"]) == 1
    assert data["products"][0]["id"] == "panos"
    assert manifest_path.exists()
    mdata = json.loads(manifest_path.read_text())
    assert any("pan-os-11-2-3-known-issues" in k for k in mdata["entries"])
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_cli.py::test_fetch_uses_sitemap_and_writes_manifest -v`
Expected: fails (no `--manifest` flag, no sitemap path).

- [ ] **Step 3: Update `cli.py fetch`**

Top of `fetch` command, after parsing args:

```python
from bugdb.fetch_manifest import FetchManifest
from bugdb.sitemap import SitemapIndex
from bugdb.transport.httpx_transport import HttpxDocsTransport
from bugdb.transport.fluidtopics_transport import FluidTopicsTransport

# ... existing arg handling ...

manifest_path = manifest or (output.with_suffix(".manifest.json"))
manifest_obj = FetchManifest() if no_manifest else FetchManifest.load(manifest_path)

# Fetch sitemap once
sitemap_index: Optional[SitemapIndex] = None
if not use_browser:
    sitemap_url = "https://docs.paloaltonetworks.com/sitemap.xml"
    with httpx.Client(http2=True, follow_redirects=True, timeout=30.0) as c:
        resp = c.get(sitemap_url)
        resp.raise_for_status()
        sitemap_index = SitemapIndex.from_xml(resp.text)
```

Add new options to the `fetch` function signature:

```python
manifest: Annotated[
    Optional[Path],
    typer.Option("--manifest", help="Path to fetch manifest JSON (default: <output>.manifest.json)"),
] = None,
no_manifest: Annotated[
    bool,
    typer.Option("--no-manifest", help="Disable manifest read/write."),
] = False,
use_browser: Annotated[
    bool,
    typer.Option("--use-browser", help="Use the legacy Playwright path."),
] = False,
```

Pass `sitemap=sitemap_index`, `transport=...`, and `fluidtopics=...` through to each
`crawl_*` call. Register the transport factory inside each `_crawl_*_async`
in `registry.py`:

```python
# registry.py — one example, repeat for each product
async def _crawl_panos_async(
    major_versions=None, headless=True, verbose=False, debug=False,
    max_concurrency=3, skip_versions=None,
    transport=None, sitemap=None,
):
    async with PANOSCrawler(
        transport=transport, sitemap=sitemap,
        headless=headless, verbose=verbose, debug=debug,
        max_concurrency=max_concurrency,
    ) as crawler:
        result = await crawler.crawl(major_versions, skip_versions)
        ...
```

Update each `crawl_<product>(...)` sync wrapper to plumb the new kwargs
through.

In the CLI's loop over products, build one transport per host and share it
across products:

```python
docs_transport = HttpxDocsTransport(concurrency=15)
fluidtopics = FluidTopicsTransport(concurrency=10)
try:
    for prod_name in products_to_fetch:
        crawler_func = supported_products[prod_name]
        skip_versions = existing_versions.get(prod_name, set())
        # Sitemap-based skip: union with manifest-known-unchanged URLs is
        # carried inside the sitemap-discovery code path, not here, so the
        # crawler can still emit per-URL failed-fetch entries.
        result = crawler_func(
            major_versions,
            headless=headless, debug=debug,
            skip_versions=skip_versions,
            transport=docs_transport if prod_name != "cortex-xdr" else None,
            fluidtopics=fluidtopics if prod_name == "cortex-xdr" else None,
            sitemap=sitemap_index,
        )
        all_products.extend(result.database.products)
        all_failed_fetches.extend(result.failed_fetches)
finally:
    asyncio.run(docs_transport.aclose())
    asyncio.run(fluidtopics.aclose())
```

After a successful fetch, record sitemap lastmods for every URL that
actually got fetched (the crawlers report this via their failed_fetches
and product structure — simplest is to walk `sitemap_index.issue_urls()`
and for any URL that the new run *kept* in the output, set the manifest
to its current lastmod):

```python
if not no_manifest and sitemap_index is not None:
    for entry in sitemap_index.issue_urls():
        manifest_obj.record(entry.url, entry.lastmod)
    manifest_obj.save(manifest_path)
```

- [ ] **Step 4: Run the CLI test to verify it passes**

Run: `uv run pytest tests/test_cli.py::test_fetch_uses_sitemap_and_writes_manifest -v`
Expected: PASS.

- [ ] **Step 5: Run the full test suite**

Run: `uv run pytest -x`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/bugdb/cli.py src/bugdb/crawlers/registry.py tests/test_cli.py
git commit -m "feat(cli): sitemap+manifest+transport wiring for fetch"
```

---

### Task 14: Pass the manifest into the discover step so unchanged URLs are skipped

**Files:**
- Modify: `src/bugdb/crawlers/products/panos.py`
- Modify: every product touched in Task 10

- [ ] **Step 1: Add a test**

```python
# tests/test_crawler.py
def test_panos_skips_urls_whose_lastmod_matches_manifest():
    from bugdb.sitemap import SitemapIndex
    from bugdb.fetch_manifest import FetchManifest, ManifestEntry
    from bugdb.crawlers.products.panos import PANOSCrawler

    xml = """<?xml version="1.0"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://docs.paloaltonetworks.com/pan-os/11-2/pan-os-release-notes/pan-os-11-2-3-known-and-addressed-issues/pan-os-11-2-3-known-issues</loc><lastmod>2026-03-01</lastmod></url>
      <url><loc>https://docs.paloaltonetworks.com/pan-os/11-2/pan-os-release-notes/pan-os-11-2-3-known-and-addressed-issues/pan-os-11-2-3-addressed-issues</loc><lastmod>2026-03-01</lastmod></url>
    </urlset>"""
    idx = SitemapIndex.from_xml(xml)
    manifest = FetchManifest(entries={
        "https://docs.paloaltonetworks.com/pan-os/11-2/pan-os-release-notes/pan-os-11-2-3-known-and-addressed-issues/pan-os-11-2-3-known-issues":
            ManifestEntry(lastmod="2026-03-01"),
    })

    c = PANOSCrawler.__new__(PANOSCrawler)
    c._sitemap = idx
    c._manifest = manifest

    vis = c.discover_version_pages_from_sitemap("11-2")
    flat = [u for v in vis for u in v.known_issues_urls + v.addressed_issues_urls]
    # The known-issues URL is unchanged → skipped. addressed-issues remains.
    assert not any("11-2-3-known-issues" in u for u in flat)
    assert any("11-2-3-addressed-issues" in u for u in flat)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_crawler.py::test_panos_skips_urls_whose_lastmod_matches_manifest -v`
Expected: fails.

- [ ] **Step 3: Implement**

In each product crawler:

```python
def __init__(self, *args, sitemap=None, manifest=None, **kwargs):
    super().__init__(*args, **kwargs)
    self._sitemap = sitemap
    self._manifest = manifest
```

In `discover_version_pages_from_sitemap`, before appending a URL:

```python
if self._manifest is not None and self._manifest.should_skip(entry.url, entry.lastmod):
    continue
```

Propagate `manifest=manifest_obj` from the CLI through `registry.py`
through each crawler.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_crawler.py::test_panos_skips_urls_whose_lastmod_matches_manifest -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bugdb/crawlers/products/ src/bugdb/crawlers/registry.py src/bugdb/cli.py tests/test_crawler.py
git commit -m "feat: skip URLs whose sitemap lastmod matches the manifest"
```

---

## Phase 6 — Parity check vs the legacy run

### Task 15: `scripts/parity_check.py`

**Files:**
- Create: `scripts/parity_check.py`
- Modify: `pyproject.toml` (optional console script)

- [ ] **Step 1: Write the script**

```python
# scripts/parity_check.py
"""Compare two bugdb JSON snapshots issue-count-wise.

Usage:
  python scripts/parity_check.py old.json new.json [--min-ratio 0.95]

Exits 0 if for every (product, version) the new snapshot has
at least min_ratio * old count of known and addressed issues.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _by_pv(db: dict) -> dict[tuple[str, str], tuple[int, int]]:
    out: dict[tuple[str, str], tuple[int, int]] = {}
    for p in db.get("products", []):
        for v in p.get("versions", []):
            out[(p["id"], v["version"])] = (
                len(v.get("known_issues", [])),
                len(v.get("addressed_issues", [])),
            )
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("old", type=Path)
    ap.add_argument("new", type=Path)
    ap.add_argument("--min-ratio", type=float, default=0.95)
    args = ap.parse_args()

    old = _by_pv(json.loads(args.old.read_text()))
    new = _by_pv(json.loads(args.new.read_text()))
    failed = []
    for key, (ko, ao) in old.items():
        kn, an = new.get(key, (0, 0))
        if ko > 0 and kn < ko * args.min_ratio:
            failed.append((key, "known", ko, kn))
        if ao > 0 and an < ao * args.min_ratio:
            failed.append((key, "addressed", ao, an))

    only_new = set(new) - set(old)
    if only_new:
        print(f"[i] {len(only_new)} (product,version) pairs new in new.json")
    only_old = set(old) - set(new)
    if only_old:
        print(f"[!] {len(only_old)} (product,version) pairs missing in new.json:")
        for k in sorted(only_old):
            print(f"    {k}")

    if failed:
        print(f"\n[x] {len(failed)} issue counts regressed:")
        for (pid, ver), kind, o, n in failed:
            print(f"    {pid} {ver} {kind}: old={o} new={n}")
        return 1
    print("[ok] new ≥ %.0f%% of old for every (product,version)" % (args.min_ratio * 100))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Test the script with two trivial snapshots**

```bash
echo '{"products":[{"id":"a","versions":[{"version":"1","known_issues":[{}, {}],"addressed_issues":[]}]}]}' > /tmp/old.json
echo '{"products":[{"id":"a","versions":[{"version":"1","known_issues":[{}, {}],"addressed_issues":[]}]}]}' > /tmp/new.json
uv run python scripts/parity_check.py /tmp/old.json /tmp/new.json
```

Expected: `[ok] new ≥ 95% of old for every (product,version)`.

- [ ] **Step 3: Commit**

```bash
git add scripts/parity_check.py
git commit -m "feat(parity): add parity_check.py to compare old vs new fetch JSON"
```

---

### Task 16: Run the parity check end-to-end

This is operational, not code. Aim: confirm that for every
(product, version) tuple in the *old* committed snapshot, the *new* run
produces at least 95% of the issue count.

- [ ] **Step 1: Capture a baseline with the legacy Playwright path**

```bash
mkdir -p artifacts/parity
uv run bugdb fetch --use-browser \
  -o artifacts/parity/old.json \
  --no-progress -f
```

Expected: long run, completes, file written. Note the wall time.

- [ ] **Step 2: Run the new path**

```bash
uv run bugdb fetch \
  -o artifacts/parity/new.json \
  --no-progress -f \
  --no-manifest
```

Expected: completes in minutes, not tens of minutes. Note the wall time.

- [ ] **Step 3: Compare**

```bash
uv run python scripts/parity_check.py \
  artifacts/parity/old.json artifacts/parity/new.json
```

Expected: `[ok] new ≥ 95% of old for every (product,version)`. If not:

- For each regressed `(product, version)` printed by the script, open
  `artifacts/parity/old.json` and `artifacts/parity/new.json`, eyeball the
  raw `bug_id` lists, and decide:
  * **Parser miss** → write a targeted unit test using a recorded HTML
    fixture and fix the parser.
  * **Sitemap miss** → check whether the URL the old run used is even in
    `sitemap.xml`; if not, add a small allowlist in
    `src/bugdb/sitemap.py:_PRODUCT_PREFIXES` or augment the discovery
    function to also probe for that URL pattern.
  * **Cortex topic-classification miss** → expand the title-matching
    heuristics in `cortex_xdr.py`.

Iterate steps 2-3 until parity holds.

- [ ] **Step 4: Commit any parser/discovery fixes**

```bash
git add <changed files> tests/
git commit -m "fix(parity): <specific fix>"
```

- [ ] **Step 5: Save the proof-of-parity artifact**

```bash
mkdir -p docs/superpowers/proof
mv artifacts/parity/old.json docs/superpowers/proof/baseline-bugdb.json
mv artifacts/parity/new.json docs/superpowers/proof/new-bugdb.json
git add docs/superpowers/proof/
git commit -m "docs: persist parity baseline + new fetch output"
```

(Optional — these files are large; consider Git LFS or just keeping them
locally and referencing the parity-check output in the PR description.)

---

## Phase 7 — Verification before merge

### Task 17: Pre-commit gates

- [ ] **Step 1: Run linting**

```bash
uv run ruff check src tests
uv run ruff format --check src tests
```

Expected: clean.

- [ ] **Step 2: Run type checking**

```bash
uv run pyright src
```

Expected: zero errors. The plan specifies `Optional[Transport]` and
explicit returns everywhere, so no new `# type: ignore` should be needed.

- [ ] **Step 3: Run the full test suite with coverage**

```bash
uv run pytest -x --cov=src/bugdb --cov-report=term-missing
```

Expected: all green, coverage on the new modules ≥ 90 % lines.

- [ ] **Step 4: One real smoke run, single product**

```bash
uv run bugdb fetch panos -o /tmp/smoke.json -f --no-progress
test -s /tmp/smoke.json && jq '.products[0].versions | length' /tmp/smoke.json
```

Expected: file written, at least 5 versions present.

- [ ] **Step 5: One real incremental run**

```bash
# Should make minimal HTTP traffic — every URL's lastmod is in the manifest.
time uv run bugdb fetch panos -o /tmp/smoke.json --incremental --no-progress
```

Expected: completes in seconds.

---

## Phase 8 — CI/CD integration (planning, not yet executing)

The CI work is left for a follow-up plan because it touches the GitLab
runner config and operations. It's documented in
`docs/superpowers/plans/2026-05-31-weekly-incremental-ci.md` (created
alongside this plan) so the dev can pick it up next. Summary of what that
plan covers:

1. New scheduled GitLab pipeline (`schedules: weekly`) that runs:
   ```yaml
   incremental-fetch:
     image: python:3.12-slim
     script:
       - pip install -e .
       - bugdb fetch -o assets/bugdb.json --incremental
                     --manifest assets/bugdb.manifest.json
                     --no-progress -l assets/bugdb.log
       - git add assets/bugdb.json assets/bugdb.manifest.json
       - git commit -m "chore(data): weekly incremental refresh" || echo "no changes"
       - git push origin HEAD:develop
     rules:
       - if: '$CI_PIPELINE_SOURCE == "schedule"'
   ```
2. CI image becomes `python:3.12-slim` (no `playwright install --with-deps
   chromium` step) — saves ~30-60 s and ~150 MB of cache per job.
3. Pages deploy stage unchanged; it just consumes the refreshed
   `assets/bugdb.json`.
4. A separate monthly cron-driven *full* refresh job (also via `bugdb
   fetch -f`, no incremental, no manifest) catches republished pages
   whose `<lastmod>` lied.
5. Token + branch-protection notes (write access scoped to the
   `assets/bugdb*.json` paths only via a custom CI-only project token
   instead of letting the runner push as a maintainer).

---

## Self-review

**Spec coverage:**
- ✅ B (replace Playwright with httpx + FluidTopics): Phases 1-4
- ✅ Iterate until new ≥ old: Phase 6
- ✅ C (sitemap-driven incremental in CI): Phase 5 wires manifest; Phase 8
  documents the CI integration plan

**Placeholder scan:** no `TODO`/`TBD`. Plan steps Task 10 lists 11
products; the body explicitly says "follow the PAN-OS pattern" and gives
the same 4-step template for each rather than repeating the code 11
times. That's the one place the plan abbreviates — acceptable because each
product is a near-identical copy of Task 9.

**Type consistency:** `FetchedPage(url, status_code, html, lastmod)`,
`SitemapEntry(url, lastmod, product_id, major_version, is_issue_page)`,
`ManifestEntry(lastmod)`, `FetchManifest.should_skip(url, lastmod)`,
`FetchManifest.record(url, lastmod)`, `Transport.fetch(url) -> FetchedPage`,
`Transport.aclose()`. All referenced consistently in tests and
implementations.

**Risks called out:**
- Sitemap might drift (lastmod lies) → mitigated by the monthly full refresh
  (Phase 8) and the optional content-hash short-circuit can be added later.
- Cortex FluidTopics maps may have multiple "Release Notes" maps per
  agent — the topic title filter in Task 12 (`if "Release Notes" in
  title`) is intentionally loose; Phase 6 will catch over-pruning via the
  parity check.
- Sitemap entries that 404 are silently dropped by `HttpxDocsTransport`'s
  return-non-200 path; the crawler's `_crawl_versions_parallel` already
  treats 404 as a non-fatal per-URL failure and records it in
  `failed_fetches`.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-31-sitemap-httpx-fetch.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
