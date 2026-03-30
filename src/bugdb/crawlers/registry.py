"""Product registry and wrapper factory for crawlers."""

import asyncio
from datetime import datetime, timezone
from typing import Optional

from bugdb.models import BugDatabase, Metadata

from .models import FetchResult, PluginConfig
from .products.globalprotect import GlobalProtectCrawler
from .products.panos import PANOSCrawler
from .products.prisma_access import PrismaAccessCrawler
from .products.prisma_access_agent import PrismaAccessAgentCrawler
from .products.prisma_sdwan import PrismaSDWANCrawler
from .products.cloud_ngfw import CloudNGFWAzureCrawler, CloudNGFWAWSCrawler
from .products.saas import (
    RemoteBrowserIsolationCrawler,
    AIRuntimeSecurityCrawler,
    StrataLoggingServiceCrawler,
)
from .products.device_security import DeviceSecurityCrawler
from .products.adem import ADEMCrawler
from .products.scm import SCMCrawler
from .products.sdwan_plugin import SDWANPluginCrawler
from .products.cortex_xdr import CortexXDRCrawler
from .products.plugins import PluginCrawler, PLUGIN_CONFIGS


# Registry of all product crawlers by product ID
PRODUCT_CRAWLERS = {
    "globalprotect": GlobalProtectCrawler,
    "panos": PANOSCrawler,
    "prisma-access": PrismaAccessCrawler,
    "prisma-access-agent": PrismaAccessAgentCrawler,
    "prisma-sdwan": PrismaSDWANCrawler,
    "cloud-ngfw-azure": CloudNGFWAzureCrawler,
    "cloud-ngfw-aws": CloudNGFWAWSCrawler,
    "remote-browser-isolation": RemoteBrowserIsolationCrawler,
    "ai-runtime-security": AIRuntimeSecurityCrawler,
    "strata-logging-service": StrataLoggingServiceCrawler,
    "device-security": DeviceSecurityCrawler,
    "adem": ADEMCrawler,
    "scm": SCMCrawler,
    "sdwan-plugin": SDWANPluginCrawler,
    "cortex-xdr": CortexXDRCrawler,
}

# Add plugin crawlers
for plugin_id in PLUGIN_CONFIGS:
    PRODUCT_CRAWLERS[plugin_id] = PluginCrawler


def get_crawler_class(product_id: str):
    """Get the crawler class for a product ID.

    Args:
        product_id: Product identifier.

    Returns:
        Crawler class.

    Raises:
        KeyError: If product_id is not found.
    """
    return PRODUCT_CRAWLERS[product_id]


# ==============================================================================
# Async wrapper functions for each product
# ==============================================================================

async def _crawl_globalprotect_async(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> FetchResult:
    """Async implementation of GlobalProtect crawler."""
    async with GlobalProtectCrawler(
        headless=headless, verbose=verbose, debug=debug, max_concurrency=max_concurrency
    ) as crawler:
        result = await crawler.crawl(major_versions, skip_versions)

        if major_versions:
            versions_str = ", ".join(v.replace("-", ".") for v in major_versions)
            source = f"Palo Alto Networks GlobalProtect {versions_str} Release Notes"
        else:
            source = "Palo Alto Networks GlobalProtect Release Notes (All Versions)"

        return FetchResult(
            database=BugDatabase(
                metadata=Metadata(
                    generated_at=datetime.now(timezone.utc),
                    version="1.0.0",
                    source=source,
                ),
                products=[result.product],
            ),
            failed_fetches=result.failed_fetches,
        )


async def _crawl_panos_async(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> FetchResult:
    """Async implementation of PAN-OS crawler."""
    async with PANOSCrawler(
        headless=headless, verbose=verbose, debug=debug, max_concurrency=max_concurrency
    ) as crawler:
        result = await crawler.crawl(major_versions, skip_versions)

        if major_versions:
            versions_str = ", ".join(v.replace("-", ".") for v in major_versions)
            source = f"Palo Alto Networks PAN-OS {versions_str} Release Notes"
        else:
            source = "Palo Alto Networks PAN-OS Release Notes (All Versions)"

        return FetchResult(
            database=BugDatabase(
                metadata=Metadata(
                    generated_at=datetime.now(timezone.utc),
                    version="1.0.0",
                    source=source,
                ),
                products=[result.product],
            ),
            failed_fetches=result.failed_fetches,
        )


async def _crawl_prisma_access_async(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> FetchResult:
    """Async implementation of Prisma Access crawler."""
    async with PrismaAccessCrawler(
        headless=headless, verbose=verbose, debug=debug, max_concurrency=max_concurrency
    ) as crawler:
        result = await crawler.crawl(major_versions, skip_versions)

        if major_versions:
            versions_str = ", ".join(v.replace("-", ".") for v in major_versions)
            source = f"Palo Alto Networks Prisma Access {versions_str} Release Notes"
        else:
            source = "Palo Alto Networks Prisma Access Release Notes (All Versions)"

        return FetchResult(
            database=BugDatabase(
                metadata=Metadata(
                    generated_at=datetime.now(timezone.utc),
                    version="1.0.0",
                    source=source,
                ),
                products=[result.product],
            ),
            failed_fetches=result.failed_fetches,
        )


async def _crawl_prisma_access_agent_async(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> FetchResult:
    """Async implementation of Prisma Access Agent crawler."""
    async with PrismaAccessAgentCrawler(
        headless=headless, verbose=verbose, debug=debug, max_concurrency=max_concurrency
    ) as crawler:
        result = await crawler.crawl(major_versions, skip_versions)

        if major_versions:
            versions_str = ", ".join(v.replace("-", ".") for v in major_versions)
            source = f"Palo Alto Networks Prisma Access Agent {versions_str} Release Notes"
        else:
            source = "Palo Alto Networks Prisma Access Agent Release Notes (All Versions)"

        return FetchResult(
            database=BugDatabase(
                metadata=Metadata(
                    generated_at=datetime.now(timezone.utc),
                    version="1.0.0",
                    source=source,
                ),
                products=[result.product],
            ),
            failed_fetches=result.failed_fetches,
        )


async def _crawl_prisma_sdwan_async(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> FetchResult:
    """Async implementation of Prisma SD-WAN crawler."""
    async with PrismaSDWANCrawler(
        headless=headless, verbose=verbose, debug=debug, max_concurrency=max_concurrency
    ) as crawler:
        result = await crawler.crawl(major_versions, skip_versions)

        if major_versions:
            versions_str = ", ".join(v.replace("-", ".") for v in major_versions)
            source = f"Palo Alto Networks Prisma SD-WAN {versions_str} Release Notes"
        else:
            source = "Palo Alto Networks Prisma SD-WAN Release Notes (All Versions)"

        return FetchResult(
            database=BugDatabase(
                metadata=Metadata(
                    generated_at=datetime.now(timezone.utc),
                    version="1.0.0",
                    source=source,
                ),
                products=[result.product],
            ),
            failed_fetches=result.failed_fetches,
        )


async def _crawl_cloud_ngfw_azure_async(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> FetchResult:
    """Async implementation of Cloud NGFW for Azure crawler."""
    async with CloudNGFWAzureCrawler(
        headless=headless, verbose=verbose, debug=debug, max_concurrency=max_concurrency
    ) as crawler:
        result = await crawler.crawl(major_versions, skip_versions)

        return FetchResult(
            database=BugDatabase(
                metadata=Metadata(
                    generated_at=datetime.now(timezone.utc),
                    version="1.0.0",
                    source="Palo Alto Networks Cloud NGFW for Azure Release Notes",
                ),
                products=[result.product],
            ),
            failed_fetches=result.failed_fetches,
        )


async def _crawl_cloud_ngfw_aws_async(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> FetchResult:
    """Async implementation of Cloud NGFW for AWS crawler."""
    async with CloudNGFWAWSCrawler(
        headless=headless, verbose=verbose, debug=debug, max_concurrency=max_concurrency
    ) as crawler:
        result = await crawler.crawl(major_versions, skip_versions)

        return FetchResult(
            database=BugDatabase(
                metadata=Metadata(
                    generated_at=datetime.now(timezone.utc),
                    version="1.0.0",
                    source="Palo Alto Networks Cloud NGFW for AWS Release Notes",
                ),
                products=[result.product],
            ),
            failed_fetches=result.failed_fetches,
        )


async def _crawl_remote_browser_isolation_async(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> FetchResult:
    """Async implementation of Remote Browser Isolation crawler."""
    async with RemoteBrowserIsolationCrawler(
        headless=headless, verbose=verbose, debug=debug, max_concurrency=max_concurrency
    ) as crawler:
        result = await crawler.crawl(major_versions, skip_versions)

        return FetchResult(
            database=BugDatabase(
                metadata=Metadata(
                    generated_at=datetime.now(timezone.utc),
                    version="1.0.0",
                    source="Palo Alto Networks Remote Browser Isolation Release Notes",
                ),
                products=[result.product],
            ),
            failed_fetches=result.failed_fetches,
        )


async def _crawl_ai_runtime_security_async(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> FetchResult:
    """Async implementation of AI Runtime Security crawler."""
    async with AIRuntimeSecurityCrawler(
        headless=headless, verbose=verbose, debug=debug, max_concurrency=max_concurrency
    ) as crawler:
        result = await crawler.crawl(major_versions, skip_versions)

        return FetchResult(
            database=BugDatabase(
                metadata=Metadata(
                    generated_at=datetime.now(timezone.utc),
                    version="1.0.0",
                    source="Palo Alto Networks AI Runtime Security Release Notes",
                ),
                products=[result.product],
            ),
            failed_fetches=result.failed_fetches,
        )


async def _crawl_strata_logging_service_async(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> FetchResult:
    """Async implementation of Strata Logging Service crawler."""
    async with StrataLoggingServiceCrawler(
        headless=headless, verbose=verbose, debug=debug, max_concurrency=max_concurrency
    ) as crawler:
        result = await crawler.crawl(major_versions, skip_versions)

        return FetchResult(
            database=BugDatabase(
                metadata=Metadata(
                    generated_at=datetime.now(timezone.utc),
                    version="1.0.0",
                    source="Palo Alto Networks Strata Logging Service Release Notes",
                ),
                products=[result.product],
            ),
            failed_fetches=result.failed_fetches,
        )


async def _crawl_device_security_async(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> FetchResult:
    """Async implementation of Device Security crawler."""
    async with DeviceSecurityCrawler(
        headless=headless, verbose=verbose, debug=debug, max_concurrency=max_concurrency
    ) as crawler:
        result = await crawler.crawl(skip_versions=skip_versions)

        return FetchResult(
            database=BugDatabase(
                metadata=Metadata(
                    generated_at=datetime.now(timezone.utc),
                    version="1.0.0",
                    source="Palo Alto Networks Device Security Release Notes",
                ),
                products=[result.product],
            ),
            failed_fetches=result.failed_fetches,
        )


async def _crawl_adem_async(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> FetchResult:
    """Async implementation of Autonomous DEM crawler."""
    async with ADEMCrawler(
        headless=headless, verbose=verbose, debug=debug, max_concurrency=max_concurrency
    ) as crawler:
        result = await crawler.crawl()

        return FetchResult(
            database=BugDatabase(
                metadata=Metadata(
                    generated_at=datetime.now(timezone.utc),
                    version="1.0.0",
                    source="Palo Alto Networks Autonomous DEM Release Notes",
                ),
                products=[result.product],
            ),
            failed_fetches=result.failed_fetches,
        )


async def _crawl_scm_async(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> FetchResult:
    """Async implementation of Strata Cloud Manager crawler."""
    async with SCMCrawler(
        headless=headless, verbose=verbose, debug=debug, max_concurrency=max_concurrency
    ) as crawler:
        result = await crawler.crawl()

        return FetchResult(
            database=BugDatabase(
                metadata=Metadata(
                    generated_at=datetime.now(timezone.utc),
                    version="1.0.0",
                    source="Palo Alto Networks Strata Cloud Manager Release Notes",
                ),
                products=[result.product],
            ),
            failed_fetches=result.failed_fetches,
        )


async def _crawl_sdwan_plugin_async(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> FetchResult:
    """Async implementation of Panorama Plugin for SD-WAN crawler."""
    async with SDWANPluginCrawler(
        headless=headless, verbose=verbose, debug=debug, max_concurrency=max_concurrency
    ) as crawler:
        result = await crawler.crawl(major_versions, skip_versions)

        if major_versions:
            versions_str = ", ".join(v.replace("-", ".") for v in major_versions)
            source = f"Palo Alto Networks Panorama Plugin for SD-WAN {versions_str} Release Notes"
        else:
            source = "Palo Alto Networks Panorama Plugin for SD-WAN Release Notes (All Versions)"

        return FetchResult(
            database=BugDatabase(
                metadata=Metadata(
                    generated_at=datetime.now(timezone.utc),
                    version="1.0.0",
                    source=source,
                ),
                products=[result.product],
            ),
            failed_fetches=result.failed_fetches,
        )


async def _crawl_cortex_xdr_async(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> FetchResult:
    """Async implementation of Cortex XDR Agent crawler."""
    async with CortexXDRCrawler(
        headless=headless, verbose=verbose, debug=debug, max_concurrency=max_concurrency
    ) as crawler:
        result = await crawler.crawl(skip_versions=skip_versions)

        return FetchResult(
            database=BugDatabase(
                metadata=Metadata(
                    generated_at=datetime.now(timezone.utc),
                    version="1.0.0",
                    source="Palo Alto Networks Cortex XDR Agent Release Notes",
                ),
                products=[result.product],
            ),
            failed_fetches=result.failed_fetches,
        )


async def _crawl_plugin_async(
    plugin_id: str,
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> FetchResult:
    """Generic async implementation for Panorama/VM-Series plugin crawlers."""
    config = PLUGIN_CONFIGS[plugin_id]

    async with PluginCrawler(
        config=config,
        headless=headless, verbose=verbose, debug=debug, max_concurrency=max_concurrency
    ) as crawler:
        result = await crawler.crawl(major_versions, skip_versions)

        if major_versions:
            versions_str = ", ".join(v.replace("-", ".") for v in major_versions)
            source = f"Palo Alto Networks {config.product_name} {versions_str} Release Notes"
        else:
            source = f"Palo Alto Networks {config.product_name} Release Notes (All Versions)"

        return FetchResult(
            database=BugDatabase(
                metadata=Metadata(
                    generated_at=datetime.now(timezone.utc),
                    version="1.0.0",
                    source=source,
                ),
                products=[result.product],
            ),
            failed_fetches=result.failed_fetches,
        )


# ==============================================================================
# Sync wrapper functions for each product
# ==============================================================================

def crawl_globalprotect(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> FetchResult:
    """Crawl GlobalProtect release notes and return a FetchResult."""
    return asyncio.run(_crawl_globalprotect_async(
        major_versions, headless, verbose, debug, max_concurrency, skip_versions
    ))


def crawl_panos(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> FetchResult:
    """Crawl PAN-OS release notes and return a FetchResult."""
    return asyncio.run(_crawl_panos_async(
        major_versions, headless, verbose, debug, max_concurrency, skip_versions
    ))


def crawl_prisma_access(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> FetchResult:
    """Crawl Prisma Access release notes and return a FetchResult."""
    return asyncio.run(_crawl_prisma_access_async(
        major_versions, headless, verbose, debug, max_concurrency, skip_versions
    ))


def crawl_prisma_access_agent(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> FetchResult:
    """Crawl Prisma Access Agent release notes and return a FetchResult."""
    return asyncio.run(_crawl_prisma_access_agent_async(
        major_versions, headless, verbose, debug, max_concurrency, skip_versions
    ))


def crawl_prisma_sdwan(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> FetchResult:
    """Crawl Prisma SD-WAN release notes and return a FetchResult."""
    return asyncio.run(_crawl_prisma_sdwan_async(
        major_versions, headless, verbose, debug, max_concurrency, skip_versions
    ))


def crawl_cloud_ngfw_azure(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> FetchResult:
    """Crawl Cloud NGFW for Azure release notes and return a FetchResult."""
    return asyncio.run(_crawl_cloud_ngfw_azure_async(
        major_versions, headless, verbose, debug, max_concurrency, skip_versions
    ))


def crawl_cloud_ngfw_aws(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> FetchResult:
    """Crawl Cloud NGFW for AWS release notes and return a FetchResult."""
    return asyncio.run(_crawl_cloud_ngfw_aws_async(
        major_versions, headless, verbose, debug, max_concurrency, skip_versions
    ))


def crawl_remote_browser_isolation(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> FetchResult:
    """Crawl Remote Browser Isolation release notes and return a FetchResult."""
    return asyncio.run(_crawl_remote_browser_isolation_async(
        major_versions, headless, verbose, debug, max_concurrency, skip_versions
    ))


def crawl_ai_runtime_security(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> FetchResult:
    """Crawl AI Runtime Security release notes and return a FetchResult."""
    return asyncio.run(_crawl_ai_runtime_security_async(
        major_versions, headless, verbose, debug, max_concurrency, skip_versions
    ))


def crawl_strata_logging_service(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> FetchResult:
    """Crawl Strata Logging Service release notes and return a FetchResult."""
    return asyncio.run(_crawl_strata_logging_service_async(
        major_versions, headless, verbose, debug, max_concurrency, skip_versions
    ))


def crawl_device_security(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> FetchResult:
    """Crawl Device Security release notes and return a FetchResult."""
    return asyncio.run(_crawl_device_security_async(
        major_versions, headless, verbose, debug, max_concurrency, skip_versions
    ))


def crawl_adem(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> FetchResult:
    """Crawl Autonomous DEM release notes and return a FetchResult."""
    return asyncio.run(_crawl_adem_async(
        major_versions, headless, verbose, debug, max_concurrency, skip_versions
    ))


def crawl_scm(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> FetchResult:
    """Crawl Strata Cloud Manager release notes and return a FetchResult."""
    return asyncio.run(_crawl_scm_async(
        major_versions, headless, verbose, debug, max_concurrency, skip_versions
    ))


def crawl_sdwan_plugin(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> FetchResult:
    """Crawl Panorama Plugin for SD-WAN release notes and return a FetchResult."""
    return asyncio.run(_crawl_sdwan_plugin_async(
        major_versions, headless, verbose, debug, max_concurrency, skip_versions
    ))


def crawl_cortex_xdr(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> FetchResult:
    """Crawl Cortex XDR Agent release notes and return a FetchResult."""
    return asyncio.run(_crawl_cortex_xdr_async(
        major_versions, headless, verbose, debug, max_concurrency, skip_versions
    ))


# Factory function for plugin crawlers
def _make_plugin_crawler(plugin_id: str):
    """Factory function to create a plugin crawler function."""
    config = PLUGIN_CONFIGS[plugin_id]

    def crawl_func(
        major_versions: Optional[list[str]] = None,
        headless: bool = True,
        verbose: bool = False,
        debug: bool = False,
        max_concurrency: int = 3,
        skip_versions: Optional[set[str]] = None,
    ) -> FetchResult:
        return asyncio.run(_crawl_plugin_async(
            plugin_id, major_versions, headless, verbose, debug,
            max_concurrency, skip_versions
        ))

    crawl_func.__name__ = f"crawl_{plugin_id.replace('-', '_')}"
    crawl_func.__doc__ = f"""Crawl {config.product_name} release notes and return a FetchResult.

    Args:
        major_versions: List of major versions to crawl (e.g., ["5-3", "5-2"]).
                       If None, discovers and crawls all available versions.
        headless: Whether to run browser in headless mode.
        verbose: Whether to print progress messages.
        debug: Whether to enable debug logging.
        max_concurrency: Maximum number of concurrent page fetches.
        skip_versions: Set of version strings to skip for incremental fetching.

    Returns:
        FetchResult with BugDatabase and any failed fetches.
    """
    return crawl_func


# Create crawler functions for all plugins
crawl_vm_series_plugin = _make_plugin_crawler("vm-series-plugin")
crawl_plugin_aws = _make_plugin_crawler("plugin-aws")
crawl_plugin_azure = _make_plugin_crawler("plugin-azure")
crawl_plugin_gcp = _make_plugin_crawler("plugin-gcp")
crawl_plugin_vmware_nsx = _make_plugin_crawler("plugin-vmware-nsx")
crawl_plugin_vmware_vcenter = _make_plugin_crawler("plugin-vmware-vcenter")
crawl_plugin_kubernetes = _make_plugin_crawler("plugin-kubernetes")
crawl_plugin_cisco_aci = _make_plugin_crawler("plugin-cisco-aci")
crawl_plugin_cisco_trustsec = _make_plugin_crawler("plugin-cisco-trustsec")
crawl_plugin_ztp = _make_plugin_crawler("plugin-ztp")
crawl_plugin_clustering = _make_plugin_crawler("plugin-clustering")
