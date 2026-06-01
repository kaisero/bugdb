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
        ...

    async def aclose(self) -> None:
        """Release any held resources (connections, browser, etc.)."""
        ...
