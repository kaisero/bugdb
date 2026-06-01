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
    rather than just the bare Transport.fetch protocol because Cortex crawling
    needs traversal, not a flat URL fetch. The bare `fetch` method is still
    implemented so the FluidTopics client is callable from anywhere a Transport
    is expected.
    """

    def __init__(self, *, concurrency: int = 10, timeout: float = 20.0) -> None:
        self._client = httpx.AsyncClient(
            http2=True,
            follow_redirects=False,
            headers=_HEADERS,
            timeout=timeout,
            limits=httpx.Limits(
                max_keepalive_connections=concurrency,
                max_connections=concurrency + 5,
            ),
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
        resp = await self._client.get(
            f"{CORTEX_BASE}/api/khub/maps/{map_id}/topics"
        )
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
