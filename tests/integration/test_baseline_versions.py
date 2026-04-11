"""Assert every (product, version) pair in the baseline is still present
in the current data.json.

This is the test that would have caught a "PAN-OS 11.2 dropped" regression.
It does NOT catch "new upstream major version appeared" — see the canary
tier for that.
"""

from __future__ import annotations

import pytest

from bugdb.baseline import BaselineSnapshot, load_baseline

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


def test_baseline_version_still_present(
    baseline_pv: tuple[str, str], current_snapshot: BaselineSnapshot
) -> None:
    """Every (product, version) in the baseline must exist in current data."""
    product_id, version = baseline_pv
    product = current_snapshot.products.get(product_id)
    if product is None:
        pytest.fail(
            f"Product {product_id!r} itself is missing (see "
            f"test_baseline_product_still_present). Cannot check version "
            f"{version!r}."
        )

    available = sorted(product.versions.keys())
    assert version in product.versions, (
        f"Version {version!r} of {product_id!r} missing from current "
        f"data.json. Currently available versions for this product: "
        f"{available}. This is a crawler regression."
    )
