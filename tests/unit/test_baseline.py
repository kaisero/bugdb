"""Unit tests for bugdb.baseline — the snapshot/diff module that the
integration tier depends on.

These live in the flat tests/ tree (not tests/integration/) because they
are fast, pure-Python, and must always run as part of the default pytest
invocation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bugdb.baseline import (
    SCHEMA_VERSION,
    Baseline,
    BaselineSnapshot,
    build_baseline,
    diff_snapshots,
    format_diff,
    load_baseline,
    save_baseline,
)


@pytest.fixture
def sample_data() -> dict:
    """A minimal two-product data.json payload."""
    return {
        "metadata": {"generated_at": "2026-04-11T00:00:00Z"},
        "products": [
            {
                "id": "panos",
                "name": "PAN-OS",
                "versions": [
                    {
                        "version": "11.2.11",
                        "known_issues": [
                            {"bug_id": "PAN-1", "description": "one"},
                            {"bug_id": "PAN-2", "description": "two"},
                        ],
                        "addressed_issues": [
                            {"bug_id": "PAN-3", "description": "three"},
                        ],
                    },
                    {
                        "version": "11.2.10",
                        "known_issues": [],
                        "addressed_issues": [
                            {"bug_id": "PAN-4", "description": "four"},
                        ],
                    },
                ],
            },
            {
                "id": "globalprotect",
                "name": "GlobalProtect",
                "versions": [
                    {
                        "version": "6.2.1",
                        "known_issues": [
                            {"bug_id": "GP-100", "description": "gp one"},
                        ],
                        "addressed_issues": [],
                    }
                ],
            },
        ],
    }


class TestBuildBaseline:
    def test_produces_one_entry_per_product_version(self, sample_data):
        snapshot = build_baseline(sample_data)
        assert set(snapshot.products.keys()) == {"panos", "globalprotect"}
        assert set(snapshot.products["panos"].versions.keys()) == {
            "11.2.11",
            "11.2.10",
        }

    def test_records_issue_counts(self, sample_data):
        snapshot = build_baseline(sample_data)
        v = snapshot.products["panos"].versions["11.2.11"]
        assert v.known == 2
        assert v.addressed == 1

    def test_records_sorted_bug_ids_from_both_sides(self, sample_data):
        snapshot = build_baseline(sample_data)
        v = snapshot.products["panos"].versions["11.2.11"]
        assert v.bug_ids == ("PAN-1", "PAN-2", "PAN-3")

    def test_skips_issues_without_bug_id(self):
        data = {
            "products": [
                {
                    "id": "x",
                    "versions": [
                        {
                            "version": "1.0.0",
                            "known_issues": [
                                {"bug_id": "", "description": "empty id"},
                                {"description": "missing id"},
                                {"bug_id": "X-1", "description": "good"},
                            ],
                            "addressed_issues": [],
                        }
                    ],
                }
            ]
        }
        snapshot = build_baseline(data)
        v = snapshot.products["x"].versions["1.0.0"]
        # Count is the raw list length — we don't silently drop on count.
        assert v.known == 3
        assert v.bug_ids == ("X-1",)

    def test_skips_products_without_id(self):
        data = {
            "products": [
                {"id": "", "versions": []},
                {"versions": []},
                {"id": "valid", "versions": []},
            ]
        }
        snapshot = build_baseline(data)
        assert set(snapshot.products.keys()) == {"valid"}

    def test_output_is_deterministic_between_runs(self, sample_data):
        a = build_baseline(sample_data)
        b = build_baseline(sample_data)
        assert a == b

    def test_products_and_versions_sorted_deterministically(self, sample_data):
        # Shuffle input order, expect same output.
        data = {
            "products": list(reversed(sample_data["products"])),
        }
        snapshot = build_baseline(data)
        assert list(snapshot.products.keys()) == ["globalprotect", "panos"]


class TestSaveAndLoad:
    def test_roundtrip_preserves_structure(self, sample_data, tmp_path: Path):
        snapshot = build_baseline(sample_data)
        path = tmp_path / "baseline.json"
        save_baseline(snapshot, path, captured_at="2026-04-11T00:00:00+00:00")

        loaded = load_baseline(path)
        assert loaded.schema_version == SCHEMA_VERSION
        assert loaded.captured_at == "2026-04-11T00:00:00+00:00"
        assert loaded.snapshot == snapshot

    def test_written_file_has_trailing_newline(self, sample_data, tmp_path: Path):
        snapshot = build_baseline(sample_data)
        path = tmp_path / "baseline.json"
        save_baseline(snapshot, path)
        assert path.read_text().endswith("\n")

    def test_load_rejects_unknown_schema_version(self, tmp_path: Path):
        path = tmp_path / "baseline.json"
        path.write_text(json.dumps({"schema_version": 999, "products": {}}))
        with pytest.raises(ValueError, match="schema_version"):
            load_baseline(path)

    def test_load_rejects_missing_schema_version(self, tmp_path: Path):
        path = tmp_path / "baseline.json"
        path.write_text(json.dumps({"products": {}}))
        with pytest.raises(ValueError, match="schema_version"):
            load_baseline(path)


class TestDiff:
    def _mk_baseline(self, snapshot: BaselineSnapshot) -> Baseline:
        return Baseline(
            schema_version=SCHEMA_VERSION,
            captured_at="2026-04-11T00:00:00+00:00",
            snapshot=snapshot,
        )

    def test_clean_diff_when_current_matches_baseline(self, sample_data):
        snapshot = build_baseline(sample_data)
        baseline = self._mk_baseline(snapshot)
        diff = diff_snapshots(baseline, snapshot)
        assert diff.is_clean
        assert diff.products_added == []
        assert diff.versions_added == []

    def test_detects_removed_product(self, sample_data):
        baseline = self._mk_baseline(build_baseline(sample_data))
        current_data = {
            "products": [p for p in sample_data["products"] if p["id"] != "globalprotect"]
        }
        current = build_baseline(current_data)
        diff = diff_snapshots(baseline, current)
        assert diff.products_removed == ["globalprotect"]
        assert not diff.is_clean

    def test_detects_removed_version(self, sample_data):
        baseline = self._mk_baseline(build_baseline(sample_data))
        current_data = dict(sample_data)
        current_data["products"] = [
            {**p, "versions": [v for v in p["versions"] if v["version"] != "11.2.10"]}
            if p["id"] == "panos"
            else p
            for p in sample_data["products"]
        ]
        current = build_baseline(current_data)
        diff = diff_snapshots(baseline, current)
        assert ("panos", "11.2.10") in diff.versions_removed

    def test_detects_count_regression(self, sample_data):
        baseline = self._mk_baseline(build_baseline(sample_data))
        current_data = dict(sample_data)
        current_data["products"] = [
            {
                **p,
                "versions": [
                    (
                        {**v, "known_issues": v["known_issues"][:1]}
                        if v["version"] == "11.2.11"
                        else v
                    )
                    for v in p["versions"]
                ],
            }
            if p["id"] == "panos"
            else p
            for p in sample_data["products"]
        ]
        current = build_baseline(current_data)
        diff = diff_snapshots(baseline, current)
        assert any(
            pid == "panos" and ver == "11.2.11" and issue_type == "known"
            for pid, ver, issue_type, _b, _c in diff.count_regressions
        )

    def test_detects_missing_bug_ids(self, sample_data):
        baseline = self._mk_baseline(build_baseline(sample_data))
        current_data = {
            "products": [
                {
                    **p,
                    "versions": [
                        (
                            {
                                **v,
                                "known_issues": [{"bug_id": "PAN-999", "description": "swap"}],
                            }
                            if v["version"] == "11.2.11"
                            else v
                        )
                        for v in p["versions"]
                    ],
                }
                if p["id"] == "panos"
                else p
                for p in sample_data["products"]
            ]
        }
        current = build_baseline(current_data)
        diff = diff_snapshots(baseline, current)
        # Counts regressed (2 known -> 1), AND bug_ids are missing.
        assert any(pid == "panos" and ver == "11.2.11" for pid, ver, _ in diff.missing_bug_ids)

    def test_diff_is_clean_when_counts_grow(self, sample_data):
        baseline = self._mk_baseline(build_baseline(sample_data))
        current_data = {
            "products": [
                {
                    **p,
                    "versions": [
                        (
                            {
                                **v,
                                "known_issues": v["known_issues"]
                                + [{"bug_id": "PAN-NEW", "description": "new"}],
                            }
                            if v["version"] == "11.2.11"
                            else v
                        )
                        for v in p["versions"]
                    ],
                }
                if p["id"] == "panos"
                else p
                for p in sample_data["products"]
            ]
        }
        current = build_baseline(current_data)
        diff = diff_snapshots(baseline, current)
        assert diff.is_clean
        assert diff.count_regressions == []

    def test_format_diff_handles_clean_state(self, sample_data):
        snapshot = build_baseline(sample_data)
        baseline = self._mk_baseline(snapshot)
        text = format_diff(diff_snapshots(baseline, snapshot))
        assert "No changes" in text

    def test_format_diff_highlights_regressions(self, sample_data):
        baseline = self._mk_baseline(build_baseline(sample_data))
        current_data = {
            "products": [
                {
                    **p,
                    "versions": [
                        ({**v, "known_issues": []} if v["version"] == "11.2.11" else v)
                        for v in p["versions"]
                    ],
                }
                if p["id"] == "panos"
                else p
                for p in sample_data["products"]
            ]
        }
        current = build_baseline(current_data)
        text = format_diff(diff_snapshots(baseline, current))
        assert "panos" in text
        assert "11.2.11" in text
        assert "lost 2" in text
