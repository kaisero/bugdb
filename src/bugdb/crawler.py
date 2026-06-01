"""DEPRECATED: use ``bugdb.crawlers`` instead.

This module is a backward-compatibility shim that re-exports the public
API of the modular ``bugdb.crawlers`` package. It exists so that any
third-party script still importing from ``bugdb.crawler`` (singular)
keeps working.

Before v1.0.2 this file contained its own grouped imports and aliases;
the project's own CLI was importing from here, which meant the
"deprecated" label was misleading — it was production code. In v1.0.2
``bugdb.cli`` switched to importing directly from ``bugdb.crawlers``,
so the shim is now genuinely off the live path and can be collapsed
to a simple re-export.

New code should import from ``bugdb.crawlers`` directly::

    # Old (still works, but emits a DeprecationWarning at import time)
    from bugdb.crawler import crawl_panos, PaloAltoCrawler

    # New
    from bugdb.crawlers import crawl_panos
    from bugdb.crawlers import BaseCrawler as PaloAltoCrawler

This shim will be removed in a future major release. Tracked as
roadmap item D5 in ``docs/roadmap.md``.
"""

from __future__ import annotations

import warnings

# Re-export the entire public API. `noqa: F401,F403` — these names exist
# for the backward-compat side-effect of being importable from
# `bugdb.crawler`; ruff's unused-import check can't see that intent.
from bugdb.crawlers import *  # noqa: F403
from bugdb.crawlers import BaseCrawler

# Backward-compatibility alias: older code imported PaloAltoCrawler
# directly from bugdb.crawler. The modular package uses BaseCrawler.
PaloAltoCrawler = BaseCrawler

warnings.warn(
    "bugdb.crawler is a deprecated backward-compatibility shim; "
    "import from bugdb.crawlers instead. This shim will be removed "
    "in a future major release.",
    DeprecationWarning,
    stacklevel=2,
)
