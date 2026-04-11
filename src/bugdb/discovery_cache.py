"""Persistent discovery cache for the crawler.

This module persists two things across `bugdb fetch` invocations:

1. **URL pattern resolution** — PAN-OS (and 4 other crawlers) probe multiple
   URL templates per major version (``/ngfw/release-notes/<v>`` and
   ``/pan-os/<v>/pan-os-release-notes``). Probing costs ~60 HTTP requests per
   run across 5 crawlers. Caching the resolved pattern eliminates those
   probes on warm runs.

2. **Discovered version infos** — every crawl invocation currently re-runs
   ``discover_versions`` (probes) + ``discover_version_pages`` (per-major
   index fetches) even in incremental mode, costing another ~125-210 requests
   per warm run. Caching the resulting ``VersionInfo`` objects lets
   incremental mode skip discovery entirely when the cache is fresh.

The cache is backed by a single JSON file at ``.cache/bugdb/discovery.json``
relative to the repo root, with a 24-hour TTL. Writes are atomic via a
``.tmp`` intermediate + ``os.replace`` so a SIGKILL during save can't
corrupt the file. Corrupt or schema-mismatched caches are logged and
discarded — there is no migration path for schema v1.

Canary staleness is bounded to ~24h by this TTL alone; the separate
``upstream-canary`` test tier runs nightly and catches any upstream drift
the cache happens to miss.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from bugdb.crawlers.models import VersionInfo

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
TTL_SECONDS = 24 * 3600
DEFAULT_CACHE_PATH = (
    Path(__file__).resolve().parents[2] / ".cache" / "bugdb" / "discovery.json"
)


class DiscoveryCache:
    """JSON-backed persistent cache for URL patterns and discovered versions.

    One instance per ``bugdb fetch`` run. Shared across crawlers via the
    ``BaseCrawler`` constructor. Not thread-safe — the crawler is a
    single-process tool.
    """

    def __init__(self, path: Path | None = None):
        self.path = path or DEFAULT_CACHE_PATH
        self._data: dict[str, Any] = self._load()

    # ------------------------------------------------------------------
    # Load / save
    # ------------------------------------------------------------------

    def _empty(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "products": {},
        }

    def _load(self) -> dict[str, Any]:
        """Read the cache file. On any error, start fresh.

        We deliberately catch a broad set of exceptions and log a warning
        rather than raise — a corrupt cache should never block a crawl.
        """
        if not self.path.exists():
            return self._empty()
        try:
            with self.path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(
                "Discovery cache at %s is unreadable (%s); starting fresh.",
                self.path,
                e,
            )
            return self._empty()

        if not isinstance(payload, dict):
            logger.warning(
                "Discovery cache at %s has unexpected shape; starting fresh.",
                self.path,
            )
            return self._empty()

        schema_version = payload.get("schema_version")
        if schema_version != SCHEMA_VERSION:
            logger.warning(
                "Discovery cache at %s has schema_version=%r (expected %d); "
                "starting fresh.",
                self.path,
                schema_version,
                SCHEMA_VERSION,
            )
            return self._empty()

        # Ensure required top-level key exists.
        if not isinstance(payload.get("products"), dict):
            payload["products"] = {}
        return payload

    def save(self) -> None:
        """Write the cache atomically to disk.

        Uses a ``.tmp`` intermediate file and ``os.replace`` so a SIGKILL
        during write can't leave the cache in a partially-written state.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as fh:
            json.dump(self._data, fh, indent=2, sort_keys=True, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp_path, self.path)

    # ------------------------------------------------------------------
    # Freshness
    # ------------------------------------------------------------------

    def is_fresh(self, product_id: str) -> bool:
        """Return True if this product's cache entry is less than 24h old.

        A missing or unparseable ``updated_at`` counts as stale.
        """
        entry = self._data["products"].get(product_id)
        if not entry:
            return False
        updated_at_raw = entry.get("updated_at")
        if not updated_at_raw:
            return False
        try:
            updated_at = datetime.fromisoformat(updated_at_raw)
        except ValueError:
            return False
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=UTC)
        age = datetime.now(UTC) - updated_at
        return age < timedelta(seconds=TTL_SECONDS)

    # ------------------------------------------------------------------
    # URL patterns (S1)
    # ------------------------------------------------------------------

    def get_url_pattern(self, product_id: str, major: str) -> str | None:
        """Return the cached URL pattern for a (product, major), or None.

        Staleness check is the caller's responsibility — callers that care
        should ``is_fresh(product_id)`` first. We return the raw value
        even if stale so that callers can implement grace-period behaviour
        if they want.
        """
        entry = self._data["products"].get(product_id)
        if not entry:
            return None
        return entry.get("url_patterns", {}).get(major)

    def put_url_pattern(self, product_id: str, major: str, url: str) -> None:
        """Record a resolved URL pattern and bump the product's ``updated_at``."""
        entry = self._ensure_product(product_id)
        entry.setdefault("url_patterns", {})[major] = url
        entry["updated_at"] = _now_iso()

    # ------------------------------------------------------------------
    # Version infos (S3)
    # ------------------------------------------------------------------

    def get_version_infos(
        self, product_id: str
    ) -> dict[str, list[VersionInfo]] | None:
        """Return the cached ``{major: [VersionInfo, ...]}`` map or None.

        Returns None if there's no entry or if the entry is stale (older
        than TTL). Callers should treat None as "fall through to full
        discovery".
        """
        if not self.is_fresh(product_id):
            return None
        entry = self._data["products"].get(product_id)
        if not entry:
            return None
        raw = entry.get("version_infos")
        if not isinstance(raw, dict):
            return None
        try:
            return {
                major: [
                    VersionInfo(
                        version=vi["version"],
                        known_issues_urls=list(vi.get("known_issues_urls", [])),
                        addressed_issues_urls=list(vi.get("addressed_issues_urls", [])),
                    )
                    for vi in vi_list
                ]
                for major, vi_list in raw.items()
            }
        except (KeyError, TypeError) as e:
            logger.warning(
                "Discovery cache for %s has unexpected version_infos shape (%s); "
                "treating as miss.",
                product_id,
                e,
            )
            return None

    def put_version_infos(
        self,
        product_id: str,
        version_infos_by_major: dict[str, list[VersionInfo]],
    ) -> None:
        """Record discovered VersionInfo objects and bump ``updated_at``."""
        entry = self._ensure_product(product_id)
        entry["version_infos"] = {
            major: [asdict(vi) for vi in vi_list]
            for major, vi_list in version_infos_by_major.items()
        }
        entry["updated_at"] = _now_iso()

    # ------------------------------------------------------------------
    # Invalidation
    # ------------------------------------------------------------------

    def invalidate(self, product_id: str | None = None) -> None:
        """Drop cache entries.

        With ``product_id=None``, wipes everything (used by the
        ``--refresh-discovery`` CLI flag). With a specific id, drops just
        that product's entry.
        """
        if product_id is None:
            self._data = self._empty()
        else:
            self._data["products"].pop(product_id, None)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _ensure_product(self, product_id: str) -> dict[str, Any]:
        entry = self._data["products"].get(product_id)
        if entry is None:
            entry = {"updated_at": _now_iso(), "url_patterns": {}, "version_infos": {}}
            self._data["products"][product_id] = entry
        return entry


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
