"""Baseline snapshot utilities for data-fidelity integration tests.

A *baseline* is a compressed fingerprint of `assets/bugdb.json`. For every
`(product, version)` pair it records:

- the number of known issues
- the number of addressed issues
- the full set of bug ids (sorted)

The baseline is committed under `tests/baselines/data_baseline.json` and
compared against the current `bugdb.json` by the `tests/integration/` suite
to catch crawler regressions that silently drop data.

This module is the single source of truth for how snapshots are built,
serialised, and loaded — both the test session and the `bugdb baseline
refresh` CLI command import from here.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class VersionFingerprint:
    """Snapshot of a single (product, version) in the baseline."""

    known: int
    addressed: int
    bug_ids: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "known": self.known,
            "addressed": self.addressed,
            "bug_ids": list(self.bug_ids),
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> VersionFingerprint:
        return cls(
            known=int(data["known"]),
            addressed=int(data["addressed"]),
            bug_ids=tuple(data.get("bug_ids", [])),
        )


@dataclass(frozen=True)
class ProductFingerprint:
    """Snapshot of a product — an ordered map of version -> fingerprint."""

    versions: dict[str, VersionFingerprint] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {"versions": {v: f.to_json() for v, f in self.versions.items()}}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> ProductFingerprint:
        versions = {v: VersionFingerprint.from_json(f) for v, f in data.get("versions", {}).items()}
        return cls(versions=versions)


@dataclass(frozen=True)
class BaselineSnapshot:
    """Top-level snapshot payload (without metadata)."""

    products: dict[str, ProductFingerprint] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {pid: p.to_json() for pid, p in self.products.items()}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> BaselineSnapshot:
        products = {pid: ProductFingerprint.from_json(p) for pid, p in data.items()}
        return cls(products=products)


@dataclass(frozen=True)
class Baseline:
    """A loaded baseline plus its metadata."""

    schema_version: int
    captured_at: str | None
    snapshot: BaselineSnapshot

    def product_ids(self) -> list[str]:
        return sorted(self.snapshot.products.keys())

    def version_ids(self, product_id: str) -> list[str]:
        product = self.snapshot.products.get(product_id)
        return sorted(product.versions.keys()) if product else []


def build_baseline(bugdb_json: dict[str, Any]) -> BaselineSnapshot:
    """Compute a fingerprint from a loaded `bugdb.json` dict.

    Accepts the full BugDatabase JSON shape (``{"products": [...]}``).
    Orders product ids and versions deterministically so two runs produce
    byte-identical output for identical inputs.
    """
    products: dict[str, ProductFingerprint] = {}

    for product in bugdb_json.get("products", []):
        pid = product.get("id")
        if not pid:
            continue

        versions: dict[str, VersionFingerprint] = {}
        for version_entry in product.get("versions", []):
            version = version_entry.get("version")
            if not version:
                continue

            known = version_entry.get("known_issues", []) or []
            addressed = version_entry.get("addressed_issues", []) or []

            bug_ids = sorted(_collect_bug_ids(known) | _collect_bug_ids(addressed))

            versions[version] = VersionFingerprint(
                known=len(known),
                addressed=len(addressed),
                bug_ids=tuple(bug_ids),
            )

        # Sort versions deterministically by key for reproducibility.
        sorted_versions = dict(sorted(versions.items()))
        products[pid] = ProductFingerprint(versions=sorted_versions)

    sorted_products = dict(sorted(products.items()))
    return BaselineSnapshot(products=sorted_products)


def _collect_bug_ids(issues: Iterable[dict[str, Any]]) -> set[str]:
    """Extract non-empty bug ids from a list of issue dicts."""
    return {issue["bug_id"] for issue in issues if isinstance(issue, dict) and issue.get("bug_id")}


def save_baseline(
    snapshot: BaselineSnapshot,
    path: Path,
    *,
    captured_at: str | None = None,
) -> None:
    """Write a snapshot to disk with stable ordering and a trailing newline."""
    from datetime import datetime, timezone

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "captured_at": captured_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "products": snapshot.to_json(),
    }
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=False, ensure_ascii=False)
        fh.write("\n")


def load_baseline(path: Path) -> Baseline:
    """Read a baseline from disk."""
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)

    schema_version = int(payload.get("schema_version", 0))
    if schema_version != SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported baseline schema_version {schema_version} "
            f"(this bugdb only understands v{SCHEMA_VERSION}). "
            f"Regenerate the baseline with BUGDB_REFRESH_BASELINE=1."
        )

    snapshot = BaselineSnapshot.from_json(payload.get("products", {}))
    return Baseline(
        schema_version=schema_version,
        captured_at=payload.get("captured_at"),
        snapshot=snapshot,
    )


# --------------------------------------------------------------------------
# Diffing — used by the CLI and by terminal-summary reporting.
# --------------------------------------------------------------------------


@dataclass
class BaselineDiff:
    """A human-readable delta between a baseline and a current snapshot."""

    products_added: list[str] = field(default_factory=list)
    products_removed: list[str] = field(default_factory=list)
    versions_added: list[tuple[str, str]] = field(default_factory=list)
    versions_removed: list[tuple[str, str]] = field(default_factory=list)
    count_regressions: list[tuple[str, str, str, int, int]] = field(
        default_factory=list
    )  # (product, version, issue_type, baseline, current)
    missing_bug_ids: list[tuple[str, str, list[str]]] = field(default_factory=list)
    # (product, version, first-10-missing)

    @property
    def is_clean(self) -> bool:
        return not any(
            [
                self.products_removed,
                self.versions_removed,
                self.count_regressions,
                self.missing_bug_ids,
            ]
        )


def diff_snapshots(baseline: Baseline, current: BaselineSnapshot) -> BaselineDiff:
    """Compute the delta baseline -> current."""
    diff = BaselineDiff()

    baseline_products = set(baseline.snapshot.products.keys())
    current_products = set(current.products.keys())

    diff.products_added = sorted(current_products - baseline_products)
    diff.products_removed = sorted(baseline_products - current_products)

    for pid in sorted(baseline_products & current_products):
        b_versions = baseline.snapshot.products[pid].versions
        c_versions = current.products[pid].versions

        b_version_set = set(b_versions.keys())
        c_version_set = set(c_versions.keys())

        for added_ver in sorted(c_version_set - b_version_set):
            diff.versions_added.append((pid, added_ver))
        for removed_ver in sorted(b_version_set - c_version_set):
            diff.versions_removed.append((pid, removed_ver))

        for ver in sorted(b_version_set & c_version_set):
            b = b_versions[ver]
            c = c_versions[ver]

            if c.known < b.known:
                diff.count_regressions.append((pid, ver, "known", b.known, c.known))
            if c.addressed < b.addressed:
                diff.count_regressions.append((pid, ver, "addressed", b.addressed, c.addressed))

            missing = sorted(set(b.bug_ids) - set(c.bug_ids))
            if missing:
                diff.missing_bug_ids.append((pid, ver, missing[:10]))

    return diff


def format_diff(diff: BaselineDiff) -> str:
    """Render a diff as a human-readable multi-line string."""
    lines: list[str] = []

    if diff.is_clean and not diff.products_added and not diff.versions_added:
        return "No changes."

    if diff.products_added:
        lines.append(f"Products added (+{len(diff.products_added)}):")
        lines.extend(f"  + {p}" for p in diff.products_added)
    if diff.products_removed:
        lines.append(f"Products REMOVED (-{len(diff.products_removed)}) ⚠:")
        lines.extend(f"  - {p}" for p in diff.products_removed)

    if diff.versions_added:
        lines.append(f"Versions added (+{len(diff.versions_added)}):")
        for pid, ver in diff.versions_added[:20]:
            lines.append(f"  + {pid} {ver}")
        if len(diff.versions_added) > 20:
            lines.append(f"  … and {len(diff.versions_added) - 20} more")

    if diff.versions_removed:
        lines.append(f"Versions REMOVED (-{len(diff.versions_removed)}) ⚠:")
        for pid, ver in diff.versions_removed:
            lines.append(f"  - {pid} {ver}")

    if diff.count_regressions:
        lines.append(f"Count regressions ({len(diff.count_regressions)}) ⚠:")
        for pid, ver, issue_type, b, c in diff.count_regressions:
            lines.append(f"  ! {pid} {ver} {issue_type}: {b} -> {c} (lost {b - c})")

    if diff.missing_bug_ids:
        lines.append(f"Versions with missing bug ids ({len(diff.missing_bug_ids)}) ⚠:")
        for pid, ver, sample in diff.missing_bug_ids[:20]:
            sample_str = ", ".join(sample[:5])
            more = f" (+{len(sample) - 5} more)" if len(sample) > 5 else ""
            lines.append(f"  ! {pid} {ver}: {sample_str}{more}")

    return "\n".join(lines)


# --------------------------------------------------------------------------
# CLI entry point — `python -m bugdb.baseline refresh ...`
# --------------------------------------------------------------------------


def _cli() -> int:
    """Minimal CLI for baseline refresh and diff operations."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="bugdb.baseline",
        description="Inspect or refresh the integration-test baseline snapshot.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    refresh = sub.add_parser(
        "refresh",
        help="Print a diff of current vs. baseline and optionally rewrite it.",
    )
    refresh.add_argument("--bugdb", required=True, type=Path, help="Path to assets/bugdb.json")
    refresh.add_argument(
        "--baseline",
        required=True,
        type=Path,
        help="Path to the baseline JSON to write/compare against.",
    )
    refresh.add_argument("--yes", action="store_true", help="Actually write the new baseline.")

    diff_cmd = sub.add_parser("diff", help="Show diff between current bugdb.json and baseline.")
    diff_cmd.add_argument("--bugdb", required=True, type=Path, help="Path to assets/bugdb.json")
    diff_cmd.add_argument("--baseline", required=True, type=Path)

    args = parser.parse_args()

    with args.bugdb.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    current = build_baseline(data)

    if args.command == "diff":
        baseline_obj = load_baseline(args.baseline)
        diff = diff_snapshots(baseline_obj, current)
        print(format_diff(diff))
        return 0 if diff.is_clean else 1

    if args.command == "refresh":
        if args.baseline.exists():
            baseline_obj = load_baseline(args.baseline)
            diff = diff_snapshots(baseline_obj, current)
            print(format_diff(diff))
        else:
            print(f"No existing baseline at {args.baseline}; writing fresh.")
        if not args.yes:
            print()
            print("Dry run only. Re-run with --yes to write the new baseline.")
            return 0
        save_baseline(current, args.baseline)
        print(f"\nBaseline written to {args.baseline}")
        return 0

    return 0  # unreachable — argparse enforces required subcommand


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(_cli())
