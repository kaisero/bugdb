"""Product-specific crawler implementations."""

from .adem import ADEMCrawler
from .cloud_ngfw import CloudNGFWAWSCrawler, CloudNGFWAzureCrawler
from .cortex_xdr import CortexXDRCrawler
from .device_security import DeviceSecurityCrawler
from .globalprotect import GlobalProtectCrawler
from .panos import PANOSCrawler
from .plugins import PluginCrawler
from .prisma_access import PrismaAccessCrawler
from .prisma_access_agent import PrismaAccessAgentCrawler
from .prisma_sdwan import PrismaSDWANCrawler
from .saas import (
    AIRuntimeSecurityCrawler,
    RemoteBrowserIsolationCrawler,
    StrataLoggingServiceCrawler,
)
from .scm import SCMCrawler
from .sdwan_plugin import SDWANPluginCrawler

__all__ = [
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
]
