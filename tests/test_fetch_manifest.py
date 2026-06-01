"""Tests for FetchManifest."""

from pathlib import Path

from bugdb.fetch_manifest import FetchManifest, ManifestEntry


def test_load_missing_file_returns_empty_manifest(tmp_path: Path):
    m = FetchManifest.load(tmp_path / "manifest.json")
    assert len(m.entries) == 0


def test_should_skip_returns_false_when_url_unknown(tmp_path: Path):
    m = FetchManifest.load(tmp_path / "manifest.json")
    assert m.should_skip("https://x/y", lastmod="2026-01-01") is False


def test_should_skip_returns_true_when_lastmod_matches():
    m = FetchManifest(entries={"https://x/y": ManifestEntry(lastmod="2026-01-01")})
    assert m.should_skip("https://x/y", lastmod="2026-01-01") is True


def test_should_skip_returns_false_when_lastmod_differs():
    m = FetchManifest(entries={"https://x/y": ManifestEntry(lastmod="2026-01-01")})
    assert m.should_skip("https://x/y", lastmod="2026-02-01") is False


def test_should_skip_returns_false_when_no_recorded_lastmod():
    m = FetchManifest(entries={"https://x/y": ManifestEntry(lastmod=None)})
    assert m.should_skip("https://x/y", lastmod="2026-01-01") is False


def test_should_skip_returns_false_when_current_lastmod_missing():
    m = FetchManifest(entries={"https://x/y": ManifestEntry(lastmod="2026-01-01")})
    assert m.should_skip("https://x/y", lastmod=None) is False


def test_round_trip_save_load(tmp_path: Path):
    p = tmp_path / "manifest.json"
    m = FetchManifest(
        entries={
            "https://x/y": ManifestEntry(lastmod="2026-01-01"),
            "https://x/z": ManifestEntry(lastmod=None),
        }
    )
    m.save(p)
    loaded = FetchManifest.load(p)
    assert loaded.entries == m.entries


def test_record_updates_entry():
    m = FetchManifest()
    m.record("https://x/y", lastmod="2026-03-01")
    assert m.entries["https://x/y"].lastmod == "2026-03-01"


def test_record_overwrites_previous_lastmod():
    m = FetchManifest(entries={"https://x/y": ManifestEntry(lastmod="2025-01-01")})
    m.record("https://x/y", lastmod="2026-03-01")
    assert m.entries["https://x/y"].lastmod == "2026-03-01"


def test_save_creates_parent_directory(tmp_path: Path):
    p = tmp_path / "nested" / "dir" / "manifest.json"
    m = FetchManifest(entries={"https://x": ManifestEntry(lastmod="2026-01-01")})
    m.save(p)
    assert p.exists()
