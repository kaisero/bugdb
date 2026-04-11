"""Assert every product present in the baseline is still present in the
current data.json. A product disappearing is the loudest possible signal
that a crawler silently broke.

Parametrization: one test per baseline product id, so a single missing
product fails exactly one test case with a clean id.
"""

from __future__ import annotations

import pytest

from bugdb.baseline import Baseline, BaselineSnapshot

pytestmark = pytest.mark.data_baseline


def _baseline_product_ids(baseline: Baseline) -> list[str]:
    return sorted(baseline.snapshot.products.keys())


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Parametrize tests with the list of product ids from the baseline.

    We can't use a fixture for parametrize values directly, so we load the
    baseline at collection time. This happens once per session because
    pytest memoizes collection.
    """
    if "baseline_product_id" in metafunc.fixturenames:
        from tests.integration.conftest import DEFAULT_BASELINE_PATH
        from bugdb.baseline import load_baseline

        if not DEFAULT_BASELINE_PATH.exists():
            metafunc.parametrize("baseline_product_id", [])
            return

        baseline = load_baseline(DEFAULT_BASELINE_PATH)
        product_ids = _baseline_product_ids(baseline)
        metafunc.parametrize("baseline_product_id", product_ids, ids=product_ids)


def test_baseline_product_still_present(
    baseline_product_id: str, current_snapshot: BaselineSnapshot
) -> None:
    """Every product from the baseline must exist in current data.json."""
    current_products = set(current_snapshot.products.keys())
    assert baseline_product_id in current_products, (
        f"Product {baseline_product_id!r} was in the committed baseline but "
        f"is MISSING from current assets/data.json. This is a crawler "
        f"regression — investigate fetch logs for "
        f"{baseline_product_id}. Current products: {sorted(current_products)}"
    )
