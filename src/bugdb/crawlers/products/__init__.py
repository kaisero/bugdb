"""Product-specific crawler implementations."""

from .globalprotect import GlobalProtectCrawler
from .panos import PANOSCrawler
from .prisma_access import PrismaAccessCrawler
from .prisma_access_agent import PrismaAccessAgentCrawler
from .prisma_sdwan import PrismaSDWANCrawler
from .cloud_ngfw import CloudNGFWAzureCrawler, CloudNGFWAWSCrawler
from .saas import (
    RemoteBrowserIsolationCrawler,
    AIRuntimeSecurityCrawler,
    StrataLoggingServiceCrawler,
)
from .device_security import DeviceSecurityCrawler
from .adem import ADEMCrawler
from .scm import SCMCrawler
from .sdwan_plugin import SDWANPluginCrawler
from .cortex_xdr import CortexXDRCrawler
from .plugins import PluginCrawler

__all__ = [
    "GlobalProtectCrawler",
    "PANOSCrawler",
    "PrismaAccessCrawler",
    "PrismaAccessAgentCrawler",
    "PrismaSDWANCrawler",
    "CloudNGFWAzureCrawler",
    "CloudNGFWAWSCrawler",
    "RemoteBrowserIsolationCrawler",
    "AIRuntimeSecurityCrawler",
    "StrataLoggingServiceCrawler",
    "DeviceSecurityCrawler",
    "ADEMCrawler",
    "SCMCrawler",
    "SDWANPluginCrawler",
    "CortexXDRCrawler",
    "PluginCrawler",
]
