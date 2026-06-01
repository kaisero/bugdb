"""Shared fixtures for the data-fidelity integration tier.

These tests compare the current `assets/bugdb.json` against a committed
baseline snapshot. They are session-scoped because loading a 13 MB JSON
file per test is wasteful.

Run with:
    uv run pytest tests/integration/ -m data_baseline

Refresh the baseline (explicit opt-in only):
    BUGDB_REFRESH_BASELINE=1 uv run pytest tests/integration/ -m data_baseline
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from bugdb.baseline import (
    Baseline,
    BaselineSnapshot,
    build_baseline,
    load_baseline,
    save_baseline,
)

# Repo layout: tests/integration/conftest.py -> repo root is parents[2]
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BUGDB_PATH = REPO_ROOT / "assets" / "bugdb.json"
# NOTE: the baseline filename deliberately stays `data_baseline.json`
# — it's an independent fingerprint artifact, not a copy of the raw
# bug database, and renaming would invalidate the committed snapshot.
DEFAULT_BASELINE_PATH = REPO_ROOT / "tests" / "baselines" / "data_baseline.json"

REFRESH_ENV_VAR = "BUGDB_REFRESH_BASELINE"


def pytest_addoption(parser: pytest.Parser) -> None:
    """Allow overriding the bugdb and baseline paths from the CLI.

    Useful for staging runs and local experimentation.
    """
    group = parser.getgroup("bugdb-integration")
    group.addoption(
        "--bugdb-path",
        action="store",
        default=None,
        help="Path to assets/bugdb.json (default: repo assets/bugdb.json).",
    )
    group.addoption(
        "--baseline-path",
        action="store",
        default=None,
        help="Path to the baseline snapshot JSON.",
    )


@pytest.fixture(scope="session")
def bugdb_path(request: pytest.FixtureRequest) -> Path:
    """Resolved path to the bugdb.json under test."""
    cli = request.config.getoption("--bugdb-path")
    return Path(cli) if cli else DEFAULT_BUGDB_PATH


@pytest.fixture(scope="session")
def baseline_path(request: pytest.FixtureRequest) -> Path:
    """Resolved path to the baseline snapshot JSON."""
    cli = request.config.getoption("--baseline-path")
    return Path(cli) if cli else DEFAULT_BASELINE_PATH


@pytest.fixture(scope="session")
def bugdb_json(bugdb_path: Path) -> dict[str, Any]:
    """Load assets/bugdb.json exactly once per session."""
    if not bugdb_path.exists():
        pytest.fail(
            f"Bug database file not found: {bugdb_path}. "
            f"Run `uv run bugdb fetch` first or pass --bugdb-path."
        )
    with bugdb_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="session")
def current_snapshot(bugdb_json: dict[str, Any]) -> BaselineSnapshot:
    """Build a fresh fingerprint of the current bugdb.json.

    Reusing the same function as the baseline saver guarantees that the
    comparison is apples-to-apples.
    """
    return build_baseline(bugdb_json)


@pytest.fixture(scope="session")
def baseline(
    baseline_path: Path, current_snapshot: BaselineSnapshot, request: pytest.FixtureRequest
) -> Baseline:
    """Load the committed baseline.

    If `BUGDB_REFRESH_BASELINE=1` is set, rewrite the baseline from the
    current data instead and fail the session cleanly.
    """
    if os.environ.get(REFRESH_ENV_VAR) == "1":
        save_baseline(current_snapshot, baseline_path)
        request.config._bugdb_baseline_refreshed = True  # type: ignore[attr-defined]
        pytest.skip(
            f"{REFRESH_ENV_VAR}=1: baseline rewritten at {baseline_path}. "
            f"Review the diff and commit."
        )

    if not baseline_path.exists():
        pytest.fail(
            f"Baseline not found: {baseline_path}. "
            f"Create one with `{REFRESH_ENV_VAR}=1 uv run pytest "
            f"tests/integration/ -m data_baseline`."
        )
    return load_baseline(baseline_path)


@pytest.fixture(scope="session")
def baseline_product_version_pairs(baseline: Baseline) -> list[tuple[str, str]]:
    """Sorted (product_id, version) pairs present in the baseline."""
    return sorted(
        (pid, ver)
        for pid, product in baseline.snapshot.products.items()
        for ver in product.versions
    )


def pytest_terminal_summary(terminalreporter: Any, exitstatus: int, config: pytest.Config) -> None:
    """Print a friendly banner if the baseline was just refreshed."""
    if getattr(config, "_bugdb_baseline_refreshed", False):
        terminalreporter.write_sep("=", "BASELINE REFRESHED")
        terminalreporter.write_line(
            f"{REFRESH_ENV_VAR}=1 was set. A fresh baseline has been written."
        )
        terminalreporter.write_line(
            "Review `git diff tests/baselines/data_baseline.json` and commit "
            "explicitly. Do NOT commit a refreshed baseline without reviewing "
            "count deltas and missing bug_ids."
        )
