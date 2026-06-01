"""Release notes data for BugDB."""

from bugdb.models import ChangeType, Release, ReleaseChange, ReleaseNotes


def get_release_notes() -> ReleaseNotes:
    """Return the release notes data."""
    return ReleaseNotes(
        releases=[
            Release(
                version="1.0.1",
                date="2026-03-31",
                changes=[
                    ReleaseChange(
                        type=ChangeType.FEATURE,
                        description="Cortex XDR Product Support",
                    ),
                ],
            ),
            Release(
                version="1.0.0",
                date="2026-03-31",
                title="Initial Release",
                changes=[
                    # Cross-reference features
                    ReleaseChange(
                        type=ChangeType.FEATURE,
                        description=(
                            "Fix Available Cross-Reference for Known Issues to find Fixed Release"
                        ),
                    ),
                    ReleaseChange(
                        type=ChangeType.FEATURE,
                        description=(
                            "Other Issues Affected - Find other releases affected by the issue"
                        ),
                    ),
                    # Core products
                    ReleaseChange(
                        type=ChangeType.FEATURE,
                        description="PAN-OS release notes crawler",
                    ),
                    ReleaseChange(
                        type=ChangeType.FEATURE,
                        description="GlobalProtect release notes crawler",
                    ),
                    # Prisma products
                    ReleaseChange(
                        type=ChangeType.FEATURE,
                        description="Prisma Access release notes crawler",
                    ),
                    ReleaseChange(
                        type=ChangeType.FEATURE,
                        description="Prisma Access Agent release notes crawler",
                    ),
                    ReleaseChange(
                        type=ChangeType.FEATURE,
                        description="Prisma SD-WAN release notes crawler",
                    ),
                    # Cloud NGFW
                    ReleaseChange(
                        type=ChangeType.FEATURE,
                        description="Cloud NGFW for AWS release notes crawler",
                    ),
                    ReleaseChange(
                        type=ChangeType.FEATURE,
                        description="Cloud NGFW for Azure release notes crawler",
                    ),
                    # Security products
                    ReleaseChange(
                        type=ChangeType.FEATURE,
                        description="Cortex XDR Agent release notes crawler",
                    ),
                    ReleaseChange(
                        type=ChangeType.FEATURE,
                        description="AI Runtime Security release notes crawler",
                    ),
                    ReleaseChange(
                        type=ChangeType.FEATURE,
                        description="Device Security release notes crawler",
                    ),
                    ReleaseChange(
                        type=ChangeType.FEATURE,
                        description="Remote Browser Isolation release notes crawler",
                    ),
                    # Management
                    ReleaseChange(
                        type=ChangeType.FEATURE,
                        description="Strata Cloud Manager (SCM) release notes crawler",
                    ),
                    ReleaseChange(
                        type=ChangeType.FEATURE,
                        description="Strata Logging Service release notes crawler",
                    ),
                    ReleaseChange(
                        type=ChangeType.FEATURE,
                        description="Autonomous DEM (ADEM) release notes crawler",
                    ),
                    # Plugins
                    ReleaseChange(
                        type=ChangeType.FEATURE,
                        description="VM-Series Plugin release notes crawler",
                    ),
                    ReleaseChange(
                        type=ChangeType.FEATURE,
                        description="SD-WAN Plugin release notes crawler",
                    ),
                    ReleaseChange(
                        type=ChangeType.FEATURE,
                        description="AWS Plugin release notes crawler",
                    ),
                    ReleaseChange(
                        type=ChangeType.FEATURE,
                        description="Azure Plugin release notes crawler",
                    ),
                    ReleaseChange(
                        type=ChangeType.FEATURE,
                        description="GCP Plugin release notes crawler",
                    ),
                    ReleaseChange(
                        type=ChangeType.FEATURE,
                        description="Cisco ACI Plugin release notes crawler",
                    ),
                    ReleaseChange(
                        type=ChangeType.FEATURE,
                        description="Cisco TrustSec Plugin release notes crawler",
                    ),
                    ReleaseChange(
                        type=ChangeType.FEATURE,
                        description="VMware NSX Plugin release notes crawler",
                    ),
                    ReleaseChange(
                        type=ChangeType.FEATURE,
                        description="VMware vCenter Plugin release notes crawler",
                    ),
                    ReleaseChange(
                        type=ChangeType.FEATURE,
                        description="Kubernetes Plugin release notes crawler",
                    ),
                    ReleaseChange(
                        type=ChangeType.FEATURE,
                        description="Clustering Plugin release notes crawler",
                    ),
                    ReleaseChange(
                        type=ChangeType.FEATURE,
                        description="ZTP Plugin release notes crawler",
                    ),
                ],
            ),
        ]
    )
