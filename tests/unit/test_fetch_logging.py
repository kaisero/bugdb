"""Tests for the fetch logging helpers.

Two concerns:

1. :func:`configure_fetch_logging` lifecycle — handlers added on
   entry, removed on exit (even when the block raises), file
   contents appear at the right level, stderr handler only attaches
   under ``--debug``.
2. :func:`format_fetch_summary` pure rendering — each section of
   the output (header, totals, per-product breakdown, failed
   fetches) is asserted independently against a hand-built
   :class:`FetchReport`.
"""

from __future__ import annotations

import logging

import pytest

from bugdb.fetch_logging import configure_fetch_logging, format_fetch_summary
from bugdb.models import FailedFetchEntry, FetchReport, ProductStats

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def clean_bugdb_logger():
    """Snapshot the bugdb logger's handlers and level before each test
    and restore them after so no test leaks handler state into the
    next one."""
    logger = logging.getLogger("bugdb")
    saved_handlers = list(logger.handlers)
    saved_level = logger.level
    yield logger
    logger.handlers = saved_handlers
    logger.setLevel(saved_level)


def _make_report(
    *,
    products: int = 2,
    versions: int = 5,
    known: int = 42,
    addressed: int = 17,
    product_stats: list[ProductStats] | None = None,
    failed: list[FailedFetchEntry] | None = None,
) -> FetchReport:
    """Hand-built FetchReport with sensible defaults. Individual
    tests override only the fields they assert on."""
    return FetchReport(
        bugdb_file="assets/bugdb.json",
        total_products=products,
        total_versions=versions,
        total_known_issues=known,
        total_addressed_issues=addressed,
        product_stats=product_stats
        or [
            ProductStats(
                product_id="panos",
                product_name="PAN-OS",
                versions_fetched=3,
                known_issues_count=30,
                addressed_issues_count=15,
                failed_fetch_count=0,
            ),
            ProductStats(
                product_id="gp",
                product_name="GlobalProtect",
                versions_fetched=2,
                known_issues_count=12,
                addressed_issues_count=2,
                failed_fetch_count=0,
            ),
        ],
        failed_fetches=failed or [],
    )


# ---------------------------------------------------------------------------
# configure_fetch_logging
# ---------------------------------------------------------------------------


class TestConfigureFetchLogging:
    """Context manager lifecycle + file output."""

    def test_none_log_file_is_noop(self, clean_bugdb_logger):
        """Passing ``log_file=None`` without ``debug`` attaches no
        handlers — the helper is a zero-cost pass-through."""
        before = list(clean_bugdb_logger.handlers)
        with configure_fetch_logging(None, debug=False):
            assert list(clean_bugdb_logger.handlers) == before

    def test_log_file_adds_and_removes_file_handler(self, clean_bugdb_logger, tmp_path):
        log = tmp_path / "fetch.log"
        before = list(clean_bugdb_logger.handlers)

        with configure_fetch_logging(log, debug=False):
            added = [h for h in clean_bugdb_logger.handlers if h not in before]
            assert len(added) == 1
            assert isinstance(added[0], logging.FileHandler)

        after = list(clean_bugdb_logger.handlers)
        assert after == before

    def test_log_file_captures_child_logger_output(self, clean_bugdb_logger, tmp_path):
        """Events from ``bugdb.crawlers.base`` (a child of the
        ``bugdb`` logger the handler attaches to) must propagate
        into the file."""
        log = tmp_path / "fetch.log"
        crawler_logger = logging.getLogger("bugdb.crawlers.base")

        with configure_fetch_logging(log, debug=False):
            crawler_logger.info("per-version event: 12.1.5 done")
            crawler_logger.warning("retry: transient failure")

        content = log.read_text()
        assert "per-version event: 12.1.5 done" in content
        assert "retry: transient failure" in content
        # The formatter tags the level name, so levels are visible.
        assert "INFO" in content
        assert "WARNING" in content

    def test_parent_directory_is_created(self, clean_bugdb_logger, tmp_path):
        log = tmp_path / "nested" / "dir" / "fetch.log"
        with configure_fetch_logging(log, debug=False):
            logging.getLogger("bugdb").info("hello")
        assert log.exists()

    def test_log_file_truncates_existing_content(self, clean_bugdb_logger, tmp_path):
        """Each fetch run overwrites the file — append mode would
        confuse users comparing runs."""
        log = tmp_path / "fetch.log"
        log.write_text("stale content from a previous run\n")

        with configure_fetch_logging(log, debug=False):
            logging.getLogger("bugdb").info("fresh run")

        content = log.read_text()
        assert "stale content" not in content
        assert "fresh run" in content

    def test_debug_false_filters_debug_events(self, clean_bugdb_logger, tmp_path):
        log = tmp_path / "fetch.log"
        logger = logging.getLogger("bugdb.crawlers.base")

        with configure_fetch_logging(log, debug=False):
            logger.debug("noisy debug event")
            logger.info("user-visible event")

        content = log.read_text()
        assert "noisy debug event" not in content
        assert "user-visible event" in content

    def test_debug_true_captures_debug_events(self, clean_bugdb_logger, tmp_path):
        log = tmp_path / "fetch.log"
        logger = logging.getLogger("bugdb.crawlers.base")

        with configure_fetch_logging(log, debug=True):
            logger.debug("this must appear")
            logger.info("this too")

        content = log.read_text()
        assert "this must appear" in content
        assert "this too" in content

    def test_debug_true_attaches_stderr_stream_handler(self, clean_bugdb_logger, tmp_path, capsys):
        """``--debug`` must route live output to stderr, NOT stdout —
        stdout is where Rich renders its progress bars, so any
        duplicate stream there would tear the UI."""
        log = tmp_path / "fetch.log"

        with configure_fetch_logging(log, debug=True):
            logging.getLogger("bugdb.crawlers.base").info("live event")

        captured = capsys.readouterr()
        assert "live event" in captured.err
        assert "live event" not in captured.out

    def test_handlers_removed_when_block_raises(self, clean_bugdb_logger, tmp_path):
        """Handler cleanup must run even if the fetch pipeline raises
        — tests and chained CLI commands depend on it."""
        log = tmp_path / "fetch.log"
        before = list(clean_bugdb_logger.handlers)

        with (
            pytest.raises(RuntimeError, match="boom"),
            configure_fetch_logging(log, debug=True),
        ):
            raise RuntimeError("boom")

        after = list(clean_bugdb_logger.handlers)
        assert after == before

    def test_nested_use_does_not_leak(self, clean_bugdb_logger, tmp_path):
        """Two sequential fetch runs in the same process must each
        leave the logger in a clean state — otherwise `bugdb build`
        would attach a handler during fetch and leave it dangling
        for the site build stage."""
        log1 = tmp_path / "a.log"
        log2 = tmp_path / "b.log"

        with configure_fetch_logging(log1, debug=False):
            logging.getLogger("bugdb").info("first run")
        with configure_fetch_logging(log2, debug=False):
            logging.getLogger("bugdb").info("second run")

        assert "first run" in log1.read_text()
        assert "first run" not in log2.read_text()
        assert "second run" in log2.read_text()
        assert "second run" not in log1.read_text()


# ---------------------------------------------------------------------------
# format_fetch_summary
# ---------------------------------------------------------------------------


class TestFormatFetchSummary:
    """Pure-function rendering tests. No I/O, no logger."""

    def test_header_and_totals_present(self):
        report = _make_report()
        out = format_fetch_summary(report)
        assert "Fetch Summary" in out
        assert "Products fetched:    2" in out
        assert "Total versions:      5" in out
        assert "Known issues:        42" in out
        assert "Addressed issues:    17" in out
        assert "Failed fetches:      0" in out

    def test_large_counts_are_comma_formatted(self):
        """1843 → '1,843' — readable at a glance in the log file."""
        report = _make_report(known=1843, addressed=3201)
        out = format_fetch_summary(report)
        assert "Known issues:        1,843" in out
        assert "Addressed issues:    3,201" in out

    def test_per_product_breakdown_rows(self):
        report = _make_report()
        out = format_fetch_summary(report)
        assert "Per-product breakdown:" in out
        assert "PAN-OS" in out
        assert "GlobalProtect" in out
        # Row format: versions, known, addressed, failed
        assert "3 versions" in out
        assert "30 known" in out
        assert "15 addressed" in out
        assert "0 failed" in out

    def test_failed_fetches_section_omitted_when_empty(self):
        report = _make_report(failed=[])
        out = format_fetch_summary(report)
        assert "Failed fetches:      0" in out  # in the totals block
        # The detail section is NOT present when there's nothing to list
        assert "Failed fetches:\n" not in out

    def test_failed_fetches_section_lists_each_entry(self):
        report = _make_report(
            failed=[
                FailedFetchEntry(
                    url="https://docs.example.com/a",
                    error="Timeout after 30000ms",
                    product="panos",
                    version="11.2.3",
                    issue_type="known",
                ),
                FailedFetchEntry(
                    url="https://docs.example.com/b",
                    error="HTTP 500 Internal Server Error",
                    product="adem",
                    version=None,
                    issue_type="known",
                ),
            ],
        )
        out = format_fetch_summary(report)
        assert "! panos" in out
        assert "11.2.3" in out
        assert "https://docs.example.com/a" in out
        assert "Timeout after 30000ms" in out
        assert "! adem" in out
        assert "https://docs.example.com/b" in out
        assert "HTTP 500 Internal Server Error" in out

    def test_empty_product_stats_still_renders_header(self):
        """An edge-case fetch with zero products still produces a
        coherent summary — no crash, no malformed output."""
        report = FetchReport(
            bugdb_file="assets/bugdb.json",
            total_products=0,
            total_versions=0,
            total_known_issues=0,
            total_addressed_issues=0,
            product_stats=[],
            failed_fetches=[],
        )
        out = format_fetch_summary(report)
        assert "Fetch Summary" in out
        assert "Products fetched:    0" in out
        # No per-product section when product_stats is empty.
        assert "Per-product breakdown:" not in out

    def test_output_is_newline_joined_not_crlf(self):
        """Lines are joined with ``\\n`` so a caller can ``splitlines()``
        reliably and feed them into ``logger.info`` one at a time."""
        report = _make_report()
        out = format_fetch_summary(report)
        assert "\r\n" not in out
        assert out.count("\n") > 5
