"""Release notes data for BugDB.

This module is the single source of truth for the webapp's release-notes
modal. ``bugdb generate-release-notes`` renders it to
``assets/release-notes.json`` on every site build, overwriting whatever
is there — so an entry that exists only in the generated JSON is lost on
the next deploy. That is exactly what happened to 1.0.3, which was hand-
edited into the JSON but never added here and vanished from the site.

Add every user-visible release here. Keep entries short: the CHANGELOG
carries the engineering detail, this is the in-app summary.
"""

from bugdb.models import ChangeType, Release, ReleaseChange, ReleaseNotes


def get_release_notes() -> ReleaseNotes:
    """Return the release notes data."""
    return ReleaseNotes(
        releases=[
            Release(
                version="1.0.7",
                date="2026-08-05",
                changes=[
                    ReleaseChange(
                        type=ChangeType.FEATURE,
                        description=(
                            "Dark mode. Follows your system appearance by default; "
                            "use the switch in the header to override it."
                        ),
                    ),
                    ReleaseChange(
                        type=ChangeType.IMPROVEMENT,
                        description=(
                            "Release notes now mark each change with an icon and a "
                            "key, so descriptions line up in a single column."
                        ),
                    ),
                    ReleaseChange(
                        type=ChangeType.IMPROVEMENT,
                        description=(
                            "Build version and data date moved from the header into this dialog."
                        ),
                    ),
                ],
            ),
            Release(
                version="1.0.6",
                date="2026-08-05",
                changes=[
                    ReleaseChange(
                        type=ChangeType.FIX,
                        description=(
                            "PAN-OS 12.1 and 12.2 are discovered and crawled again. "
                            "Palo Alto moved their release notes onto the NGFW "
                            "documentation book and every 12.x version had been "
                            "missing from the database."
                        ),
                    ),
                    ReleaseChange(
                        type=ChangeType.FIX,
                        description=(
                            "Release notes no longer lose older entries each time "
                            "the site is rebuilt."
                        ),
                    ),
                    ReleaseChange(
                        type=ChangeType.FIX,
                        description=(
                            "`bugdb build` writes release notes next to the bug "
                            "database file instead of a fixed assets/ directory."
                        ),
                    ),
                    ReleaseChange(
                        type=ChangeType.IMPROVEMENT,
                        description=(
                            "The nightly upstream check now verifies that each "
                            "PAN-OS version is actually ingested, not just that "
                            "its page loads."
                        ),
                    ),
                ],
            ),
            Release(
                version="1.0.5",
                date="2026-06-11",
                changes=[
                    ReleaseChange(
                        type=ChangeType.IMPROVEMENT,
                        description=(
                            "Data baseline refreshed against the sitemap-driven "
                            "crawler: roughly 1,600 additional versions discovered "
                            "and bug ids keyed to more precise versions."
                        ),
                    ),
                    ReleaseChange(
                        type=ChangeType.FIX,
                        description=(
                            "PAN-OS 10.0 removed — Palo Alto delisted its release notes upstream."
                        ),
                    ),
                ],
            ),
            Release(
                version="1.0.4",
                date="2026-06-02",
                changes=[
                    ReleaseChange(
                        type=ChangeType.IMPROVEMENT,
                        description=(
                            "Much faster data collection: sitemap-driven discovery "
                            "and a direct HTTP transport replace the browser crawl."
                        ),
                    ),
                    ReleaseChange(
                        type=ChangeType.IMPROVEMENT,
                        description=(
                            "Incremental refreshes skip pages that have not changed upstream."
                        ),
                    ),
                    ReleaseChange(
                        type=ChangeType.IMPROVEMENT,
                        description="Cortex XDR data now comes from the documentation API.",
                    ),
                ],
            ),
            Release(
                version="1.0.3",
                date="2026-04-11",
                changes=[
                    ReleaseChange(
                        type=ChangeType.FIX,
                        description="Fixed PAN-OS 12.1 release detection and parsing",
                    ),
                    ReleaseChange(
                        type=ChangeType.IMPROVEMENT,
                        description=(
                            "Content Security Policy and cross-site scripting "
                            "hardening for the site."
                        ),
                    ),
                    ReleaseChange(
                        type=ChangeType.IMPROVEMENT,
                        description="Live progress reporting and a streaming fetch log.",
                    ),
                ],
            ),
            Release(
                version="1.0.2",
                date="2026-04-11",
                changes=[
                    ReleaseChange(
                        type=ChangeType.IMPROVEMENT,
                        description=(
                            "Automated data-fidelity checks so a refresh can never "
                            "silently lose bug data."
                        ),
                    ),
                ],
            ),
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
