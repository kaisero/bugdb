"""Sample data generation for BugDB."""

from datetime import datetime, timezone

from bugdb.models import (
    BugDatabase,
    Issue,
    Metadata,
    Product,
    ProductVersion,
)


def generate_sample_data() -> BugDatabase:
    """Generate sample bug database with realistic PAN data."""
    return BugDatabase(
        metadata=Metadata(
            generated_at=datetime.now(timezone.utc),
            version="1.0.0",
            source="Palo Alto Networks Release Notes (Sample Data)",
        ),
        products=[
            _create_panos_product(),
            _create_panorama_product(),
            _create_globalprotect_product(),
        ],
    )


def _create_panos_product() -> Product:
    """Create PAN-OS product with sample issues."""
    return Product(
        id="pan-os",
        name="PAN-OS",
        versions=[
            ProductVersion(
                version="11.1.3",
                release_date="2026-03-15",
                known_issues=[
                    Issue(
                        bug_id="PAN-300637",
                        description="The PA-5450 firewall's HSCI interface does not recognize a hot-swapped transceiver.",
                        symptoms="Transceiver not detected after hot-swap. Interface remains down despite physical connectivity.",
                        workaround="Power down the firewall before removing or inserting the transceiver module.",
                        affected_components=["Hardware", "Networking"],
                    ),
                    Issue(
                        bug_id="PAN-298445",
                        description="GlobalProtect gateway authentication fails intermittently when using SAML with Azure AD.",
                        symptoms="Users experience random authentication failures. Error message: 'SAML assertion validation failed'.",
                        workaround="Increase the SAML clock skew tolerance to 120 seconds in the authentication profile.",
                        affected_components=["GlobalProtect", "Authentication"],
                    ),
                    Issue(
                        bug_id="PAN-295112",
                        description="Memory leak in the management plane when processing large numbers of log queries.",
                        symptoms="Gradual increase in memory usage on the management plane. System may become unresponsive after extended log queries.",
                        workaround="Restart the management server process (mgmtsrvr) during maintenance window.",
                        affected_components=["Management", "Logging"],
                    ),
                ],
                addressed_issues=[
                    Issue(
                        bug_id="PAN-289001",
                        description="Security profiles consumed excessive memory causing dataplane restart.",
                    ),
                    Issue(
                        bug_id="PAN-287654",
                        description="SSL decryption failed for TLS 1.3 connections with certain cipher suites.",
                    ),
                    Issue(
                        bug_id="PAN-285432",
                        description="Zone protection profile counters displayed incorrect values in the web interface.",
                    ),
                ],
            ),
            ProductVersion(
                version="11.1.2",
                release_date="2026-02-01",
                known_issues=[
                    Issue(
                        bug_id="PAN-289001",
                        description="Security profiles consumed excessive memory causing dataplane restart.",
                        symptoms="Firewall experiences unexpected dataplane restarts. High memory utilization observed before restart.",
                        workaround="Reduce the number of security profiles or upgrade to 11.1.3.",
                        affected_components=["Dataplane", "Security Profiles"],
                    ),
                    Issue(
                        bug_id="PAN-287654",
                        description="SSL decryption failed for TLS 1.3 connections with certain cipher suites.",
                        symptoms="Decrypted sessions show as failed. Users cannot access HTTPS sites using TLS 1.3.",
                        workaround="Add affected domains to SSL decryption exclusion list.",
                        affected_components=["SSL Decryption", "Security"],
                    ),
                ],
                addressed_issues=[
                    Issue(
                        bug_id="PAN-282100",
                        description="HA failover took longer than expected during high traffic conditions.",
                    ),
                    Issue(
                        bug_id="PAN-280555",
                        description="Custom URL categories not syncing correctly to Panorama managed devices.",
                    ),
                ],
            ),
            ProductVersion(
                version="11.0.4",
                release_date="2026-01-15",
                known_issues=[
                    Issue(
                        bug_id="PAN-278900",
                        description="DNS proxy service stops responding under high query load.",
                        symptoms="DNS queries timeout. Clients unable to resolve domain names through the firewall.",
                        workaround="Restart the DNS proxy service or configure clients to use alternate DNS servers.",
                        affected_components=["DNS Proxy", "Networking"],
                    ),
                ],
                addressed_issues=[
                    Issue(
                        bug_id="PAN-275000",
                        description="IPSec tunnel flapping when rekeying with certain third-party VPN devices.",
                    ),
                    Issue(
                        bug_id="PAN-273500",
                        description="User-ID agent connection drops after 24 hours of continuous operation.",
                    ),
                    Issue(
                        bug_id="PAN-271200",
                        description="Web interface slow to load when device has more than 10,000 security rules.",
                    ),
                ],
            ),
        ],
    )


def _create_panorama_product() -> Product:
    """Create Panorama product with sample issues."""
    return Product(
        id="panorama",
        name="Panorama",
        versions=[
            ProductVersion(
                version="11.1.3",
                release_date="2026-03-15",
                known_issues=[
                    Issue(
                        bug_id="PAN-302100",
                        description="Template stack push fails when device group contains more than 500 firewalls.",
                        symptoms="Push operation times out. Partial configuration may be applied to some devices.",
                        workaround="Split large device groups into smaller groups of 250 or fewer devices.",
                        affected_components=["Templates", "Device Management"],
                    ),
                    Issue(
                        bug_id="PAN-301555",
                        description="Log forwarding to external syslog servers drops packets during peak hours.",
                        symptoms="Missing logs in SIEM. Log collector shows high queue utilization.",
                        workaround="Increase log collector resources or add additional log collectors.",
                        affected_components=["Logging", "Log Forwarding"],
                    ),
                ],
                addressed_issues=[
                    Issue(
                        bug_id="PAN-298000",
                        description="Panorama web interface became unresponsive when viewing large ACC reports.",
                    ),
                    Issue(
                        bug_id="PAN-296500",
                        description="Scheduled config exports failed silently when SCP server was unreachable.",
                    ),
                ],
            ),
            ProductVersion(
                version="11.0.4",
                release_date="2026-01-15",
                known_issues=[
                    Issue(
                        bug_id="PAN-290000",
                        description="Managed device firmware upgrade fails when using proxy server.",
                        symptoms="Firmware download stuck at 0%. Error in logs indicates connection timeout.",
                        workaround="Download firmware manually and upload to Panorama.",
                        affected_components=["Software Updates", "Proxy"],
                    ),
                ],
                addressed_issues=[
                    Issue(
                        bug_id="PAN-285000",
                        description="Role-based access control not enforced correctly for API access.",
                    ),
                    Issue(
                        bug_id="PAN-283000",
                        description="Collector group statistics inaccurate after HA failover.",
                    ),
                ],
            ),
        ],
    )


def _create_globalprotect_product() -> Product:
    """Create GlobalProtect product with sample issues."""
    return Product(
        id="globalprotect",
        name="GlobalProtect",
        versions=[
            ProductVersion(
                version="6.2.1",
                release_date="2026-03-10",
                known_issues=[
                    Issue(
                        bug_id="GPT-45678",
                        description="GlobalProtect client disconnects when switching between WiFi networks on macOS.",
                        symptoms="VPN connection drops when network changes. User must manually reconnect.",
                        workaround="Enable 'Reconnect on network change' in GlobalProtect agent settings.",
                        affected_components=["macOS Client", "Connectivity"],
                    ),
                    Issue(
                        bug_id="GPT-45500",
                        description="Split tunnel exclude routes not applied correctly on Windows 11 23H2.",
                        symptoms="Traffic meant to be excluded from tunnel is still routed through VPN.",
                        workaround="Use include-based split tunneling instead of exclude-based.",
                        affected_components=["Windows Client", "Split Tunneling"],
                    ),
                ],
                addressed_issues=[
                    Issue(
                        bug_id="GPT-44000",
                        description="Client certificate authentication failed with smart cards on Windows.",
                    ),
                    Issue(
                        bug_id="GPT-43500",
                        description="HIP check results cached longer than configured interval.",
                    ),
                ],
            ),
            ProductVersion(
                version="6.2.0",
                release_date="2026-02-01",
                known_issues=[
                    Issue(
                        bug_id="GPT-44000",
                        description="Client certificate authentication failed with smart cards on Windows.",
                        symptoms="Users cannot authenticate using PIV/CAC smart cards. Error: 'Certificate chain validation failed'.",
                        workaround="Use username/password authentication as fallback.",
                        affected_components=["Windows Client", "Authentication"],
                    ),
                ],
                addressed_issues=[
                    Issue(
                        bug_id="GPT-42000",
                        description="GlobalProtect system tray icon disappeared after Windows update.",
                    ),
                    Issue(
                        bug_id="GPT-41500",
                        description="Pre-logon VPN connection failed on domain-joined machines.",
                    ),
                ],
            ),
        ],
    )
