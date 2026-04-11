"""
Modular web crawlers for Palo Alto Networks release notes.

This package provides a clean, modular architecture for crawling release notes
from various Palo Alto Networks products.

Usage:
    # Using sync wrapper functions (recommended)
    from bugdb.crawlers import crawl_globalprotect, crawl_panos

    result = crawl_globalprotect(verbose=True)
    print(f"Found {len(result.database.products[0].versions)} versions")

    # Using crawler classes directly (advanced)
    from bugdb.crawlers import GlobalProtectCrawler

    async with GlobalProtectCrawler(verbose=True) as crawler:
        result = await crawler.crawl(major_versions=["6-3"])

Structure:
    crawlers/
    ├── __init__.py          # Public API re-exports
    ├── base.py              # BaseCrawler class with shared functionality
    ├── models.py            # Data classes (FailedFetch, CrawlResult, etc.)
    ├── utils.py             # Utility functions (extract_workaround, etc.)
    ├── registry.py          # Product registry and wrapper factory
    └── products/
        ├── __init__.py      # Product exports
        ├── globalprotect.py
        ├── panos.py
        └── ...              # Other product crawlers
"""

# Data models
# Base crawler class
from .base import BaseCrawler
from .models import (
    CrawlResult,
    FailedFetch,
    FetchResult,
    PluginConfig,
    VersionCrawlResult,
    VersionInfo,
)

# Product crawler classes
from .products import (
    ADEMCrawler,
    AIRuntimeSecurityCrawler,
    CloudNGFWAWSCrawler,
    CloudNGFWAzureCrawler,
    CortexXDRCrawler,
    DeviceSecurityCrawler,
    GlobalProtectCrawler,
    PANOSCrawler,
    PluginCrawler,
    PrismaAccessAgentCrawler,
    PrismaAccessCrawler,
    PrismaSDWANCrawler,
    RemoteBrowserIsolationCrawler,
    SCMCrawler,
    SDWANPluginCrawler,
    StrataLoggingServiceCrawler,
)

# Plugin configurations
from .products.plugins import PLUGIN_CONFIGS

# Sync wrapper functions
from .registry import (
    PRODUCT_CRAWLERS,
    # Main products
    crawl_adem,
    crawl_ai_runtime_security,
    crawl_cloud_ngfw_aws,
    crawl_cloud_ngfw_azure,
    crawl_cortex_xdr,
    crawl_device_security,
    crawl_globalprotect,
    crawl_panos,
    # Plugin products
    crawl_plugin_aws,
    crawl_plugin_azure,
    crawl_plugin_cisco_aci,
    crawl_plugin_cisco_trustsec,
    crawl_plugin_clustering,
    crawl_plugin_gcp,
    crawl_plugin_kubernetes,
    crawl_plugin_vmware_nsx,
    crawl_plugin_vmware_vcenter,
    crawl_plugin_ztp,
    crawl_prisma_access,
    crawl_prisma_access_agent,
    crawl_prisma_sdwan,
    crawl_remote_browser_isolation,
    crawl_scm,
    crawl_sdwan_plugin,
    crawl_strata_logging_service,
    crawl_vm_series_plugin,
    # Registry
    get_crawler_class,
)

# Utility functions
from .utils import (
    BASE_URL,
    CORTEX_BASE_URL,
    extract_affected_components,
    extract_bug_id_and_fix_info,
    extract_cell_text_with_tables,
    extract_fix_info_from_description,
    extract_workaround,
    get_existing_versions,
    merge_databases,
    normalize_text,
    table_to_text,
    version_sort_key,
)

__all__ = [
    # Data models
    "CrawlResult",
    "FailedFetch",
    "FetchResult",
    "PluginConfig",
    "VersionCrawlResult",
    "VersionInfo",
    # Utility functions
    "BASE_URL",
    "CORTEX_BASE_URL",
    "extract_affected_components",
    "extract_bug_id_and_fix_info",
    "extract_cell_text_with_tables",
    "extract_fix_info_from_description",
    "extract_workaround",
    "get_existing_versions",
    "merge_databases",
    "normalize_text",
    "table_to_text",
    "version_sort_key",
    # Base class
    "BaseCrawler",
    # Crawler classes
    "ADEMCrawler",
    "AIRuntimeSecurityCrawler",
    "CloudNGFWAWSCrawler",
    "CloudNGFWAzureCrawler",
    "CortexXDRCrawler",
    "DeviceSecurityCrawler",
    "GlobalProtectCrawler",
    "PANOSCrawler",
    "PluginCrawler",
    "PrismaAccessAgentCrawler",
    "PrismaAccessCrawler",
    "PrismaSDWANCrawler",
    "RemoteBrowserIsolationCrawler",
    "SCMCrawler",
    "SDWANPluginCrawler",
    "StrataLoggingServiceCrawler",
    # Plugin configs
    "PLUGIN_CONFIGS",
    # Sync wrapper functions
    "crawl_adem",
    "crawl_ai_runtime_security",
    "crawl_cloud_ngfw_aws",
    "crawl_cloud_ngfw_azure",
    "crawl_cortex_xdr",
    "crawl_device_security",
    "crawl_globalprotect",
    "crawl_panos",
    "crawl_prisma_access",
    "crawl_prisma_access_agent",
    "crawl_prisma_sdwan",
    "crawl_remote_browser_isolation",
    "crawl_scm",
    "crawl_sdwan_plugin",
    "crawl_strata_logging_service",
    "crawl_plugin_aws",
    "crawl_plugin_azure",
    "crawl_plugin_cisco_aci",
    "crawl_plugin_cisco_trustsec",
    "crawl_plugin_clustering",
    "crawl_plugin_gcp",
    "crawl_plugin_kubernetes",
    "crawl_plugin_vmware_nsx",
    "crawl_plugin_vmware_vcenter",
    "crawl_plugin_ztp",
    "crawl_vm_series_plugin",
    # Registry
    "get_crawler_class",
    "PRODUCT_CRAWLERS",
]
