"""Product-specific crawler implementations."""

from .adem import ADEMCrawler
from .cloud_ngfw import CloudNGFWAWSCrawler, CloudNGFWAzureCrawler
from .cortex_xdr import CortexXDRCrawler
from .device_security import DeviceSecurityCrawler
from .enterprise_dlp import EnterpriseDLPCrawler
from .globalprotect import GlobalProtectCrawler
from .panos import PANOSCrawler
from .plugins import PluginCrawler
from .prisma_access import PrismaAccessCrawler
from .prisma_access_agent import PrismaAccessAgentCrawler
from .prisma_sdwan import PrismaSDWANCrawler
from .saas import (
    AIAccessSecurityCrawler,
    AIRuntimeSecurityCrawler,
    RemoteBrowserIsolationCrawler,
    StrataLoggingServiceCrawler,
)
from .scm import SCMCrawler
from .sdwan_plugin import SDWANPluginCrawler
from .ts_agent import TSAgentCrawler

__all__ = [
    "ADEMCrawler",
    "AIAccessSecurityCrawler",
    "AIRuntimeSecurityCrawler",
    "CloudNGFWAWSCrawler",
    "CloudNGFWAzureCrawler",
    "CortexXDRCrawler",
    "DeviceSecurityCrawler",
    "EnterpriseDLPCrawler",
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
    "TSAgentCrawler",
]
