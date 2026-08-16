"""Transport protocol for fetching release-notes pages."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class FetchedPage:
    """Result of a single page fetch.

    `html` is always the response body as text — usually HTML for the
    BeautifulSoup-based parsers, occasionally XML (sitemaps). `lastmod` is the
    sitemap timestamp if known, None for transports that don't carry one.
    """

    url: str
    status_code: int
    html: str
    lastmod: str | None = None


class Transport(Protocol):
    """Async fetch transport for release-notes pages."""

    async def fetch(self, url: str) -> FetchedPage:
        """Fetch a single URL and return the page."""
        ...

    async def aclose(self) -> None:
        """Release any held resources (connections, browser, etc.)."""
        ...
