"""Strata Cloud Manager (SCM) crawler implementation."""

import asyncio
import logging
import re

from bugdb.models import Issue, Product, ProductVersion

from ..base import BaseCrawler
from ..models import CrawlResult, FailedFetch
from ..utils import (
    extract_affected_components,
    extract_cell_text_with_tables,
    extract_fix_info_from_description,
    extract_workaround,
)

logger = logging.getLogger(__name__)


class SCMCrawler(BaseCrawler):
    """Crawler for Strata Cloud Manager release notes.

    SCM is a SaaS service with versioned releases like 2025.r5.0.
    """

    product_id = "scm"
    product_name = "Strata Cloud Manager"

    def _parse_adem_date(self, text: str) -> str | None:
        """Parse a date string (shared with ADEM format)."""
        text = text.strip()

        months = {
            "january": "01",
            "february": "02",
            "march": "03",
            "april": "04",
            "may": "05",
            "june": "06",
            "july": "07",
            "august": "08",
            "september": "09",
            "october": "10",
            "november": "11",
            "december": "12",
        }

        match = re.match(r"^([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})$", text)
        if match:
            month_name = match.group(1).lower()
            day = match.group(2).zfill(2)
            year = match.group(3)
            if month_name in months:
                return f"{year}-{months[month_name]}-{day}"

        match = re.match(r"^([A-Za-z]+)\s+(\d{4})$", text)
        if match:
            month_name = match.group(1).lower()
            year = match.group(2)
            if month_name in months:
                return f"{year}-{months[month_name]}-01"

        match = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", text)
        if match:
            return text

        return None

    def _scm_version_sort_key(self, version: str) -> tuple:
        """Create a sort key for SCM version strings."""
        if version in ("Unknown", "SaaS"):
            return (0, 0, 0)

        match = re.match(r"(\d{4})\.r(\d+)\.(\d+)", version)
        if match:
            return (int(match.group(1)), int(match.group(2)), int(match.group(3)))

        return (0, 0, 0)

    def _parse_scm_known_issues_page(self, soup) -> dict[str, list[Issue]]:
        """Parse SCM known issues page organized by component."""
        results: dict[str, list[Issue]] = {}
        current_component: str | None = None

        component_pattern = re.compile(r"^(.*?)\s*Known\s*Issues?$", re.IGNORECASE)

        for element in soup.find_all(["h2", "h3", "h4", "table"]):
            if element.name in ["h2", "h3", "h4"]:
                header_text = element.get_text(strip=True)

                comp_match = component_pattern.match(header_text)
                if comp_match:
                    component_name = comp_match.group(1).strip()
                    if component_name:
                        current_component = component_name
                        logger.debug("Found SCM component: %s", current_component)
                    continue

            elif element.name == "table":
                if element.find_parent("table"):
                    continue

                issues = self._parse_issues_table(element)

                if current_component:
                    for issue in issues:
                        if issue.affected_components:
                            if current_component not in issue.affected_components:
                                issue.affected_components.append(current_component)
                        else:
                            issue.affected_components = [current_component]

                if issues:
                    if "SaaS" not in results:
                        results["SaaS"] = []
                    results["SaaS"].extend(issues)

        return results

    def _parse_scm_multitenant_known_issues_page(self, soup) -> list[Issue]:
        """Parse SCM multitenant known issues page."""
        issues: list[Issue] = []

        for table in soup.find_all("table"):
            if table.find_parent("table"):
                continue

            table_issues = self._parse_issues_table(table)

            for issue in table_issues:
                issue.affected_components = ["Strata Multitenant Cloud Manager"]

            issues.extend(table_issues)

        return issues

    def _parse_scm_addressed_issues_page(self, soup) -> dict[str, list[Issue]]:
        """Parse SCM addressed issues page organized by version and component."""
        results: dict[str, list[Issue]] = {}
        current_version = "Unknown"
        current_component: str | None = None
        current_release_date: str | None = None

        version_pattern = re.compile(r"(\d{4}\.r\d+\.\d+)")

        component_keywords = [
            "Configuration Management",
            "Command Center",
            "Insights",
            "Activity",
            "Health",
            "Incidents",
            "Policy",
            "Tenancy",
            "Identity",
            "Objects",
            "Workflows",
            "Network",
            "SASE",
        ]

        for element in soup.find_all(["h2", "h3", "h4", "p", "table"]):
            if element.name in ["h2", "h3", "h4"]:
                header_text = element.get_text(strip=True)

                version_match = version_pattern.search(header_text)
                if version_match:
                    current_version = version_match.group(1)
                    current_component = None
                    current_release_date = None
                    logger.debug("Found SCM version: %s", current_version)
                    continue

                date_match = self._parse_adem_date(header_text)
                if date_match:
                    if current_version == "Unknown" or not version_pattern.search(header_text):
                        current_release_date = date_match
                        current_version = "Unknown"
                    logger.debug("Found SCM release date: %s", date_match)
                    continue

                for comp in component_keywords:
                    if comp.lower() in header_text.lower():
                        current_component = comp
                        logger.debug("Found SCM component: %s", current_component)
                        break

            elif element.name == "table":
                if element.find_parent("table"):
                    continue

                # Try to parse the main SCM table format
                issues = self._parse_scm_main_addressed_table(element, results)

                if not issues:
                    issues = self._parse_issues_table(element)

                    if current_component:
                        for issue in issues:
                            if issue.affected_components:
                                if current_component not in issue.affected_components:
                                    issue.affected_components.append(current_component)
                            else:
                                issue.affected_components = [current_component]

                    if current_release_date:
                        for issue in issues:
                            issue.release_date = current_release_date

                    if issues:
                        if current_version not in results:
                            results[current_version] = []
                        results[current_version].extend(issues)

        return results

    def _parse_scm_main_addressed_table(self, table, results: dict[str, list[Issue]]) -> bool:
        """Parse the main SCM addressed issues table with various bug ID formats."""
        headers = []
        thead = table.find("thead")
        if thead:
            headers = [th.get_text(strip=True).lower() for th in thead.find_all("th")]
        else:
            first_row = table.find("tr")
            if first_row:
                headers = [th.get_text(strip=True).lower() for th in first_row.find_all("th")]

        if headers and any(h.strip() for h in headers):
            return False

        tbody = table.find("tbody")
        if tbody:
            rows = tbody.find_all("tr", recursive=False)
        else:
            rows = table.find_all("tr", recursive=False)
            if not rows:
                rows = table.find_all("tr")
            if rows and rows[0].find("th"):
                rows = rows[1:]

        version_pattern = re.compile(r"^([A-Z]+-\d+)(\d{4}\.r\d+\.\d+)$")
        date_pattern = re.compile(r"^([A-Z]+-\d+)([A-Z][a-z]+\s+\d{4})$")
        bug_only_pattern = re.compile(r"^([A-Z]+-\d+)$")

        parsed_any = False
        for row in rows:
            cells = row.find_all(["td", "th"], recursive=False)
            if len(cells) < 2:
                continue

            raw_id = cells[0].get_text(strip=True)
            raw_description = extract_cell_text_with_tables(cells[1])

            bug_id = None
            version = "Unknown"
            release_date = None

            match = version_pattern.match(raw_id)
            if match:
                bug_id = match.group(1)
                version = match.group(2)
            else:
                match = date_pattern.match(raw_id)
                if match:
                    bug_id = match.group(1)
                    date_str = match.group(2)
                    release_date = self._parse_adem_date(date_str)
                else:
                    match = bug_only_pattern.match(raw_id)
                    if match:
                        bug_id = match.group(1)

            if not bug_id:
                continue

            description, workaround = extract_workaround(raw_description)
            description, fix_info = extract_fix_info_from_description(description, None)
            description, affected_components = extract_affected_components(description)

            issue = Issue(
                bug_id=bug_id,
                description=description,
                workaround=workaround,
                fix_info=fix_info,
                affected_components=affected_components,
                release_date=release_date,
            )

            if version not in results:
                results[version] = []
            results[version].append(issue)
            parsed_any = True

        return parsed_any

    async def crawl(
        self,
        major_versions: list[str] | None = None,
        skip_versions: set[str] | None = None,
    ) -> CrawlResult:
        """Crawl Strata Cloud Manager release notes.

        Returns:
            CrawlResult with Product and any failed fetches.
        """
        logger.info("Crawling Strata Cloud Manager...")
        self._set_task_total(1, f"{self.product_name}: fetching")

        known_issues_url = "/strata-cloud-manager/release-notes/known-issues"
        addressed_issues_url = "/strata-cloud-manager/release-notes/addressed-issues"
        multitenant_known_issues_url = (
            "/sase/prisma-sase-multitenant-platform/release-updates/known-issues-msp"
        )
        failed_fetches: list[FailedFetch] = []

        fetch_tasks = [
            self._fetch_page_with_semaphore(known_issues_url),
            self._fetch_page_with_semaphore(addressed_issues_url),
            self._fetch_page_with_semaphore(multitenant_known_issues_url),
        ]
        results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        known_by_version: dict[str, list[Issue]] = {}
        addressed_by_version: dict[str, list[Issue]] = {}

        if not isinstance(results[0], Exception):
            known_by_version = self._parse_scm_known_issues_page(results[0])
            total_known = sum(len(issues) for issues in known_by_version.values())
            logger.info(f"  Found {total_known} known issues")
        else:
            logger.error(f"Error fetching known issues: {results[0]}")
            failed_fetches.append(
                FailedFetch(
                    url=known_issues_url,
                    error=str(results[0]),
                    product=self.product_id,
                    issue_type="known",
                )
            )

        if not isinstance(results[2], Exception):
            multitenant_issues = self._parse_scm_multitenant_known_issues_page(results[2])
            if multitenant_issues:
                if "SaaS" not in known_by_version:
                    known_by_version["SaaS"] = []
                known_by_version["SaaS"].extend(multitenant_issues)
                logger.info(f"  Found {len(multitenant_issues)} multitenant known issues")
        else:
            logger.error(f"Error fetching multitenant known issues: {results[2]}")
            failed_fetches.append(
                FailedFetch(
                    url=multitenant_known_issues_url,
                    error=str(results[2]),
                    product=self.product_id,
                    issue_type="known",
                )
            )

        if not isinstance(results[1], Exception):
            addressed_by_version = self._parse_scm_addressed_issues_page(results[1])
            total_addressed = sum(len(issues) for issues in addressed_by_version.values())
            logger.info(f"  Found {total_addressed} addressed issues")
        else:
            logger.error(f"Error fetching addressed issues: {results[1]}")
            failed_fetches.append(
                FailedFetch(
                    url=addressed_issues_url,
                    error=str(results[1]),
                    product=self.product_id,
                    issue_type="addressed",
                )
            )

        if failed_fetches:
            _, still_failed = await self._retry_failed_fetches_sequentially(failed_fetches)
            failed_fetches = still_failed

        all_versions_set = set(known_by_version.keys()) | set(addressed_by_version.keys())
        all_product_versions = []

        for ver in all_versions_set:
            known = self._deduplicate_issues(known_by_version.get(ver, []))
            addressed = self._deduplicate_issues(addressed_by_version.get(ver, []))

            if known or addressed:
                all_product_versions.append(
                    ProductVersion(
                        version=ver,
                        known_issues=known,
                        addressed_issues=addressed,
                    )
                )

        all_product_versions.sort(
            key=lambda v: self._scm_version_sort_key(v.version),
            reverse=True,
        )

        self._advance_task(f"{self.product_name}: done")

        return CrawlResult(
            product=Product(
                id=self.product_id,
                name=self.product_name,
                versions=all_product_versions,
            ),
            failed_fetches=failed_fetches,
        )
