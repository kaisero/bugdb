"""HTTP transport for docs.paloaltonetworks.com using httpx."""

from __future__ import annotations

import asyncio
import logging

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
        limits = httpx.Limits(
            max_keepalive_connections=concurrency,
            max_connections=concurrency + 5,
        )
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
            last_exc: Exception | None = None
            resp: httpx.Response | None = None
            for attempt in range(self._max_retries):
                try:
                    resp = await self._client.get(url)
                except httpx.HTTPError as exc:
                    last_exc = exc
                    if attempt < self._max_retries - 1:
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
            if resp is not None:
                html = _fix_inline_div_tables(resp.text)
                return FetchedPage(
                    url=str(resp.url),
                    status_code=resp.status_code,
                    html=html,
                )
            assert last_exc is not None
            raise last_exc

    async def _sleep_backoff(self, attempt: int) -> None:
        await asyncio.sleep(self._retry_base_delay * (2**attempt))


def _fix_inline_div_tables(html: str) -> str:
    """Unwrap `<div style="display: inline">` elements inside `<table>`.

    See class docstring for rationale.
    """
    if "display: inline" not in html and "display:inline" not in html:
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
