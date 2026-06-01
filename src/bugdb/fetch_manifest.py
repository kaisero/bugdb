"""Persisted record of last-seen <lastmod> per URL.

Stored alongside the data JSON (e.g. `assets/bugdb.manifest.json`).
Read at the start of a fetch, mutated during the fetch as URLs are
processed, and rewritten on success. Lets weekly CI runs skip URLs
whose sitemap timestamp hasn't moved.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field


class ManifestEntry(BaseModel):
    lastmod: str | None = None


class FetchManifest(BaseModel):
    entries: dict[str, ManifestEntry] = Field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> FetchManifest:
        if not path.exists():
            return cls()
        return cls.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.model_dump(mode="json"), indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def should_skip(self, url: str, lastmod: str | None) -> bool:
        """Return True iff this URL's content is known unchanged.

        We require both a stored lastmod and a current lastmod, and they
        must match. Missing data on either side means "fetch to be safe".
        """
        if lastmod is None:
            return False
        prev = self.entries.get(url)
        if prev is None or prev.lastmod is None:
            return False
        return prev.lastmod == lastmod

    def record(self, url: str, lastmod: str | None) -> None:
        self.entries[url] = ManifestEntry(lastmod=lastmod)
