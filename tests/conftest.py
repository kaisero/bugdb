"""Pytest configuration and shared fixtures."""

import asyncio
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bs4 import BeautifulSoup

from bugdb.models import BugDatabase, Issue, Metadata, Product, ProductVersion


# Path to fixtures directory
FIXTURES_DIR = Path(__file__).parent / "fixtures"


class MockPage:
    """Mock Playwright page object that returns HTML from fixtures."""

    def __init__(self, fixtures_dir: Path, url_to_file_mapping: dict[str, str]):
        """Initialize mock page with URL to file mapping.

        Args:
            fixtures_dir: Base directory for fixture files.
            url_to_file_mapping: Dict mapping URL patterns to fixture file paths.
        """
        self.fixtures_dir = fixtures_dir
        self.url_to_file_mapping = url_to_file_mapping
        self._current_content: Optional[str] = None
        self._current_url: Optional[str] = None

    async def goto(self, url: str, wait_until: str = "networkidle") -> None:
        """Simulate navigation to a URL."""
        self._current_url = url
        self._current_content = self._get_content_for_url(url)

    async def wait_for_timeout(self, timeout: int) -> None:
        """Simulate waiting (no-op in tests)."""
        pass

    async def content(self) -> str:
        """Return the current page content."""
        return self._current_content or "<html><head><title>Not Found</title></head><body>404</body></html>"

    async def close(self) -> None:
        """Simulate closing the page."""
        pass

    def _get_content_for_url(self, url: str) -> str:
        """Get fixture content for a URL."""
        # Remove base URL if present
        url = url.replace("https://docs.paloaltonetworks.com", "")

        # Try to find a matching file
        for pattern, filepath in self.url_to_file_mapping.items():
            if pattern in url:
                full_path = self.fixtures_dir / filepath
                if full_path.exists():
                    return full_path.read_text()

        # Return 404 page for unknown URLs
        return "<html><head><title>Page Not Found</title></head><body>404</body></html>"


class MockBrowser:
    """Mock Playwright browser object."""

    def __init__(self, fixtures_dir: Path, url_to_file_mapping: dict[str, str]):
        """Initialize mock browser."""
        self.fixtures_dir = fixtures_dir
        self.url_to_file_mapping = url_to_file_mapping

    async def new_page(self) -> MockPage:
        """Create a new mock page."""
        return MockPage(self.fixtures_dir, self.url_to_file_mapping)

    async def close(self) -> None:
        """Simulate closing the browser."""
        pass


class MockPlaywright:
    """Mock Playwright context manager."""

    def __init__(self, fixtures_dir: Path, url_to_file_mapping: dict[str, str]):
        """Initialize mock playwright."""
        self.fixtures_dir = fixtures_dir
        self.url_to_file_mapping = url_to_file_mapping
        self.chromium = MagicMock()
        self.chromium.launch = AsyncMock(
            return_value=MockBrowser(fixtures_dir, url_to_file_mapping)
        )

    async def start(self):
        """Return self as the playwright instance."""
        return self

    async def stop(self) -> None:
        """Simulate stopping playwright."""
        pass


# URL mappings for GlobalProtect
GLOBALPROTECT_URL_MAPPING = {
    # Index pages
    "/globalprotect/6-2/globalprotect-app-release-notes": "globalprotect/release-notes-index.html",
    "/globalprotect/release-notes/6-2/globalprotect-addressed-issues": "globalprotect/6-2-addressed-issues-index.html",
    "/globalprotect/release-notes/6-2/known-issues-related-to-gp-app": "globalprotect/6-2-known-issues-index.html",
    # Version-specific pages (6.2.x)
    "/6-2-1-known-issues": "globalprotect/6-2-1-known-issues.html",
    "/6-2-1-addressed-issues": "globalprotect/6-2-1-addressed-issues.html",
    # Multi-version pages (6.1.x)
    "/globalprotect/6-1/globalprotect-app-release-notes": "globalprotect/6-1-multi-version-known-issues.html",
    "/globalprotect/release-notes/6-1/globalprotect-addressed-issues": "globalprotect/6-1-multi-version-addressed-issues.html",
    "/globalprotect/release-notes/6-1/known-issues-related-to-gp-app": "globalprotect/6-1-multi-version-known-issues.html",
}

# URL mappings for PAN-OS
PANOS_URL_MAPPING = {
    # NGFW index pages (12.x+)
    "/ngfw/release-notes/12-1/features-introduced-in-pan-os": "panos/12-1-index.html",
    "/ngfw/release-notes/12-1": "panos/12-1-index.html",
    # NGFW version-specific pages
    "/pan-os-12-1-5-known-issues": "panos/12-1-5-known-issues.html",
    "/pan-os-12-1-5-addressed-issues": "panos/12-1-5-addressed-issues.html",
    # PAN-OS index pages (11.x and older)
    "/pan-os/11-2/pan-os-release-notes": "panos/11-2-index.html",
    # PAN-OS version-specific pages
    "/pan-os-11-2-4-known-issues": "panos/11-2-4-known-issues.html",
    "/pan-os-11-2-4-addressed-issues": "panos/11-2-4-addressed-issues.html",
}

# URL mappings for Prisma Access Agent
PRISMA_ACCESS_AGENT_URL_MAPPING = {
    # Index pages
    "/prisma-access-agent-known-issues": "prisma-access-agent/known-issues-index.html",
    "/prisma-access-agent-addressed-issues": "prisma-access-agent/addressed-issues-index.html",
    # Version-specific pages (26.1.x)
    "/prisma-access-agent-26-1-2-known-issues": "prisma-access-agent/26-1-2-known-issues.html",
    "/prisma-access-agent-26-1-2-addressed-issues": "prisma-access-agent/26-1-2-addressed-issues.html",
    # Version-specific pages (25.2.x)
    "/prisma-access-agent-25-2-1-known-issues": "prisma-access-agent/25-2-1-known-issues.html",
    "/prisma-access-agent-25-2-1-addressed-issues": "prisma-access-agent/25-2-1-addressed-issues.html",
}

# Combined URL mapping for all products
ALL_URL_MAPPINGS = {
    **GLOBALPROTECT_URL_MAPPING,
    **PANOS_URL_MAPPING,
    **PRISMA_ACCESS_AGENT_URL_MAPPING,
}


@pytest.fixture
def fixtures_dir() -> Path:
    """Return path to fixtures directory."""
    return FIXTURES_DIR


@pytest.fixture
def globalprotect_url_mapping() -> dict[str, str]:
    """Return URL mapping for GlobalProtect fixtures."""
    return GLOBALPROTECT_URL_MAPPING


@pytest.fixture
def panos_url_mapping() -> dict[str, str]:
    """Return URL mapping for PAN-OS fixtures."""
    return PANOS_URL_MAPPING


@pytest.fixture
def prisma_access_agent_url_mapping() -> dict[str, str]:
    """Return URL mapping for Prisma Access Agent fixtures."""
    return PRISMA_ACCESS_AGENT_URL_MAPPING


@pytest.fixture
def all_url_mappings() -> dict[str, str]:
    """Return URL mapping for all products."""
    return ALL_URL_MAPPINGS


@pytest.fixture
def mock_playwright_globalprotect(fixtures_dir, globalprotect_url_mapping):
    """Create a mock playwright for GlobalProtect testing."""
    return MockPlaywright(fixtures_dir, globalprotect_url_mapping)


@pytest.fixture
def mock_playwright_panos(fixtures_dir, panos_url_mapping):
    """Create a mock playwright for PAN-OS testing."""
    return MockPlaywright(fixtures_dir, panos_url_mapping)


@pytest.fixture
def mock_playwright_prisma(fixtures_dir, prisma_access_agent_url_mapping):
    """Create a mock playwright for Prisma Access Agent testing."""
    return MockPlaywright(fixtures_dir, prisma_access_agent_url_mapping)


@pytest.fixture
def mock_playwright_all(fixtures_dir, all_url_mappings):
    """Create a mock playwright for testing all products."""
    return MockPlaywright(fixtures_dir, all_url_mappings)


@pytest.fixture
def sample_database() -> BugDatabase:
    """Create a sample database for testing."""
    issue = Issue(
        bug_id="PAN-12345",
        description="Test issue description",
        symptoms="Test symptoms",
        workaround="Test workaround",
        affected_components=["Component A", "Component B"],
    )
    version = ProductVersion(
        version="11.1.0",
        release_date="2026-03-01",
        known_issues=[issue],
        addressed_issues=[],
    )
    product = Product(
        id="pan-os",
        name="PAN-OS",
        versions=[version],
    )
    return BugDatabase(
        metadata=Metadata(source="Test Source"),
        products=[product],
    )


@pytest.fixture
def sample_html_with_issues() -> str:
    """Create sample HTML with issues table."""
    return """
    <!DOCTYPE html>
    <html>
    <head><title>Test Issues</title></head>
    <body>
        <h1>Known Issues</h1>
        <table>
            <thead>
                <tr>
                    <th>Issue ID</th>
                    <th>Description</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>TEST-001</td>
                    <td>First test issue</td>
                </tr>
                <tr>
                    <td>TEST-002</td>
                    <td>Second test issue</td>
                </tr>
            </tbody>
        </table>
    </body>
    </html>
    """


@pytest.fixture
def sample_html_multi_version() -> str:
    """Create sample HTML with multiple version sections."""
    return """
    <!DOCTYPE html>
    <html>
    <head><title>Multi-Version Issues</title></head>
    <body>
        <h1>Known Issues</h1>

        <h3>GlobalProtect App 6.1.4 Known Issues</h3>
        <table>
            <thead>
                <tr><th>Issue ID</th><th>Description</th></tr>
            </thead>
            <tbody>
                <tr><td>GPC-001</td><td>Issue for 6.1.4</td></tr>
            </tbody>
        </table>

        <h3>GlobalProtect 6.1.3 Known Issues</h3>
        <table>
            <thead>
                <tr><th>Issue ID</th><th>Description</th></tr>
            </thead>
            <tbody>
                <tr><td>GPC-002</td><td>Issue for 6.1.3</td></tr>
                <tr><td>GPC-003</td><td>Another issue for 6.1.3</td></tr>
            </tbody>
        </table>
    </body>
    </html>
    """


@pytest.fixture
def sample_html_no_issues() -> str:
    """Create sample HTML with no valid issues."""
    return """
    <!DOCTYPE html>
    <html>
    <head><title>No Issues</title></head>
    <body>
        <h1>Release Notes</h1>
        <p>No known issues in this release.</p>
        <table>
            <thead>
                <tr><th>Feature</th><th>Description</th></tr>
            </thead>
            <tbody>
                <tr><td>New Feature</td><td>Some new feature description</td></tr>
            </tbody>
        </table>
    </body>
    </html>
    """


@pytest.fixture
def sample_html_invalid_bug_ids() -> str:
    """Create sample HTML with invalid bug IDs that should be filtered."""
    return """
    <!DOCTYPE html>
    <html>
    <head><title>Invalid Bug IDs</title></head>
    <body>
        <table>
            <thead>
                <tr><th>Issue ID</th><th>Description</th></tr>
            </thead>
            <tbody>
                <tr><td>valid-123</td><td>Lowercase prefix - invalid</td></tr>
                <tr><td>TEST-ABC</td><td>Non-numeric suffix - invalid</td></tr>
                <tr><td>123-456</td><td>Numeric prefix - invalid</td></tr>
                <tr><td>TEST-123</td><td>Valid issue</td></tr>
                <tr><td></td><td>Empty ID - invalid</td></tr>
                <tr><td>ANOTHER-456</td><td>Another valid issue</td></tr>
            </tbody>
        </table>
    </body>
    </html>
    """
