"""Assert issue counts are monotonically non-decreasing per (product, version).

If the crawler previously extracted 34 known issues for PAN-OS 11.2.11
and now extracts 28, that's a regression — even if no bug_ids are missing
from the intersection, the set shrank.
"""

from __future__ import annotations

import pytest

from bugdb.baseline import BaselineSnapshot, VersionFingerprint, load_baseline

pytestmark = pytest.mark.data_baseline


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "baseline_pvt" not in metafunc.fixturenames:
        return

    from tests.integration.conftest import DEFAULT_BASELINE_PATH

    if not DEFAULT_BASELINE_PATH.exists():
        metafunc.parametrize("baseline_pvt", [])
        return

    baseline = load_baseline(DEFAULT_BASELINE_PATH)
    triples: list[tuple[str, str, str]] = []
    for pid, product in sorted(baseline.snapshot.products.items()):
        for ver in sorted(product.versions.keys()):
            triples.append((pid, ver, "known"))
            triples.append((pid, ver, "addressed"))
    ids = [f"{pid}-{ver}-{t}" for pid, ver, t in triples]
    metafunc.parametrize("baseline_pvt", triples, ids=ids)


def _baseline_fingerprint_for(
    baseline_pvt: tuple[str, str, str],
) -> VersionFingerprint:
    from tests.integration.conftest import DEFAULT_BASELINE_PATH

    baseline = load_baseline(DEFAULT_BASELINE_PATH)
    pid, ver, _ = baseline_pvt
    return baseline.snapshot.products[pid].versions[ver]


def test_baseline_issue_count_non_decreasing(
    baseline_pvt: tuple[str, str, str], current_snapshot: BaselineSnapshot
) -> None:
    """current.{known,addressed} must be >= baseline.{known,addressed}."""
    product_id, version, issue_type = baseline_pvt

    # Skip if prior tests already caught the missing product/version.
    product = current_snapshot.products.get(product_id)
    if product is None or version not in product.versions:
        pytest.skip(f"{product_id} {version} already missing (see other tests)")

    baseline_fp = _baseline_fingerprint_for(baseline_pvt)
    current_fp = product.versions[version]

    baseline_count = getattr(baseline_fp, issue_type)
    current_count = getattr(current_fp, issue_type)

    # For the delta message, compute which bug_ids the baseline had that
    # are gone from the current fingerprint. This turns a dry numeric
    # failure into an actionable report.
    missing = sorted(set(baseline_fp.bug_ids) - set(current_fp.bug_ids))

    assert current_count >= baseline_count, (
        f"REGRESSION: {product_id} {version} {issue_type}_issues dropped "
        f"from {baseline_count} -> {current_count} "
        f"(lost {baseline_count - current_count} issues). "
        f"First missing bug_ids: {missing[:10]}"
    )
