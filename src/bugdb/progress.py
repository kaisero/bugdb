"""Progress reporting abstraction for long-running CLI operations.

This module exposes a small, framework-agnostic :class:`ProgressReporter`
protocol plus three concrete implementations:

- :class:`RichProgressReporter` — live bars + spinner via the ``rich`` library,
  used when the process is attached to a TTY.
- :class:`PlainProgressReporter` — one log line per event, used in CI or any
  non-TTY pipe where a redrawing bar would either spam refresh frames or
  collapse to a single stuck line.
- :class:`NullProgressReporter` — silent no-op, used by library callers and
  tests that don't want any output.

The protocol intentionally mirrors a subset of Rich's ``Progress`` API (it
handles strings, ints, and an opaque :data:`TaskHandle`), which keeps the
crawler layer free of any Rich import and lets unrelated commands or even
other projects reuse the same abstraction.

Motivation
----------

``bugdb fetch`` runs for 10-20 minutes on a cold crawl and, before this
module landed, gave the user a single spinner whose label bumped once per
product. For the 5+ minutes it spent inside PAN-OS the user had no signal
at all. This module lets the crawlers emit per-version events back to the
CLI which then decides how to render them based on the environment.

Typical usage
-------------

.. code-block:: python

    from bugdb.progress import default_reporter
    from rich.console import Console

    console = Console()
    reporter = default_reporter(console, progress=None)  # auto-detect TTY
    with reporter:
        outer = reporter.add_task("Fetching products", total=3)
        for name in ("panos", "scm", "adem"):
            sub = reporter.add_task(f"{name}: discovering versions…", parent=outer)
            crawler_func(..., reporter=reporter, task=sub)
            reporter.complete(sub)
            reporter.update(outer, advance=1)
"""

from __future__ import annotations

import sys
from types import TracebackType
from typing import TYPE_CHECKING, NewType, Protocol, runtime_checkable

if TYPE_CHECKING:
    from rich.console import Console

# Opaque task identifier returned by :meth:`ProgressReporter.add_task`. Using
# ``NewType`` gives us a distinct static type so mypy catches misuse (mixing
# raw ints with task ids) without adding runtime overhead — at runtime a
# ``TaskHandle`` is just an ``int``.
TaskHandle = NewType("TaskHandle", int)


@runtime_checkable
class ProgressReporter(Protocol):
    """Framework-agnostic protocol for progress reporting.

    Implementations may render live terminal bars, stream log lines, or
    swallow events entirely. Callers should treat returned
    :data:`TaskHandle` values as opaque — they are meaningful only to the
    reporter that issued them.

    Every reporter is also a context manager so ``with reporter:`` gives
    Rich a clean start/stop hook; the plain and null implementations
    return ``self`` and do nothing on exit.
    """

    def add_task(
        self,
        description: str,
        total: int | None = None,
        parent: TaskHandle | None = None,
    ) -> TaskHandle:
        """Register a new task and return its opaque handle.

        ``total`` may be ``None`` if the total work size isn't yet known —
        callers then update it later via :meth:`update` once discovery
        resolves. ``parent`` is purely informational; reporters that don't
        support nesting ignore it.
        """
        ...

    def update(
        self,
        task: TaskHandle,
        *,
        advance: int = 0,
        description: str | None = None,
        total: int | None = None,
    ) -> None:
        """Mutate an existing task's progress counter, label, or total.

        Keyword-only so additional fields (``visible``, ``start``, …) can
        be added later without breaking positional callers.
        """
        ...

    def complete(self, task: TaskHandle) -> None:
        """Mark a task as finished. The reporter may remove it from
        display, leave it at 100%, or emit a final log line depending on
        implementation."""
        ...

    def log(self, message: str) -> None:
        """Print an out-of-band message (retry warning, backoff notice).

        Renders above the bars on Rich, as a plain streaming line on
        Plain, and as a no-op on Null.
        """
        ...

    def __enter__(self) -> ProgressReporter: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None: ...


# ---------------------------------------------------------------------------
# Null reporter
# ---------------------------------------------------------------------------


class NullProgressReporter:
    """A reporter that silently swallows every event.

    Use this from library callers and tests that don't want any output.
    All methods are cheap no-ops so it's safe to pass through hot paths.
    """

    def add_task(
        self,
        description: str,
        total: int | None = None,
        parent: TaskHandle | None = None,
    ) -> TaskHandle:
        return TaskHandle(0)

    def update(
        self,
        task: TaskHandle,
        *,
        advance: int = 0,
        description: str | None = None,
        total: int | None = None,
    ) -> None:
        return None

    def complete(self, task: TaskHandle) -> None:
        return None

    def log(self, message: str) -> None:
        return None

    def __enter__(self) -> NullProgressReporter:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        return None


# ---------------------------------------------------------------------------
# Plain reporter
# ---------------------------------------------------------------------------


class PlainProgressReporter:
    """Streams one log line per event via a Rich ``Console``.

    Chosen automatically when ``sys.stdout.isatty()`` is ``False`` — CI
    systems and piped output need deterministic, grep-friendly lines
    rather than a redrawing bar that either spams refresh frames or
    collapses to a single stuck line.

    The line format is deliberately machine-friendly and stable::

        [progress] start: <description> (total=<N>)
        [progress] update: <description> (<completed>/<total>)
        [progress] done: <description>
        [progress] log: <message>

    Tests lock this format — see ``tests/unit/test_progress.py``.
    """

    def __init__(self, console: Console | None = None) -> None:
        # Lazy-import so library callers that never use Rich don't pay the
        # import cost. In practice Rich is already in the dependency tree,
        # but keeping this lazy matches the protocol's no-Rich-on-crawler
        # invariant.
        from rich.console import Console as RichConsole

        self._console: Console = console if console is not None else RichConsole()
        self._tasks: dict[TaskHandle, _PlainTaskState] = {}
        self._next_id: int = 0

    def add_task(
        self,
        description: str,
        total: int | None = None,
        parent: TaskHandle | None = None,
    ) -> TaskHandle:
        self._next_id += 1
        handle = TaskHandle(self._next_id)
        self._tasks[handle] = _PlainTaskState(
            description=description,
            total=total,
            completed=0,
        )
        total_str = f" (total={total})" if total is not None else ""
        self._console.print(f"[progress] start: {description}{total_str}", markup=False)
        return handle

    def update(
        self,
        task: TaskHandle,
        *,
        advance: int = 0,
        description: str | None = None,
        total: int | None = None,
    ) -> None:
        state = self._tasks.get(task)
        if state is None:
            return
        if total is not None:
            state.total = total
        if description is not None:
            state.description = description
        if advance:
            state.completed += advance
        # Only emit a line when the event actually moves the counter or
        # changes the label — silent no-op on empty updates avoids log
        # spam.
        if advance or description is not None or total is not None:
            total_str = str(state.total) if state.total is not None else "?"
            self._console.print(
                f"[progress] update: {state.description} ({state.completed}/{total_str})",
                markup=False,
            )

    def complete(self, task: TaskHandle) -> None:
        state = self._tasks.pop(task, None)
        if state is None:
            return
        self._console.print(f"[progress] done: {state.description}", markup=False)

    def log(self, message: str) -> None:
        self._console.print(f"[progress] log: {message}", markup=False)

    def __enter__(self) -> PlainProgressReporter:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        return None


class _PlainTaskState:
    """Mutable per-task state for :class:`PlainProgressReporter`."""

    __slots__ = ("completed", "description", "total")

    def __init__(self, description: str, total: int | None, completed: int) -> None:
        self.description = description
        self.total = total
        self.completed = completed


# ---------------------------------------------------------------------------
# Rich reporter
# ---------------------------------------------------------------------------


class RichProgressReporter:
    """Live terminal bars + spinner via Rich ``Progress``.

    Uses the column set
    ``[SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn,
    TimeElapsedColumn]`` so users see a spinner, the task description,
    a filled bar, the ``N/M`` counter, and elapsed time.

    ``log()`` delegates to the underlying ``Console.log`` which prints
    above the bars without breaking the redraw loop, so retry warnings
    and backoff notices stay visible without tearing the UI.
    """

    def __init__(self, console: Console | None = None) -> None:
        # Lazy-import so importing this module doesn't drag Rich in until
        # someone actually constructs a Rich reporter.
        from rich.console import Console as RichConsole
        from rich.progress import (
            BarColumn,
            MofNCompleteColumn,
            Progress,
            SpinnerColumn,
            TextColumn,
            TimeElapsedColumn,
        )

        self._console: Console = console if console is not None else RichConsole()
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=self._console,
            transient=False,
        )

    def add_task(
        self,
        description: str,
        total: int | None = None,
        parent: TaskHandle | None = None,
    ) -> TaskHandle:
        # Rich treats ``total=None`` as an "indeterminate" spinner-only
        # task which is exactly what we want before version discovery
        # resolves.
        task_id = self._progress.add_task(description, total=total)
        return TaskHandle(task_id)

    def update(
        self,
        task: TaskHandle,
        *,
        advance: int = 0,
        description: str | None = None,
        total: int | None = None,
    ) -> None:
        kwargs: dict[str, object] = {}
        if advance:
            kwargs["advance"] = advance
        if description is not None:
            kwargs["description"] = description
        if total is not None:
            kwargs["total"] = total
        if kwargs:
            self._progress.update(int(task), **kwargs)

    def complete(self, task: TaskHandle) -> None:
        # Force the bar to 100% regardless of where it was, leaving the
        # final row visible so users see the history of what completed.
        # When total is None (indeterminate spinner, e.g. an incremental
        # fetch that skipped everything before discovery set a total),
        # set total=0 and completed=0 so Rich stops the spinner and
        # shows a resolved 0/0 state instead of hanging at "0/?".
        task_id = int(task)
        for t in self._progress.tasks:
            if t.id == task_id:
                total = t.total if t.total is not None else 0
                self._progress.update(task_id, total=total, completed=total)
                return

    def log(self, message: str) -> None:
        self._progress.console.log(message)

    def __enter__(self) -> RichProgressReporter:
        self._progress.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self._progress.stop()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def default_reporter(
    console: Console | None = None,
    *,
    progress: bool | None = None,
) -> ProgressReporter:
    """Pick a reporter implementation based on caller intent and TTY state.

    The decision table:

    =============  ======  =================
    ``progress``   TTY?    Chosen reporter
    =============  ======  =================
    ``True``       yes     Rich
    ``True``       no      Rich (forced)
    ``False``      any     Null
    ``None``       yes     Rich
    ``None``       no      Plain
    =============  ======  =================

    Passing ``progress=False`` explicitly disables all output — useful
    for very quiet CI runs or scripts that only want the final summary.
    Passing ``progress=True`` forces Rich even on non-TTY, which is
    rarely what you want but lets tests opt in without monkeypatching
    ``sys.stdout``.

    ``console`` is optional: Rich and Plain reporters will construct a
    default :class:`rich.console.Console` when ``None`` is passed.
    """
    if progress is False:
        return NullProgressReporter()

    is_tty = sys.stdout.isatty()

    if progress is True:
        return RichProgressReporter(console)

    # progress is None → auto-detect
    if is_tty:
        return RichProgressReporter(console)
    return PlainProgressReporter(console)


__all__ = [
    "NullProgressReporter",
    "PlainProgressReporter",
    "ProgressReporter",
    "RichProgressReporter",
    "TaskHandle",
    "default_reporter",
]
