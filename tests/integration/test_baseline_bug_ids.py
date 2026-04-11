"""Assert the set of bug ids from the baseline is a subset of the current
set for every (product, version).

This check is strictly stronger than the count check: it catches the case
where the crawler substitutes issues (same count, different content).
"""

from __future__ import annotations

import pytest

from bugdb.baseline import BaselineSnapshot, VersionFingerprint, load_baseline

pytestmark = pytest.mark.data_baseline


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "baseline_pv" not in metafunc.fixturenames:
        return

    from tests.integration.conftest import DEFAULT_BASELINE_PATH

    if not DEFAULT_BASELINE_PATH.exists():
        metafunc.parametrize("baseline_pv", [])
        return

    baseline = load_baseline(DEFAULT_BASELINE_PATH)
    pairs: list[tuple[str, str]] = [
        (pid, ver)
        for pid, product in sorted(baseline.snapshot.products.items())
        for ver in sorted(product.versions.keys())
    ]
    ids = [f"{pid}-{ver}" for pid, ver in pairs]
    metafunc.parametrize("baseline_pv", pairs, ids=ids)


def _baseline_fingerprint_for(
    baseline_pv: tuple[str, str],
) -> VersionFingerprint:
    from tests.integration.conftest import DEFAULT_BASELINE_PATH

    baseline = load_baseline(DEFAULT_BASELINE_PATH)
    pid, ver = baseline_pv
    return baseline.snapshot.products[pid].versions[ver]


def test_baseline_bug_ids_remain_present(
    baseline_pv: tuple[str, str], current_snapshot: BaselineSnapshot
) -> None:
    """baseline_bug_ids ⊆ current_bug_ids for this (product, version)."""
    product_id, version = baseline_pv

    product = current_snapshot.products.get(product_id)
    if product is None or version not in product.versions:
        pytest.skip(
            f"{product_id} {version} already missing (see other tests)"
        )

    baseline_fp = _baseline_fingerprint_for(baseline_pv)
    current_fp = product.versions[version]

    baseline_bug_ids = set(baseline_fp.bug_ids)
    current_bug_ids = set(current_fp.bug_ids)

    missing = sorted(baseline_bug_ids - current_bug_ids)
    assert not missing, (
        f"REGRESSION: {product_id} {version} is missing "
        f"{len(missing)} bug id(s) that were in the baseline. "
        f"First 10: {missing[:10]}. "
        f"Baseline had {len(baseline_bug_ids)}, current has "
        f"{len(current_bug_ids)}."
    )
