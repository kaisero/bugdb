"""Tests for src/bugdb/discovery_cache.py.

The discovery cache is load-bearing for the crawler's warm-run
optimization: if the cache is silently stale or corrupt, we either
re-probe unnecessarily (performance regression) or serve obsolete URLs
(correctness regression). These tests pin the invariants:

- Round-trip: put → save → load returns the same value
- TTL: entries older than 24h are not fresh
- Corrupt file: logged and discarded, never raises
- Schema mismatch: same
- Atomic write: no .tmp files left behind after save
- Invalidation: per-product and wholesale
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from bugdb.crawlers.models import VersionInfo
from bugdb.discovery_cache import (
    SCHEMA_VERSION,
    TTL_SECONDS,
    DiscoveryCache,
)


@pytest.fixture
def cache_path(tmp_path: Path) -> Path:
    """Isolated cache file path for each test."""
    return tmp_path / "discovery.json"


class TestRoundTrip:
    """A put followed by a get returns the same value."""

    def test_url_pattern_round_trip(self, cache_path: Path):
        cache = DiscoveryCache(path=cache_path)
        cache.put_url_pattern("panos", "12-1", "/ngfw/release-notes/12-1")
        assert cache.get_url_pattern("panos", "12-1") == "/ngfw/release-notes/12-1"

    def test_url_pattern_survives_save_load(self, cache_path: Path):
        cache = DiscoveryCache(path=cache_path)
        cache.put_url_pattern("panos", "12-1", "/ngfw/release-notes/12-1")
        cache.save()

        reloaded = DiscoveryCache(path=cache_path)
        assert reloaded.get_url_pattern("panos", "12-1") == "/ngfw/release-notes/12-1"

    def test_version_infos_round_trip(self, cache_path: Path):
        cache = DiscoveryCache(path=cache_path)
        vi = VersionInfo(
            version="12.1.5",
            known_issues_urls=["/path/pan-os-12-1-5-known-issues"],
            addressed_issues_urls=["/path/pan-os-12-1-5-addressed-issues"],
        )
        cache.put_version_infos("panos", {"12-1": [vi]})
        cache.save()

        reloaded = DiscoveryCache(path=cache_path)
        result = reloaded.get_version_infos("panos")
        assert result is not None
        assert "12-1" in result
        assert result["12-1"] == [vi]

    def test_multiple_products_isolated(self, cache_path: Path):
        cache = DiscoveryCache(path=cache_path)
        cache.put_url_pattern("panos", "12-1", "/ngfw/release-notes/12-1")
        cache.put_url_pattern("globalprotect", "6-2", "/globalprotect/6-2/release-notes")
        cache.save()

        reloaded = DiscoveryCache(path=cache_path)
        assert reloaded.get_url_pattern("panos", "12-1") == "/ngfw/release-notes/12-1"
        assert (
            reloaded.get_url_pattern("globalprotect", "6-2")
            == "/globalprotect/6-2/release-notes"
        )


class TestFreshness:
    """TTL semantics."""

    def test_fresh_entry_is_fresh(self, cache_path: Path):
        cache = DiscoveryCache(path=cache_path)
        cache.put_url_pattern("panos", "12-1", "/ngfw/release-notes/12-1")
        assert cache.is_fresh("panos") is True

    def test_missing_product_is_not_fresh(self, cache_path: Path):
        cache = DiscoveryCache(path=cache_path)
        assert cache.is_fresh("panos") is False

    def test_expired_entry_is_not_fresh(self, cache_path: Path):
        """Entry older than TTL_SECONDS counts as stale."""
        cache = DiscoveryCache(path=cache_path)
        cache.put_url_pattern("panos", "12-1", "/ngfw/release-notes/12-1")
        # Backdate the entry directly in the in-memory state.
        old = datetime.now(UTC) - timedelta(seconds=TTL_SECONDS + 60)
        cache._data["products"]["panos"]["updated_at"] = old.isoformat(timespec="seconds")
        assert cache.is_fresh("panos") is False

    def test_malformed_updated_at_is_not_fresh(self, cache_path: Path):
        cache = DiscoveryCache(path=cache_path)
        cache._data["products"]["panos"] = {"updated_at": "not-a-date"}
        assert cache.is_fresh("panos") is False

    def test_get_version_infos_returns_none_when_stale(self, cache_path: Path):
        """Stale version_infos should act like a cache miss."""
        cache = DiscoveryCache(path=cache_path)
        cache.put_version_infos("panos", {"12-1": [VersionInfo("12.1.5", [], [])]})
        old = datetime.now(UTC) - timedelta(seconds=TTL_SECONDS + 60)
        cache._data["products"]["panos"]["updated_at"] = old.isoformat(timespec="seconds")
        assert cache.get_version_infos("panos") is None


class TestCorruptOrMissing:
    """Bad input never raises — always logs and starts fresh."""

    def test_missing_file_starts_empty(self, cache_path: Path):
        assert not cache_path.exists()
        cache = DiscoveryCache(path=cache_path)
        assert cache.get_url_pattern("panos", "12-1") is None
        assert cache.get_version_infos("panos") is None

    def test_corrupt_json_starts_fresh(self, cache_path: Path, caplog):
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text("{not valid json")
        with caplog.at_level("WARNING"):
            cache = DiscoveryCache(path=cache_path)
        assert cache.get_url_pattern("panos", "12-1") is None
        assert any("unreadable" in rec.message.lower() for rec in caplog.records)

    def test_schema_version_mismatch_starts_fresh(self, cache_path: Path, caplog):
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(
                {
                    "schema_version": 999,
                    "products": {"panos": {"url_patterns": {"12-1": "/stale"}}},
                }
            )
        )
        with caplog.at_level("WARNING"):
            cache = DiscoveryCache(path=cache_path)
        assert cache.get_url_pattern("panos", "12-1") is None
        assert any("schema_version" in rec.message for rec in caplog.records)

    def test_non_dict_payload_starts_fresh(self, cache_path: Path, caplog):
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(["unexpected", "list"]))
        with caplog.at_level("WARNING"):
            cache = DiscoveryCache(path=cache_path)
        assert cache.get_url_pattern("panos", "12-1") is None

    def test_malformed_version_infos_treated_as_miss(self, cache_path: Path, caplog):
        """If version_infos has a broken shape, we fall through to full discovery."""
        cache = DiscoveryCache(path=cache_path)
        cache._data["products"]["panos"] = {
            "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "version_infos": {"12-1": [{"bogus": "shape"}]},
        }
        with caplog.at_level("WARNING"):
            result = cache.get_version_infos("panos")
        assert result is None


class TestAtomicWrite:
    """Writes are atomic via .tmp + os.replace."""

    def test_save_creates_file(self, cache_path: Path):
        cache = DiscoveryCache(path=cache_path)
        cache.put_url_pattern("panos", "12-1", "/ngfw/release-notes/12-1")
        cache.save()
        assert cache_path.exists()

    def test_no_tmp_file_left_behind(self, cache_path: Path):
        cache = DiscoveryCache(path=cache_path)
        cache.put_url_pattern("panos", "12-1", "/ngfw/release-notes/12-1")
        cache.save()
        tmp_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
        assert not tmp_path.exists()

    def test_saved_content_is_valid_json(self, cache_path: Path):
        cache = DiscoveryCache(path=cache_path)
        cache.put_url_pattern("panos", "12-1", "/ngfw/release-notes/12-1")
        cache.save()
        payload = json.loads(cache_path.read_text())
        assert payload["schema_version"] == SCHEMA_VERSION
        assert payload["products"]["panos"]["url_patterns"]["12-1"] == (
            "/ngfw/release-notes/12-1"
        )

    def test_save_creates_parent_directory(self, tmp_path: Path):
        """Parent directory is created on demand — default .cache/bugdb/ may not exist."""
        deep_path = tmp_path / "nested" / "deeper" / "discovery.json"
        cache = DiscoveryCache(path=deep_path)
        cache.put_url_pattern("panos", "12-1", "/ngfw/release-notes/12-1")
        cache.save()
        assert deep_path.exists()


class TestInvalidate:
    """Invalidate drops entries but never raises."""

    def test_invalidate_single_product(self, cache_path: Path):
        cache = DiscoveryCache(path=cache_path)
        cache.put_url_pattern("panos", "12-1", "/ngfw/release-notes/12-1")
        cache.put_url_pattern("globalprotect", "6-2", "/gp/6-2/release-notes")

        cache.invalidate("panos")

        assert cache.get_url_pattern("panos", "12-1") is None
        assert cache.get_url_pattern("globalprotect", "6-2") == "/gp/6-2/release-notes"

    def test_invalidate_all_wipes_everything(self, cache_path: Path):
        cache = DiscoveryCache(path=cache_path)
        cache.put_url_pattern("panos", "12-1", "/ngfw/release-notes/12-1")
        cache.put_url_pattern("globalprotect", "6-2", "/gp/6-2/release-notes")

        cache.invalidate()

        assert cache.get_url_pattern("panos", "12-1") is None
        assert cache.get_url_pattern("globalprotect", "6-2") is None

    def test_invalidate_missing_product_is_noop(self, cache_path: Path):
        cache = DiscoveryCache(path=cache_path)
        cache.invalidate("does-not-exist")  # does not raise


class TestCacheShape:
    """Defensive checks on the file format."""

    def test_put_url_pattern_bumps_updated_at(self, cache_path: Path):
        cache = DiscoveryCache(path=cache_path)

        # Freeze the first write at T-0, then advance.
        t0 = datetime(2026, 4, 11, 12, 0, 0, tzinfo=UTC)
        with patch("bugdb.discovery_cache._now_iso", return_value=t0.isoformat(timespec="seconds")):
            cache.put_url_pattern("panos", "12-1", "/ngfw/release-notes/12-1")
        first = cache._data["products"]["panos"]["updated_at"]

        t1 = t0 + timedelta(seconds=120)
        with patch("bugdb.discovery_cache._now_iso", return_value=t1.isoformat(timespec="seconds")):
            cache.put_url_pattern("panos", "11-2", "/pan-os/11-2/release-notes")
        second = cache._data["products"]["panos"]["updated_at"]

        assert second > first
