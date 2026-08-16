"""Enterprise DLP crawler implementation.

Enterprise DLP has two independent version axes on the docs site:

* **Known issues** are published per plugin release, with the version
  encoded as a run-together digit string on the URL slug —
  ``...-plugin-60`` is 6.0, ``...-plugin-602`` is 6.0.2, and
  ``...-plugin-3010`` is 3.0.10. The shared
  ``extract_dotted_version`` helper cannot read this: it wants exactly
  three digits with no digit neighbours, so the two-digit parent slugs
  and the four-digit ``3010`` both fall through it silently.

* **Addressed issues** are not versioned at all. They live on one page
  with per-year children (``addressed-issues-in-2025``), so they are
  keyed by year — the same approach the Device Security crawler takes.

Both axes land in one Product, so its version list mixes ``6.0.2`` with
``2025``. That is intentional.

Known-issues pages use the ``div.topic`` block format with no issue
table. Addressed-issues year pages are div.topic *sections* too, but
verified against the live site each month's section nests a real
``<table>`` of ID/Description rows rather than per-issue div.topic
blocks — so page parsing goes through the same table-first,
topic-format-fallback path as :meth:`BaseCrawler._parse_issues_page`.
"""

from __future__ import annotations

import asyncio
import logging
import re

from bugdb.models import Issue, Product, ProductVersion

from ..base import BaseCrawler
from ..models import CrawlResult, FailedFetch
from ..sitemap_discovery import to_relative_path

logger = logging.getLogger(__name__)

# <major><minor><patch?> run-together on the final slug segment.
# Anchored to end-of-string so an ancestor segment (".../plugin-60/...")
# never wins over the leaf (".../plugin-602").
_DLP_VERSION_RE = re.compile(r"enterprise-dlp-plugin-(\d)(\d)(\d*)$")
_DLP_YEAR_RE = re.compile(r"addressed-issues-in-(20\d{2})$")

# Non-versioned known-issues pages that share the /enterprise-dlp/
# prefix but describe different products. Deliberately out of scope —
# folding them in would put "Endpoint" or "SaaS" pseudo-versions next to
# 1.0-6.0 and make the site's version filter incoherent.
_OUT_OF_SCOPE = (
    "known-issues-in-endpoint-dlp",
    "known-issues-in-the-enterprise-dlp-cloud-service",
)


def extract_dlp_version(url: str) -> str | None:
    """Return the dotted plugin version encoded in a DLP known-issues URL.

    ``...-plugin-60`` -> ``"6.0"``, ``...-plugin-602`` -> ``"6.0.2"``,
    ``...-plugin-3010`` -> ``"3.0.10"``. Returns None for URLs that do
    not encode a plugin version.

    Assumes a single-digit major. Every shipped major is 1/3/4/5/6; a
    hypothetical 10.x would need this regex widened.
    """
    m = _DLP_VERSION_RE.search(url)
    if not m:
        return None
    major, minor, patch = m.group(1), m.group(2), m.group(3)
    if patch:
        return f"{major}.{minor}.{int(patch)}"
    return f"{major}.{minor}"


def extract_dlp_year(url: str) -> str | None:
    """Return the year encoded in a DLP addressed-issues URL, or None."""
    m = _DLP_YEAR_RE.search(url)
    return m.group(1) if m else None


class EnterpriseDLPCrawler(BaseCrawler):
    """Crawler for Enterprise DLP release notes."""

    product_id = "enterprise-dlp"
    product_name = "Enterprise DLP"

    def discover_urls(self) -> tuple[dict[str, str], dict[str, str]]:
        """Return ``({version: known_path}, {year: addressed_path})``.

        Honours the manifest, drops the out-of-scope pages, and drops
        the undated ``addressed-issues-in-enterprise-dlp`` parent — it
        is a table of contents for its year children, so crawling it
        would duplicate every addressed issue under a bogus key.
        """
        known: dict[str, str] = {}
        addressed: dict[str, str] = {}
        if self._sitemap is None:
            return known, addressed

        for entry in self._sitemap.for_product(self.product_id):
            lower = entry.url.lower()
            if any(marker in lower for marker in _OUT_OF_SCOPE):
                continue
            if self._manifest is not None and self._manifest.should_skip(entry.url, entry.lastmod):
                logger.debug("manifest skip: %s", entry.url)
                continue

            path = to_relative_path(entry.url)
            year = extract_dlp_year(entry.url)
            if year is not None:
                addressed.setdefault(year, path)
                continue
            version = extract_dlp_version(entry.url)
            if version is not None:
                known.setdefault(version, path)

        return known, addressed

    async def _parse_page(self, url: str) -> list[Issue]:
        """Fetch one DLP page and return its issues.

        Known-issues pages have zero tables (pure div.topic blocks) and
        fall through the table pass with nothing to show. Addressed
        year pages nest an ID/Description ``<table>`` inside each
        month's div.topic section, so the table pass is what actually
        parses those. ``_parse_issues_page`` already implements exactly
        this table-first, topic-fallback order.
        """
        return await self._parse_issues_page(url)

    async def crawl(
        self,
        major_versions: list[str] | None = None,
        skip_versions: set[str] | None = None,
    ) -> CrawlResult:
        """Crawl Enterprise DLP release notes.

        Args:
            major_versions: Ignored — versions come from the sitemap.
            skip_versions: Version/year keys already present locally.

        Returns:
            CrawlResult with Product and any failed fetches.
        """
        skip_versions = skip_versions or set()
        failed_fetches: list[FailedFetch] = []

        known_urls, addressed_urls = self.discover_urls()
        known_urls = {k: v for k, v in known_urls.items() if k not in skip_versions}
        addressed_urls = {k: v for k, v in addressed_urls.items() if k not in skip_versions}

        total = len(known_urls) + len(addressed_urls)
        self._set_task_total(
            total,
            f"{self.product_name}: fetching {total} pages"
            if total
            else f"{self.product_name}: nothing new to fetch",
        )

        targets: list[tuple[str, str, str]] = [
            *[(v, path, "known") for v, path in known_urls.items()],
            *[(y, path, "addressed") for y, path in addressed_urls.items()],
        ]
        results = await asyncio.gather(
            *[self._parse_page(path) for _key, path, _kind in targets],
            return_exceptions=True,
        )

        by_key: dict[str, dict[str, list[Issue]]] = {}
        for (key, path, kind), result in zip(targets, results, strict=True):
            self._advance_task(f"{self.product_name}: {key} done")
            if isinstance(result, Exception):
                logger.error("  Error fetching %s (%s): %s", path, kind, result)
                failed_fetches.append(
                    FailedFetch(
                        url=path,
                        error=str(result),
                        product=self.product_id,
                        version=key,
                        issue_type=kind,
                    )
                )
                continue
            bucket = by_key.setdefault(key, {"known": [], "addressed": []})
            bucket[kind].extend(result)
            logger.info("  %s: %d %s issues", key, len(result), kind)

        if failed_fetches:
            _, still_failed = await self._retry_failed_fetches_sequentially(failed_fetches)
            failed_fetches = still_failed

        product_versions = []
        for key, buckets in by_key.items():
            known = self._deduplicate_issues(buckets["known"])
            addressed = self._deduplicate_issues(buckets["addressed"])
            if known or addressed:
                product_versions.append(
                    ProductVersion(
                        version=key,
                        known_issues=known,
                        addressed_issues=addressed,
                    )
                )

        product_versions.sort(key=lambda v: self._version_sort_key(v.version), reverse=True)

        return CrawlResult(
            product=Product(
                id=self.product_id,
                name=self.product_name,
                versions=product_versions,
            ),
            failed_fetches=failed_fetches,
        )
