"""Cortex XDR Agent crawler implementation.

Palo Alto migrated the Cortex documentation from FluidTopics
(``docs-cortex.paloaltonetworks.com``, which exposed a JSON "khub" API) to
GitBook (``cortex-docs.paloaltonetworks.com``). The old API is gone — it
301s to the new site's root and the new host 404s on the API path — so the
crawler now works entirely off the new site:

* **Discovery is sitemap-driven and two-level.** ``/sitemap.xml`` is a
  sitemap *index* listing one ``sitemap-pages.xml`` per GitBook "space".
  Each agent release-notes space holds the pages for one agent version.
  Slugs differ wildly between versions, so page URLs are always read out of
  the space's own ``sitemap-pages.xml`` and classified by looking for
  ``known`` / ``addressed`` in the path — never built from a template.
* **Tables are ARIA divs.** GitBook renders tables as ``div`` elements with
  ``role="table"`` / ``role="row"`` / ``role="cell"``. There is not a single
  ``<table>`` tag on these pages, so the shared ``_parse_issues_table``
  helpers cannot see them and this module carries its own parser.
* **Pages are fully server-rendered**, so plain httpx is enough and
  Playwright is never needed.
"""

from __future__ import annotations

import asyncio
import logging
import re

from bs4 import BeautifulSoup

from bugdb.models import Issue, Product, ProductVersion

from ..base import BaseCrawler
from ..models import CrawlResult, FailedFetch
from ..utils import CORTEX_BASE_URL, extract_workaround

logger = logging.getLogger(__name__)


# GitBook spaces that hold Cortex XDR *agent* release notes. Matched against
# the space path (the sitemap-index entry minus host and trailing
# "sitemap-pages.xml"). Four shapes exist today:
#   xdr-agent-release-notes[/9.2|/9.1-ce]   current releases
#   7.x, 8.x[/8.1-eol|/8.3ce|/7.5ce-eol]    EoL and CE releases
#   5.0, 6.1-eol                            standalone Traps-era spaces
# Everything else on the host — XSIAM, XSOAR, Cortex Cloud, the agent admin
# guides under cortex-xdr-agent/<v>, the iOS/Android guides — is skipped.
_SPACE_RE = re.compile(
    r"^(?:xdr-agent-release-notes|\d+\.x|\d+\.\d+(?:-?ce)?(?:-eol)?)(?:/|$)",
    re.IGNORECASE,
)

# A space path segment that names a version: "9.2", "8.1-eol", "8.3ce",
# "7.5ce-eol", "9.1-ce".
_SPACE_VERSION_RE = re.compile(r"^(\d+\.\d+)(-?ce)?$", re.IGNORECASE)

# Version as spelled in the <title> of a space's root page, e.g.
# "Cortex XDR Agent 9.3 Release Information | Cortex Documentation Portal".
_TITLE_VERSION_RE = re.compile(r"Agent\s+(\d+\.\d+)(\s*-?\s*CE)?\b", re.IGNORECASE)

_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")

_BUG_ID_RE = re.compile(r"[A-Z][A-Z0-9]*-\d+")

# Palo Alto sometimes spells bug ids with a non-breaking hyphen, an en dash
# or an em dash. The characters in the class below are intentional.
_DASH_RE = re.compile(r"[‑–—]")  # noqa: RUF001

# Cell texts that mark a header row on spaces whose header cells carry
# role="cell" instead of role="columnheader".
_HEADER_WORDS = frozenset(
    {
        "issue",
        "issues",
        "issue id",
        "bug",
        "bug id",
        "id",
        "description",
        "details",
        "limitation",
        "limitations",
        "platform",
        "platforms",
        "summary",
    }
)

# Parenthesised platform tags used inside the ISSUE cell, e.g.
# "CPATR-21870 (Windows)".
_PLATFORM_MAP = {
    "windows": "Windows",
    "linux": "Linux",
    "macos": "macOS",
    "mac": "macOS",
    "android": "Android",
    "ios": "iOS",
}

# PLATFORM column values that mean "not platform specific".
_NON_PLATFORMS = frozenset({"general", "all", "n/a", "-", ""})


def _cortex_version_sort_key(version: str) -> tuple[int, int, int]:
    """Sort key for Cortex agent versions like "9.2", "8.3-CE", "5.0".

    The shared :func:`version_sort_key` expects a three-part version and
    collapses every "major.minor" string to ``(0, 0, 0, 0)``, which would
    leave the version list in arbitrary order. CE releases sort just after
    the matching mainline release.
    """
    match = re.match(r"(\d+)\.(\d+)", version)
    if not match:
        return (0, 0, 0)
    return (int(match.group(1)), int(match.group(2)), 1 if "CE" in version.upper() else 0)


class CortexXDRCrawler(BaseCrawler):
    """Crawler for Cortex XDR Agent release notes on the GitBook docs site."""

    product_id = "cortex-xdr"
    product_name = "Cortex XDR Agent"

    def _needs_browser(self) -> bool:
        # The GitBook docs site is fully server-rendered, so this crawler
        # only ever fetches through httpx (see the module docstring) and
        # never touches Playwright, even with no transport injected.
        return False

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def _space_sitemap_urls(self, index_xml: str) -> list[str]:
        """Return the per-space ``sitemap-pages.xml`` URLs worth crawling.

        Args:
            index_xml: Body of ``/sitemap.xml`` (a sitemap index).

        Returns:
            Sitemap URLs for the Cortex XDR agent release-notes spaces, in
            the order the index lists them.
        """
        urls = []
        for loc in _LOC_RE.findall(index_xml):
            path = self._space_path(loc)
            if path and _SPACE_RE.match(path):
                urls.append(loc)
        return urls

    @staticmethod
    def _space_path(sitemap_url: str) -> str:
        """Reduce a space's sitemap URL to its path, e.g. ``8.x/8.1-eol``."""
        path = sitemap_url.split("://", 1)[-1]
        path = path.split("/", 1)[1] if "/" in path else ""
        return path.removesuffix("sitemap-pages.xml").strip("/")

    def _page_urls(self, pages_xml: str) -> list[str]:
        """Return every page URL listed in a space's ``sitemap-pages.xml``."""
        return _LOC_RE.findall(pages_xml)

    def _classify_page(self, url: str) -> str | None:
        """Classify a page URL as ``"known"``, ``"addressed"`` or ``None``.

        Slugs are inconsistent across versions — ``addressed-issues-92``,
        ``addressed-issues-in-cortex-xdr-agent-8.1.x`` and
        ``cortex-xdr-agent-known-limitations`` all coexist — so this matches
        the substrings ``known`` and ``addressed`` case-insensitively rather
        than any exact slug.
        """
        lowered = url.lower()
        if "known" in lowered:
            return "known"
        if "addressed" in lowered:
            return "addressed"
        return None

    def _drop_index_pages(self, pages: list[tuple[str, str]]) -> list[tuple[str, str]]:
        """Drop index/TOC pages that only link to child topic pages.

        Some spaces (e.g. ``9.2``) hold an index page like
        ``.../addressed-issues`` that carries no table at all — it just
        links to real content pages beneath it, such as
        ``.../addressed-issues/addressed-issues-92`` and
        ``.../addressed-issues/addressed-issues-92-hotfix``. Fetching the
        index yields zero issues and would otherwise be misreported as a
        genuine parser gap (see :meth:`_crawl_version_pages`).

        A discovered page is an index only when another discovered page's
        path sits strictly beneath it, compared on ``/``-delimited path
        segments so that ``.../addressed-issues`` is not mistaken for a
        prefix of the sibling ``.../addressed-issues-92`` (no segment
        boundary between them). Other spaces (e.g. ``8.1-eol``) have no
        child page at all for their issue page — that page is the leaf
        content itself and must be kept even though it's alone.

        This mirrors the "known-and-addressed" landing-page convention in
        ``sitemap_discovery.group_into_version_infos`` for the main docs
        site, adapted to the Cortex GitBook URL shapes.
        """
        segments = {url: url.rstrip("/").split("/") for url, _ in pages}

        def is_index(url: str) -> bool:
            segs = segments[url]
            return any(
                other != url and other_segs[: len(segs)] == segs
                for other, other_segs in segments.items()
            )

        return [(url, page_type) for url, page_type in pages if not is_index(url)]

    def _version_from_space_path(self, space_path: str) -> str | None:
        """Derive the agent version from a space path, if it carries one.

        ``8.x``, ``7.x`` and the bare ``xdr-agent-release-notes`` root hold
        the newest release of their line and name no version; those are
        resolved from the space's root page instead
        (:meth:`_version_from_space_root`).
        """
        segment = space_path.rstrip("/").rsplit("/", 1)[-1]
        segment = re.sub(r"-eol$", "", segment, flags=re.IGNORECASE)
        match = _SPACE_VERSION_RE.match(segment)
        if not match:
            return None
        return match.group(1) + ("-CE" if match.group(2) else "")

    def _version_from_space_root(self, html: str) -> str | None:
        """Derive the agent version from a space root page's ``<title>``.

        Root pages are titled e.g. "Cortex XDR Agent 9.3 Release
        Information | Cortex Documentation Portal".
        """
        title = re.search(r"<title>([^<]*)</title>", html, re.IGNORECASE)
        if not title:
            return None
        match = _TITLE_VERSION_RE.search(title.group(1))
        if not match:
            return None
        return match.group(1) + ("-CE" if match.group(2) else "")

    # ------------------------------------------------------------------
    # ARIA table parsing
    # ------------------------------------------------------------------

    def _parse_aria_issue_tables(self, soup: BeautifulSoup) -> list[Issue]:
        """Extract issues from every ARIA table on a GitBook page.

        GitBook emits ``<div role="table">`` containing ``role="row"`` and
        ``role="cell"`` descendants. Column headers are usually
        ``role="columnheader"``, but older spaces put the header text in an
        ordinary first row of ``role="cell"`` divs — both shapes are
        handled.

        Rows whose ISSUE cell holds no bug id are dropped. On known-issues
        pages most rows are feature/category names ("Windows on ARM") rather
        than bug ids, so this guard is what keeps them out of the database.
        """
        issues: list[Issue] = []
        for table in soup.find_all(attrs={"role": "table"}):
            if table.find_parent(attrs={"role": "table"}):
                continue
            issues.extend(self._parse_aria_table(table))
        return issues

    def _parse_aria_table(self, table) -> list[Issue]:
        rows = [
            row
            for row in table.find_all(attrs={"role": "row"})
            if row.find_parent(attrs={"role": "table"}) is table
        ]
        headers = [
            cell.get_text(" ", strip=True).lower()
            for cell in table.find_all(attrs={"role": "columnheader"})
            if cell.find_parent(attrs={"role": "table"}) is table
        ]
        if not headers and rows:
            first = [
                cell.get_text(" ", strip=True).lower()
                for cell in rows[0].find_all(attrs={"role": "cell"})
            ]
            if first and all(text in _HEADER_WORDS for text in first):
                headers = first
                rows = rows[1:]

        issue_col = desc_col = platform_col = None
        for index, header in enumerate(headers):
            if "platform" in header:
                platform_col = index
            elif "issue" in header or "bug" in header or header == "id":
                issue_col = index
            elif any(
                word in header for word in ("description", "limitation", "details", "summary")
            ):
                desc_col = index

        issues: list[Issue] = []
        for row in rows:
            cells = row.find_all(attrs={"role": "cell"})
            if not cells:
                continue
            i_col = 0 if issue_col is None else issue_col
            if i_col >= len(cells):
                continue
            d_col = desc_col
            if d_col is None:
                d_col = len(cells) - 1 if len(cells) > 1 else None

            issues.extend(
                self._issues_from_aria_row(
                    cells[i_col],
                    cells[d_col] if d_col is not None and d_col < len(cells) else None,
                    cells[platform_col]
                    if platform_col is not None and platform_col < len(cells)
                    else None,
                )
            )
        return issues

    def _issues_from_aria_row(self, issue_cell, desc_cell, platform_cell) -> list[Issue]:
        """Build zero or more issues from one ARIA row's cells."""
        raw = _DASH_RE.sub("-", issue_cell.get_text(" ", strip=True))

        # Parenthesised platform tags ride along in the ISSUE cell on the
        # older spaces: "CPATR-21870 (Windows)".
        components: list[str] = []
        for group in re.findall(r"\(([^)]*)\)", raw):
            mapped = _PLATFORM_MAP.get(group.strip().lower())
            if mapped and mapped not in components:
                components.append(mapped)
        stripped = re.sub(r"\([^)]*\)", " ", raw)

        bug_ids = _BUG_ID_RE.findall(stripped)
        if not bug_ids:
            logger.debug("Skipping ARIA row without a bug id: %r", raw[:80])
            return []

        # Anything after the last id is trailing fix information, e.g.
        # "CPATR-10688 This issue is resolved in Cortex XDR agent 7.0.3".
        tail = stripped[stripped.rfind(bug_ids[-1]) + len(bug_ids[-1]) :]
        tail = re.sub(r"\s+", " ", tail).strip(" ,;:.-")
        fix_info = tail if re.search(r"[A-Za-z]{3}", tail) else None

        if platform_cell is not None:
            platform = platform_cell.get_text(" ", strip=True)
            for part in platform.split(","):
                part = part.strip()
                if not part or part.lower() in _NON_PLATFORMS:
                    continue
                mapped = _PLATFORM_MAP.get(part.lower(), part)
                if mapped not in components:
                    components.append(mapped)

        raw_description = desc_cell.get_text(" ", strip=True) if desc_cell is not None else ""
        raw_description = re.sub(r"\s+", " ", raw_description).strip()
        description, workaround = extract_workaround(raw_description)

        return [
            Issue(
                bug_id=bug_id,
                description=description or raw_description,
                workaround=workaround,
                fix_info=fix_info,
                affected_components=components or None,
            )
            for bug_id in bug_ids
        ]

    # ------------------------------------------------------------------
    # Crawl
    # ------------------------------------------------------------------

    async def crawl(
        self,
        major_versions: list[str] | None = None,
        skip_versions: set[str] | None = None,
    ) -> CrawlResult:
        """Crawl Cortex XDR Agent release notes from the GitBook docs site.

        Args:
            major_versions: Unused. The registry never passes it for Cortex —
                the sitemap index is a single cheap request that yields every
                version, so there is nothing to narrow.
            skip_versions: Versions already present in the database. Filtered
                out right after discovery, before any page is fetched.
        """
        del major_versions
        skip_versions = skip_versions or set()
        failed_fetches: list[FailedFetch] = []
        transport = self._transport
        own_transport = None
        if transport is None:
            # No transport injected (direct instantiation, or the legacy
            # `--use-browser` flag). The GitBook site is fully server
            # rendered, so httpx is always the right client here.
            from bugdb.transport.httpx_transport import HttpxDocsTransport

            own_transport = transport = HttpxDocsTransport(concurrency=self.max_concurrency)

        try:
            versions, failed_fetches = await self._discover(transport, skip_versions)
            self._set_task_total(
                len(versions),
                f"{self.product_name}: fetching {len(versions)} versions",
            )

            sorted_versions = sorted(versions.items())
            results = await asyncio.gather(
                *(
                    self._crawl_version_pages(transport, version, pages)
                    for version, pages in sorted_versions
                ),
                return_exceptions=True,
            )
        finally:
            if own_transport is not None:
                await own_transport.aclose()

        product_versions: list[ProductVersion] = []
        for (version, pages), outcome in zip(sorted_versions, results, strict=True):
            if isinstance(outcome, Exception):
                logger.warning("Cortex version %s failed: %s", version, outcome)
                failed_fetches.append(
                    FailedFetch(
                        url=pages[0][0] if pages else f"{CORTEX_BASE_URL}/{version}",
                        error=str(outcome),
                        product=self.product_id,
                        version=version,
                    )
                )
                continue
            product_version, version_failures = outcome
            failed_fetches.extend(version_failures)
            if product_version is not None:
                product_versions.append(product_version)

        product_versions.sort(key=lambda v: _cortex_version_sort_key(v.version), reverse=True)

        return CrawlResult(
            product=Product(
                id=self.product_id,
                name=self.product_name,
                versions=product_versions,
            ),
            failed_fetches=failed_fetches,
        )

    async def _discover(
        self, transport, skip_versions: set[str]
    ) -> tuple[dict[str, list[tuple[str, str]]], list[FailedFetch]]:
        """Map each agent version to its ``(page_url, page_type)`` pairs."""
        failed_fetches: list[FailedFetch] = []
        index_url = f"{CORTEX_BASE_URL}/sitemap.xml"
        self._log("Crawling Cortex XDR Agent release notes (GitBook)...")

        try:
            index_xml = await self._fetch_body(transport, index_url)
        except Exception as exc:
            self._log(f"  Error fetching the Cortex sitemap index: {exc}")
            failed_fetches.append(
                FailedFetch(
                    url=index_url,
                    error=str(exc),
                    product=self.product_id,
                    issue_type="sitemap",
                )
            )
            return {}, failed_fetches

        sitemap_urls = self._space_sitemap_urls(index_xml)
        self._log(f"  Found {len(sitemap_urls)} Cortex XDR agent release-notes spaces")

        space_results = await asyncio.gather(
            *(self._resolve_space(transport, url) for url in sitemap_urls),
            return_exceptions=True,
        )

        versions: dict[str, list[tuple[str, str]]] = {}
        for sitemap_url, outcome in zip(sitemap_urls, space_results, strict=True):
            if isinstance(outcome, Exception):
                logger.warning("Cortex space %s failed: %s", sitemap_url, outcome)
                failed_fetches.append(
                    FailedFetch(
                        url=sitemap_url,
                        error=str(outcome),
                        product=self.product_id,
                        issue_type="sitemap",
                    )
                )
                continue
            version, pages = outcome
            if version is None:
                logger.warning("Could not resolve a version for Cortex space %s", sitemap_url)
                continue
            if version in skip_versions:
                logger.info("  Skipping existing version: %s", version)
                continue
            versions.setdefault(version, []).extend(pages)

        return versions, failed_fetches

    async def _resolve_space(
        self, transport, sitemap_url: str
    ) -> tuple[str | None, list[tuple[str, str]]]:
        """Return ``(version, [(page_url, page_type), ...])`` for one space."""
        space_path = self._space_path(sitemap_url)
        pages_xml = await self._fetch_body(transport, sitemap_url)

        pages = [
            (url, page_type)
            for url in self._page_urls(pages_xml)
            if (page_type := self._classify_page(url)) is not None
        ]
        pages = self._drop_index_pages(pages)
        if not pages:
            return None, []

        version = self._version_from_space_path(space_path)
        if version is None:
            root_html = await self._fetch_body(transport, f"{CORTEX_BASE_URL}/{space_path}")
            version = self._version_from_space_root(root_html)
        return version, pages

    async def _crawl_version_pages(
        self, transport, version: str, pages: list[tuple[str, str]]
    ) -> tuple[ProductVersion | None, list[FailedFetch]]:
        """Fetch and parse every issue page belonging to one version."""
        failed_fetches: list[FailedFetch] = []
        known: list[Issue] = []
        addressed: list[Issue] = []

        try:
            bodies = await asyncio.gather(
                *(self._fetch_body(transport, url) for url, _ in pages),
                return_exceptions=True,
            )
            for (url, page_type), body in zip(pages, bodies, strict=True):
                if isinstance(body, Exception):
                    failed_fetches.append(
                        FailedFetch(
                            url=url,
                            error=str(body),
                            product=self.product_id,
                            version=version,
                            issue_type=page_type,
                        )
                    )
                    continue
                issues = self._parse_aria_issue_tables(BeautifulSoup(body, "lxml"))
                if not issues:
                    logger.warning("%s: no issues parsed from %s", version, url)
                    failed_fetches.append(
                        FailedFetch(
                            url=url,
                            error="no issues parsed",
                            product=self.product_id,
                            version=version,
                            issue_type=page_type,
                        )
                    )
                if page_type == "known":
                    known.extend(issues)
                else:
                    addressed.extend(issues)
        finally:
            self._advance_task(f"{self.product_name}: {version} done")

        known = self._deduplicate_issues(known)
        addressed = self._deduplicate_issues(addressed)
        logger.info("%s: %d known, %d addressed", version, len(known), len(addressed))

        if not known and not addressed:
            return None, failed_fetches
        return (
            ProductVersion(version=version, known_issues=known, addressed_issues=addressed),
            failed_fetches,
        )

    async def _fetch_body(self, transport, url: str) -> str:
        """Fetch a URL through the transport and return its body.

        Used for HTML pages *and* for the sitemap XML, which is why this
        returns the raw body rather than a parsed ``BeautifulSoup``.
        """
        page = await transport.fetch(url)
        if page.status_code != 200:
            raise RuntimeError(f"HTTP {page.status_code} for {url}")
        return page.html
