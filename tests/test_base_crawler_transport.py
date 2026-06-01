"""Tests for BaseCrawler's Transport integration."""

import asyncio

import pytest
from bs4 import BeautifulSoup

from bugdb.crawlers.base import BaseCrawler
from bugdb.transport.base import FetchedPage


class _StubTransport:
    def __init__(self, response: FetchedPage):
        self.response = response
        self.calls: list[str] = []
        self.closed = False

    async def fetch(self, url: str) -> FetchedPage:
        self.calls.append(url)
        return self.response

    async def aclose(self) -> None:
        self.closed = True


def test_base_crawler_accepts_injected_transport():
    stub = _StubTransport(FetchedPage(url="", status_code=200, html=""))
    c = BaseCrawler(transport=stub)
    assert c._transport is stub


@pytest.mark.asyncio
async def test_aenter_skips_playwright_when_transport_injected():
    stub = _StubTransport(FetchedPage(url="", status_code=200, html=""))
    async with BaseCrawler(transport=stub) as c:
        assert c._browser is None
        assert c._playwright is None
        assert c._semaphore is not None
    assert stub.closed is True


@pytest.mark.asyncio
async def test_fetch_via_transport_returns_soup_on_200():
    html = (
        "<html><body><table>"
        "<thead><tr><th>Issue ID</th><th>Description</th></tr></thead>"
        "<tbody><tr><td>PAN-1</td><td>x</td></tr></tbody>"
        "</table></body></html>"
    )
    stub = _StubTransport(FetchedPage(url="", status_code=200, html=html))
    async with BaseCrawler(transport=stub, max_concurrency=2) as c:
        soup = await c._fetch_page_with_semaphore("/some/path")
    assert isinstance(soup, BeautifulSoup)
    assert soup.find("table") is not None
    # Absolute URL was assembled from the relative path
    assert stub.calls == ["https://docs.paloaltonetworks.com/some/path"]


@pytest.mark.asyncio
async def test_fetch_via_transport_passes_absolute_urls_through():
    stub = _StubTransport(FetchedPage(url="", status_code=200, html="<html></html>"))
    async with BaseCrawler(transport=stub, max_concurrency=2) as c:
        await c._fetch_page_with_semaphore("https://example.com/x")
    assert stub.calls == ["https://example.com/x"]


@pytest.mark.asyncio
async def test_fetch_via_transport_raises_on_404():
    stub = _StubTransport(FetchedPage(url="", status_code=404, html="not found"))
    async with BaseCrawler(transport=stub, max_concurrency=2) as c:
        with pytest.raises(Exception) as excinfo:
            await c._fetch_page_with_semaphore("/missing")
    assert "404" in str(excinfo.value)


@pytest.mark.asyncio
async def test_fetch_via_transport_retries_on_5xx():
    """503 -> 200 should retry and return content."""

    class FlakyTransport:
        def __init__(self):
            self.calls = 0

        async def fetch(self, url: str) -> FetchedPage:
            self.calls += 1
            if self.calls < 2:
                return FetchedPage(url=url, status_code=503, html="busy")
            return FetchedPage(
                url=url,
                status_code=200,
                html="<html><body>ok</body></html>",
            )

        async def aclose(self) -> None: ...

    t = FlakyTransport()
    async with BaseCrawler(transport=t, max_concurrency=2, retry_delay=0.0) as c:
        soup = await c._fetch_page_with_semaphore("/flaky")
    assert "ok" in soup.text
    assert t.calls == 2


def test_parse_issues_table_handles_inline_div_quirk():
    """The AEM inline-display div wrapping is unwrapped by the parser itself."""
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


def test_parse_issues_table_with_feature_handles_inline_div_quirk():
    html = """
    <table>
      <thead><tr><th>Issue ID</th><th>Description</th></tr></thead>
      <tbody><div style="display: inline;">
        <tr><div style="display: inline;">
          <td>PAN-42</td><td>quirky</td>
        </div></tr>
      </div></tbody>
    </table>
    """
    soup = BeautifulSoup(html, "lxml")
    c = BaseCrawler.__new__(BaseCrawler)
    issues = c._parse_issues_table_with_feature(
        soup.find("table"), feature="Networking"
    )
    assert len(issues) == 1
    assert issues[0].bug_id == "PAN-42"
    assert issues[0].affected_components == ["Networking"]
