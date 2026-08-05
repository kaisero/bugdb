"""Upstream-version canary for the PAN-OS crawler.

Probes docs.paloaltonetworks.com directly to detect when Palo Alto
publishes a new major version that the crawler's hard-coded
``candidate_versions`` list doesn't know about.

This is the one test that would have caught the original PAN-OS 12.1
bug. The baseline-comparison tier cannot — if 12.1 wasn't in the
baseline, a comparison test can't notice it's missing.

Run with::

    uv run pytest tests/canary/ -m canary

Network flakes are tolerated: probes retry 3x with backoff, and failures
due to network errors (vs. real 404s) are reported distinctly.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.canary


# Major versions we expect to be reachable on the real docs site as of
# this file's last update. If a nightly run ever finds a NEW one outside
# this list, that's the signal we need to widen the crawler's
# candidate_versions list.
#
# Format matches PANOSCrawler.candidate_versions: "<major>-<minor>".
KNOWN_UPSTREAM_PANOS_MAJORS: set[str] = {
    "12-2",
    "12-1",
    "11-2",
    "11-1",
    "11-0",
    "10-2",
    "10-1",
    "10-0",
    "9-1",
}

# Majors whose issue pages should be reachable *through sitemap discovery*.
# Narrower than KNOWN_UPSTREAM_PANOS_MAJORS on purpose:
#
#   10-0 — the release-notes landing page still answers 200, and a single
#          `.../pan-os-10-0-release-information/known-issues` page exists,
#          but Palo Alto has de-listed every 10.0 issue URL from
#          sitemap.xml. Since discovery is sitemap-driven, 10.0 yields no
#          data and has been absent from bugdb.json all along. It is EOL,
#          so this is accepted rather than fixed — but it is recorded here
#          instead of silently dropped, so the exclusion is a decision
#          rather than a blind spot.
SITEMAP_INGESTED_PANOS_MAJORS: set[str] = KNOWN_UPSTREAM_PANOS_MAJORS - {"10-0"}

# Additional speculative candidates. If any of these suddenly start
# responding 200, the nightly canary fails loudly and tells us to add
# them to the crawler.
SPECULATIVE_UPSTREAM_PANOS_MAJORS: set[str] = {
    "13-0",
    "13-1",
    "12-3",
    "12-0",  # skipped release, but check in case
}


@pytest.mark.parametrize(
    "major_version",
    sorted(KNOWN_UPSTREAM_PANOS_MAJORS),
    ids=sorted(KNOWN_UPSTREAM_PANOS_MAJORS),
)
def test_known_panos_major_version_is_reachable(major_version: str, probe):
    """Every major version we currently claim to crawl must still exist."""
    ngfw = probe(f"/ngfw/release-notes/{major_version}")
    legacy = probe(f"/pan-os/{major_version}/pan-os-release-notes")

    # Tolerate network errors on a single URL so long as the *other*
    # resolves. This prevents the canary from paging on a transient fault.
    if ngfw.was_network_error and legacy.was_network_error:
        pytest.skip(
            f"Both probes for PAN-OS {major_version} failed with network "
            f"errors (ngfw={ngfw.error}, legacy={legacy.error}). "
            f"Not a real regression — re-run later."
        )

    assert ngfw.exists or legacy.exists, (
        f"PAN-OS {major_version} is not reachable at either "
        f"/ngfw/release-notes/{major_version} (got {ngfw.status}) or "
        f"/pan-os/{major_version}/pan-os-release-notes (got "
        f"{legacy.status}). Either the upstream path changed or Palo "
        f"Alto removed this major version entirely."
    )


@pytest.mark.parametrize(
    "major_version",
    sorted(SPECULATIVE_UPSTREAM_PANOS_MAJORS),
    ids=sorted(SPECULATIVE_UPSTREAM_PANOS_MAJORS),
)
def test_speculative_panos_major_version_is_not_yet_released(major_version: str, probe):
    """Speculative majors must NOT yet exist. This is the canary signal.

    If ``13-0`` suddenly 200s, it means Palo Alto shipped PAN-OS 13.0 and
    the crawler's hard-coded candidate_versions list needs updating.
    The test failing is a GOOD thing — it means we have work to do.
    """
    ngfw = probe(f"/ngfw/release-notes/{major_version}")
    legacy = probe(f"/pan-os/{major_version}/pan-os-release-notes")

    if ngfw.was_network_error and legacy.was_network_error:
        pytest.skip("Both probes failed with network errors. Re-run later.")

    # If both are 404 → the major doesn't exist yet → canary passes.
    if not ngfw.exists and not legacy.exists:
        return

    pytest.fail(
        f"CANARY FIRED: PAN-OS {major_version} is now reachable upstream "
        f"(ngfw={ngfw.status}, legacy={legacy.status}). Add "
        f"{major_version!r} to PANOSCrawler.candidate_versions in "
        f"src/bugdb/crawlers/products/panos.py, refresh the baseline, "
        f"and run `bugdb fetch panos`."
    )


def test_crawler_candidate_list_matches_known_upstream():
    """The crawler's hard-coded list should cover every known upstream major.

    This is a pure-Python check — no network needed. It runs under the
    canary marker because it's logically part of the upstream sanity.
    """
    from bugdb.crawlers.products.panos import PANOSCrawler

    # Read the real list rather than a copy — this test used to keep its
    # own duplicate, which silently drifted out of sync.
    crawler_candidates = set(PANOSCrawler.CANDIDATE_VERSIONS)

    missing_from_crawler = KNOWN_UPSTREAM_PANOS_MAJORS - crawler_candidates
    assert not missing_from_crawler, (
        f"The canary's KNOWN_UPSTREAM_PANOS_MAJORS contains versions that "
        f"PANOSCrawler.candidate_versions doesn't probe: "
        f"{sorted(missing_from_crawler)}. Update src/bugdb/crawlers/"
        f"products/panos.py or fix this test."
    )


# ---------------------------------------------------------------------
# Reachability is not ingestion.
#
# The probes above only assert that a version's landing page answers 200.
# PAN-OS 12.1 passed them for weeks while the crawl produced zero 12.x
# versions: the page existed, but `_PRODUCT_PREFIXES["panos"]` matched
# only `/pan-os/`, so the `/ngfw/release-notes/` URLs classified as
# product_id=None and discovery never saw them. A green canary plus an
# empty dataset is exactly the blind spot these tests close — they run
# the real classification path against the live sitemap.
# ---------------------------------------------------------------------


@pytest.mark.canary
@pytest.mark.parametrize(
    "major_version",
    sorted(SITEMAP_INGESTED_PANOS_MAJORS),
    ids=lambda v: f"panos-{v}",
)
def test_known_panos_major_is_discoverable_from_sitemap(major_version: str, live_sitemap):
    """Every major we claim to crawl must survive sitemap classification."""
    from bugdb.crawlers.sitemap_discovery import discover_major_versions

    discovered = discover_major_versions(live_sitemap, "panos")
    assert major_version in discovered, (
        f"PAN-OS {major_version} is reachable upstream but does NOT appear in "
        f"sitemap discovery — the crawl will silently produce zero versions "
        f"for it. Discovered majors: {discovered}. Most likely the docs moved "
        f"to a URL prefix that `_PRODUCT_PREFIXES['panos']` in "
        f"src/bugdb/sitemap.py does not match."
    )


@pytest.mark.canary
@pytest.mark.parametrize(
    "major_version",
    sorted(SITEMAP_INGESTED_PANOS_MAJORS),
    ids=lambda v: f"panos-{v}",
)
def test_known_panos_major_yields_issue_pages(major_version: str, live_sitemap):
    """Discovery must produce at least one version with real issue URLs."""
    from bugdb.crawlers.sitemap_discovery import discover_version_pages

    pages = discover_version_pages(live_sitemap, "panos", major_version=major_version)
    assert pages, f"PAN-OS {major_version} discovered no version pages at all."
    with_urls = [p for p in pages if p.known_issues_urls or p.addressed_issues_urls]
    assert with_urls, (
        f"PAN-OS {major_version} produced {len(pages)} version(s) but none carry "
        f"known/addressed issue URLs — the page-classification step is dropping them."
    )
