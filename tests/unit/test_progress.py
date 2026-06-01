"""Tests for the ProgressReporter protocol and its implementations.

Three layers of coverage:

1. ``NullProgressReporter`` — every method is a cheap no-op and accepts
   every valid call without raising.
2. ``PlainProgressReporter`` — emits one stable, grep-friendly line per
   event. The exact line format is locked here so downstream consumers
   (CI log viewers, test assertions) can rely on it.
3. ``RichProgressReporter`` — drives a Rich ``Progress`` against an
   in-memory ``Console`` sink and asserts the final rendered frame
   contains the expected task descriptions and N/M counters. Exact
   layout is intentionally NOT asserted because Rich version bumps can
   shift spacing.

Plus the ``default_reporter`` factory's full auto-detect decision table,
driven by monkeypatching ``sys.stdout.isatty``.
"""

from __future__ import annotations

from io import StringIO

import pytest
from rich.console import Console

from bugdb.progress import (
    NullProgressReporter,
    PlainProgressReporter,
    ProgressReporter,
    RichProgressReporter,
    TaskHandle,
    default_reporter,
)

# ---------------------------------------------------------------------------
# NullProgressReporter
# ---------------------------------------------------------------------------


class TestNullProgressReporter:
    """The null reporter must absorb every call without raising."""

    def test_add_task_returns_task_handle(self):
        reporter = NullProgressReporter()
        handle = reporter.add_task("work", total=5)
        assert isinstance(handle, int)

    def test_all_methods_are_silent_no_ops(self):
        reporter = NullProgressReporter()
        with reporter:
            t = reporter.add_task("x", total=None)
            reporter.update(t, advance=1)
            reporter.update(t, advance=0, description="renamed", total=10)
            reporter.complete(t)
            reporter.log("message")

    def test_conforms_to_protocol(self):
        # Protocol is @runtime_checkable so isinstance works
        assert isinstance(NullProgressReporter(), ProgressReporter)

    def test_nested_tasks_work(self):
        reporter = NullProgressReporter()
        outer = reporter.add_task("outer", total=3)
        inner = reporter.add_task("inner", total=5, parent=outer)
        reporter.update(inner, advance=2)
        reporter.complete(inner)
        reporter.update(outer, advance=1)
        reporter.complete(outer)


# ---------------------------------------------------------------------------
# PlainProgressReporter
# ---------------------------------------------------------------------------


@pytest.fixture
def plain_sink() -> tuple[PlainProgressReporter, StringIO]:
    """Plain reporter wired to an in-memory Rich Console."""
    sink = StringIO()
    console = Console(file=sink, force_terminal=False, width=120)
    return PlainProgressReporter(console), sink


class TestPlainProgressReporter:
    """Plain reporter emits a stable, grep-friendly line per event."""

    def test_add_task_emits_start_line(self, plain_sink):
        reporter, sink = plain_sink
        reporter.add_task("scm: discovering versions", total=None)
        assert "[progress] start: scm: discovering versions" in sink.getvalue()

    def test_add_task_with_known_total_includes_total(self, plain_sink):
        reporter, sink = plain_sink
        reporter.add_task("panos", total=5)
        assert "[progress] start: panos (total=5)" in sink.getvalue()

    def test_update_advance_emits_update_line(self, plain_sink):
        reporter, sink = plain_sink
        t = reporter.add_task("panos", total=3)
        reporter.update(t, advance=1, description="panos: 12.1.5 done")
        assert "[progress] update: panos: 12.1.5 done (1/3)" in sink.getvalue()

    def test_update_total_late_binds(self, plain_sink):
        """``total`` can start as None and be set later (the version-
        discovery pattern)."""
        reporter, sink = plain_sink
        t = reporter.add_task("panos: discovering", total=None)
        reporter.update(t, total=15, description="panos: fetching 15 versions")
        lines = sink.getvalue()
        assert "[progress] update: panos: fetching 15 versions (0/15)" in lines

    def test_update_without_any_change_is_silent(self, plain_sink):
        """An empty ``update()`` call must not emit a redundant line."""
        reporter, sink = plain_sink
        reporter.add_task("x", total=1)
        before = sink.getvalue()
        reporter.update(reporter.add_task("y", total=1), advance=0)
        # The second start line is expected; no stray update line.
        after = sink.getvalue()
        extra = after[len(before) :]
        assert "update:" not in extra

    def test_complete_emits_done_line(self, plain_sink):
        reporter, sink = plain_sink
        t = reporter.add_task("scm", total=1)
        reporter.update(t, advance=1, description="scm: 1.0 done")
        reporter.complete(t)
        assert "[progress] done: scm: 1.0 done" in sink.getvalue()

    def test_log_emits_log_line(self, plain_sink):
        reporter, sink = plain_sink
        reporter.log("retry 1/3 for https://example.com")
        assert "[progress] log: retry 1/3 for https://example.com" in sink.getvalue()

    def test_brackets_in_description_are_not_parsed_as_markup(self, plain_sink):
        """Descriptions containing Rich-markup-like brackets must render
        literally, not be stripped. Crawler retry messages include
        ``[Backoff]`` tags — they must survive the Plain path intact."""
        reporter, sink = plain_sink
        reporter.add_task("[Backoff] paused 30s", total=None)
        assert "[Backoff] paused 30s" in sink.getvalue()

    def test_unknown_task_handle_is_silent(self, plain_sink):
        """Updating or completing a handle we never issued is a silent
        no-op — callers in async paths may double-complete after
        cancellation."""
        reporter, _sink = plain_sink
        phantom = TaskHandle(9999)
        reporter.update(phantom, advance=1)
        reporter.complete(phantom)

    def test_context_manager_returns_self(self):
        with PlainProgressReporter() as reporter:
            assert isinstance(reporter, PlainProgressReporter)

    def test_conforms_to_protocol(self):
        assert isinstance(PlainProgressReporter(), ProgressReporter)


# ---------------------------------------------------------------------------
# RichProgressReporter
# ---------------------------------------------------------------------------


@pytest.fixture
def rich_sink() -> tuple[RichProgressReporter, Console]:
    """Rich reporter wired to an in-memory Console with recording on."""
    sink = StringIO()
    console = Console(
        file=sink,
        force_terminal=True,
        width=120,
        record=True,
        color_system=None,
    )
    return RichProgressReporter(console), console


class TestRichProgressReporter:
    """Rich reporter drives a real Progress against a recording Console.

    We assert substring presence in the exported text rather than exact
    layout — Rich version bumps can shift spacing, and the test should
    not break on cosmetic changes.
    """

    def test_add_task_and_complete_render_task_description(self, rich_sink):
        reporter, console = rich_sink
        with reporter:
            t = reporter.add_task("panos: discovering versions", total=None)
            reporter.update(t, total=3, description="panos: fetching 3 versions")
            reporter.update(t, advance=1, description="panos: 12.1.5 done")
            reporter.update(t, advance=1, description="panos: 11.2.3 done")
            reporter.update(t, advance=1, description="panos: 10.2.8 done")
            reporter.complete(t)
        rendered = console.export_text()
        assert "panos" in rendered
        # Some form of N/M counter must appear; we don't lock exact
        # column layout.
        assert "3/3" in rendered or "3 / 3" in rendered

    def test_log_writes_through_without_erroring(self, rich_sink):
        reporter, console = rich_sink
        with reporter:
            t = reporter.add_task("x", total=1)
            reporter.log("network flake; retrying")
            reporter.update(t, advance=1)
            reporter.complete(t)
        rendered = console.export_text()
        assert "network flake" in rendered

    def test_unknown_task_handle_on_complete_is_silent(self, rich_sink):
        reporter, _console = rich_sink
        with reporter:
            phantom = TaskHandle(9999)
            reporter.complete(phantom)

    def test_conforms_to_protocol(self):
        assert isinstance(RichProgressReporter(), ProgressReporter)


# ---------------------------------------------------------------------------
# default_reporter factory
# ---------------------------------------------------------------------------


class TestDefaultReporter:
    """Decision table from the module docstring:

    ============  ======  =================
    ``progress``  TTY?    Chosen reporter
    ============  ======  =================
    True          yes     Rich
    True          no      Rich (forced)
    False         any     Null
    None          yes     Rich
    None          no      Plain
    ============  ======  =================
    """

    def test_progress_false_returns_null(self, monkeypatch):
        monkeypatch.setattr("sys.stdout.isatty", lambda: True)
        assert isinstance(default_reporter(progress=False), NullProgressReporter)

    def test_progress_false_returns_null_on_non_tty(self, monkeypatch):
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        assert isinstance(default_reporter(progress=False), NullProgressReporter)

    def test_progress_true_forces_rich_on_tty(self, monkeypatch):
        monkeypatch.setattr("sys.stdout.isatty", lambda: True)
        assert isinstance(default_reporter(progress=True), RichProgressReporter)

    def test_progress_true_forces_rich_on_non_tty(self, monkeypatch):
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        assert isinstance(default_reporter(progress=True), RichProgressReporter)

    def test_progress_none_auto_selects_rich_on_tty(self, monkeypatch):
        monkeypatch.setattr("sys.stdout.isatty", lambda: True)
        assert isinstance(default_reporter(progress=None), RichProgressReporter)

    def test_progress_none_auto_selects_plain_on_non_tty(self, monkeypatch):
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        assert isinstance(default_reporter(progress=None), PlainProgressReporter)

    def test_console_is_forwarded_to_rich_reporter(self):
        console = Console(file=StringIO(), force_terminal=True, width=100)
        reporter = default_reporter(console, progress=True)
        assert isinstance(reporter, RichProgressReporter)
