"""
DEPRECATED: This module is maintained for backward compatibility only.

The crawler functionality has been refactored into a modular package structure
at bugdb.crawlers. Please update your imports to use the new module:

    # Old import (deprecated)
    from bugdb.crawler import crawl_globalprotect, PaloAltoCrawler

    # New import (recommended)
    from bugdb.crawlers import crawl_globalprotect, GlobalProtectCrawler

The new package structure provides:
- Better code organization with separate files for each product
- Easier maintenance and testing
- Reduced code duplication through a base crawler class
- Clear separation of concerns (models, utils, crawlers)

For more information, see bugdb/crawlers/__init__.py.
"""

# Re-export everything from the new crawlers package for backward compatibility

# Data models
# Base crawler class (aliased as PaloAltoCrawler for compatibility)
from bugdb.crawlers.base import BaseCrawler
from bugdb.crawlers.models import (
    CrawlResult,
    FailedFetch,
    FetchResult,
    PluginConfig,
    VersionCrawlResult,
    VersionInfo,
)

# Utility functions
from bugdb.crawlers.utils import (
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
)

PaloAltoCrawler = BaseCrawler  # Backward compatibility alias

# Plugin configurations
from bugdb.crawlers.products.plugins import PLUGIN_CONFIGS

# Sync wrapper functions
from bugdb.crawlers.registry import (
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
    # Crawler class (backward compatibility)
    "PaloAltoCrawler",
    "BaseCrawler",
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
]
