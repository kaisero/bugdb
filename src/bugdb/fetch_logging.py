"""Logging setup and summary formatting for ``bugdb fetch``.

This module exposes two small helpers:

- :func:`configure_fetch_logging` — a context manager that attaches a
  ``FileHandler`` to the ``bugdb`` root logger for the duration of a
  fetch run (when ``log_file`` is set) and an optional stderr
  ``StreamHandler`` for live ``--debug`` output. It cleans up both
  handlers on exit so tests don't leak state across cases and a
  chained ``bugdb build`` run only captures the fetch stage.

- :func:`format_fetch_summary` — a pure function that renders a
  :class:`bugdb.models.FetchReport` as a multi-line human-readable
  summary. The CLI feeds the lines into ``logger.info`` so the
  file handler timestamps each one consistently with the streaming
  per-version events above it. Separating rendering from emission
  lets tests drive the formatter with in-memory ``FetchReport``
  instances and assert the output byte-for-byte.

Rationale
---------

Before this module landed, ``bugdb fetch`` had two half-working output
channels: ``BaseCrawler._log()`` printed directly to stdout when
``verbose=True`` (but the CLI never set ``verbose``), and a helper
called ``configure_logging`` attached a ``StreamHandler`` to
``bugdb.crawlers.utils`` — the wrong logger node, so events from
``bugdb.crawlers.base`` and the product modules never reached it.
Running ``--debug`` mostly worked only because the stdout print
fallback overlapped with what debug would have shown.

This helper fixes both problems by attaching handlers to the
``bugdb`` root logger, which is the ancestor of every ``bugdb.*``
logger the crawlers actually use, so propagation carries every
event to the handler correctly. The ``verbose`` / stdout-print
branch is retired as part of the same change.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bugdb.models import FetchReport

_FORMATTER = logging.Formatter(
    "%(asctime)s - %(name)-40s - %(levelname)-7s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


@contextmanager
def configure_fetch_logging(
    log_file: Path | None,
    *,
    debug: bool = False,
) -> Iterator[None]:
    """Attach fetch-scoped logging handlers to the ``bugdb`` root logger.

    Two handlers are managed here, independently:

    - **FileHandler** — if ``log_file`` is set, a ``FileHandler`` in
      write mode is attached at ``INFO`` level (or ``DEBUG`` if
      ``debug`` is True). Every event emitted through any
      ``logging.getLogger("bugdb.*")`` call during the ``with``
      block lands in the file with consistent timestamps.

    - **Stderr StreamHandler** — if ``debug`` is True, a
      ``StreamHandler`` pointed at ``sys.stderr`` is attached at
      ``DEBUG`` level. Stderr (not stdout) is used deliberately so
      live debug output doesn't tear Rich's live progress bars,
      which render on stdout.

    Both handlers are removed on context exit (even when fetch
    raises) so tests and chained CLI commands don't leak handler
    state.

    Args:
        log_file: Path to write the streaming fetch log, or ``None``
            to disable the file channel. Parent directories are
            created if missing. Existing files are truncated —
            ``bugdb fetch`` is a one-shot tool and append-mode would
            confuse users comparing runs.
        debug: When True, both the file handler (if any) and the
            stderr handler drop to ``DEBUG`` level, so every
            ``logger.debug(...)`` call throughout the crawler tree
            becomes visible.

    Yields:
        ``None``. The context manager exists purely for handler
        lifecycle; the caller's logger calls are unmodified.
    """
    root = logging.getLogger("bugdb")
    handlers: list[logging.Handler] = []

    file_level = logging.DEBUG if debug else logging.INFO
    stream_level = logging.DEBUG

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, mode="w", encoding="utf-8")
        file_handler.setLevel(file_level)
        file_handler.setFormatter(_FORMATTER)
        root.addHandler(file_handler)
        handlers.append(file_handler)

    if debug:
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setLevel(stream_level)
        stream_handler.setFormatter(_FORMATTER)
        root.addHandler(stream_handler)
        handlers.append(stream_handler)

    # Ensure the root logger's effective level is low enough for the
    # installed handlers to actually see events. Don't clobber a
    # stricter caller-set level — only lower it.
    previous_level = root.level
    required_level = min([h.level for h in handlers], default=previous_level)
    if previous_level == logging.NOTSET or previous_level > required_level:
        root.setLevel(required_level)

    try:
        yield
    finally:
        for handler in handlers:
            try:
                handler.flush()
            finally:
                handler.close()
                root.removeHandler(handler)
        if previous_level == logging.NOTSET:
            # Restore "no explicit level set" — otherwise we'd leave
            # a sticky level on the bugdb logger that carries into
            # the next run.
            root.setLevel(logging.NOTSET)
        else:
            root.setLevel(previous_level)


def format_fetch_summary(report: FetchReport) -> str:
    """Render a :class:`FetchReport` as a human-readable summary block.

    The output is a multi-line string. Each line is self-contained so
    a caller can split on ``\n`` and feed them into
    ``logger.info(...)`` one at a time, letting a log-file handler
    timestamp them consistently with the streaming events that
    precede the summary.

    Shape::

        ======================================================================
        Fetch Summary
        ======================================================================
        Products fetched:    3
        Total versions:      42
        Known issues:        1,843
        Addressed issues:    3,201
        Failed fetches:      1

        Per-product breakdown:
          PAN-OS                  :  15 versions,   945 known,  1,822 addressed,  0 failed
          GlobalProtect           :  32 versions,   241 known,    519 addressed,  0 failed
          Prisma Access           :   8 versions,   116 known,    203 addressed,  1 failed

        Failed fetches:
          ! panos        11.2.3  known     https://docs.paloaltonetworks.com/.../pan-os-11-2-3-known-issues
            └─ Timeout after 30000ms

    The "Failed fetches:" section is omitted entirely when there are
    no failures, so a clean run produces a tight summary.
    """
    lines: list[str] = []
    bar = "=" * 70
    lines.append(bar)
    lines.append("Fetch Summary")
    lines.append(bar)
    lines.append(f"Products fetched:    {report.total_products}")
    lines.append(f"Total versions:      {report.total_versions}")
    lines.append(f"Known issues:        {report.total_known_issues:,}")
    lines.append(f"Addressed issues:    {report.total_addressed_issues:,}")
    lines.append(f"Failed fetches:      {len(report.failed_fetches)}")

    if report.product_stats:
        lines.append("")
        lines.append("Per-product breakdown:")
        for stats in report.product_stats:
            lines.append(
                f"  {stats.product_name:<24}: "
                f"{stats.versions_fetched:>3} versions, "
                f"{stats.known_issues_count:>5} known, "
                f"{stats.addressed_issues_count:>5} addressed, "
                f"{stats.failed_fetch_count:>2} failed"
            )
            if stats.versions:
                versions_str = ", ".join(stats.versions[:20])
                if len(stats.versions) > 20:
                    versions_str += f" (+{len(stats.versions) - 20} more)"
                lines.append(f"    versions: {versions_str}")

    if report.failed_fetches:
        lines.append("")
        lines.append("Failed fetches:")
        for entry in report.failed_fetches:
            version = entry.version or "-"
            issue_type = entry.issue_type or "-"
            lines.append(f"  ! {entry.product:<12} {version:<7} {issue_type:<9} {entry.url}")
            lines.append(f"    └─ {entry.error}")

    return "\n".join(lines)


__all__ = [
    "configure_fetch_logging",
    "format_fetch_summary",
]
