"""CLI commands for BugDB."""

import json
import logging
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from bugdb import __version__
from bugdb.fetch_logging import configure_fetch_logging, format_fetch_summary
from bugdb.models import BugDatabase, FetchReport
from bugdb.progress import default_reporter
from bugdb.site_builder import build_site

_fetch_logger = logging.getLogger("bugdb.fetch")


def _build_fetch_report(
    database: BugDatabase,
    output: Path,
    all_failed_fetches: list,
) -> FetchReport:
    """Aggregate a ``FetchReport`` from the in-memory database and
    the collected failed-fetch list.

    Shared between the streaming summary emitted to the log file and
    the optional ``--report`` JSON sidecar so both reflect the same
    numbers. Cheap — pure Pydantic model construction.
    """
    from datetime import UTC, datetime

    from bugdb.models import FailedFetchEntry, ProductStats

    total_versions = sum(len(p.versions) for p in database.products)
    total_known = sum(len(v.known_issues) for p in database.products for v in p.versions)
    total_addressed = sum(len(v.addressed_issues) for p in database.products for v in p.versions)

    product_stats = []
    for p in database.products:
        failed_for_product = [f for f in all_failed_fetches if f.product == p.id]
        product_stats.append(
            ProductStats(
                product_id=p.id,
                product_name=p.name,
                versions_fetched=len(p.versions),
                versions=[v.version for v in p.versions],
                known_issues_count=sum(len(v.known_issues) for v in p.versions),
                addressed_issues_count=sum(len(v.addressed_issues) for v in p.versions),
                failed_fetch_count=len(failed_for_product),
            )
        )

    return FetchReport(
        generated_at=datetime.now(UTC),
        bugdb_file=str(output),
        total_products=len(database.products),
        total_versions=total_versions,
        total_known_issues=total_known,
        total_addressed_issues=total_addressed,
        product_stats=product_stats,
        failed_fetches=[
            FailedFetchEntry(
                url=f.url,
                error=f.error,
                product=f.product,
                version=f.version,
                issue_type=f.issue_type,
            )
            for f in all_failed_fetches
        ],
    )


app = typer.Typer(
    name="bugdb",
    help="BugDB - Palo Alto Networks Bug Database Viewer",
    add_completion=False,
)
console = Console()


def version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        console.print(f"BugDB version {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            "-v",
            help="Show version and exit.",
            callback=version_callback,
            is_eager=True,
        ),
    ] = None,
) -> None:
    """BugDB - Palo Alto Networks Bug Database Viewer."""
    pass


@app.command()
def build_site_cmd(
    bugdb: Annotated[
        Path,
        typer.Option(
            "--bugdb",
            "-b",
            help="Path to the bug database JSON file.",
        ),
    ] = Path("assets/bugdb.json"),
    release_notes: Annotated[
        Path | None,
        typer.Option(
            "--release-notes",
            "-r",
            help=(
                "Optional path to a release-notes.json file produced by "
                "`bugdb generate-release-notes`. Defaults to "
                "`<bugdb_file_dir>/release-notes.json` if that file exists."
            ),
        ),
    ] = None,
    output: Annotated[
        Path,
        typer.Option(
            "--output",
            "-o",
            help="Output directory for static site.",
        ),
    ] = Path("dist"),
) -> None:
    """Build static HTML site from bug database."""
    if not bugdb.exists():
        console.print(f"[red]Error:[/red] Bug database file {bugdb} not found.")
        console.print(
            "[dim]Hint: Run 'bugdb fetch' or 'bugdb build' to populate "
            "the bug database first.[/dim]"
        )
        raise typer.Exit(1)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task("Building static site...", total=None)

        try:
            build_site(bugdb, output, release_notes_file=release_notes)
        except ValidationError as e:
            progress.stop()
            console.print(f"[red]Error:[/red] Invalid bug database file: {e}")
            raise typer.Exit(1) from e
        except Exception as e:
            progress.stop()
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(1) from e

    console.print(
        Panel(
            f"[green]✓[/green] Static site built successfully!\n"
            f"  • Output: {output}/index.html\n\n"
            f"[dim]Open in browser:[/dim]\n"
            f"  open {output}/index.html",
            title="Site Built",
            border_style="green",
        )
    )


@app.command()
def validate(
    bugdb_file: Annotated[
        Path,
        typer.Argument(help="Bug database JSON file to validate."),
    ],
) -> None:
    """Validate a bug database JSON file against the schema."""
    if not bugdb_file.exists():
        console.print(f"[red]Error:[/red] File {bugdb_file} not found.")
        raise typer.Exit(1)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task("Validating schema...", total=None)

        try:
            with open(bugdb_file, encoding="utf-8") as f:
                data = json.load(f)

            database = BugDatabase.model_validate(data)

        except json.JSONDecodeError as e:
            progress.stop()
            console.print(f"[red]Error:[/red] Invalid JSON: {e}")
            raise typer.Exit(1) from e
        except ValidationError as e:
            progress.stop()
            console.print("[red]Error:[/red] Schema validation failed:")
            for error in e.errors():
                loc = " -> ".join(str(x) for x in error["loc"])
                console.print(f"  • {loc}: {error['msg']}")
            raise typer.Exit(1) from e

    # Count statistics
    total_products = len(database.products)
    total_versions = sum(len(p.versions) for p in database.products)
    total_known = sum(len(v.known_issues) for p in database.products for v in p.versions)
    total_addressed = sum(len(v.addressed_issues) for p in database.products for v in p.versions)

    console.print(
        Panel(
            f"[green]✓[/green] Valid bug database!\n"
            f"  • Products: {total_products}\n"
            f"  • Versions: {total_versions}\n"
            f"  • Known issues: {total_known}\n"
            f"  • Addressed issues: {total_addressed}",
            title="Validation Passed",
            border_style="green",
        )
    )


@app.command()
def fetch(
    product: Annotated[
        str | None,
        typer.Argument(
            help="Product to fetch (e.g., 'globalprotect'). If not specified, fetches all products."
        ),
    ] = None,
    version: Annotated[
        str,
        typer.Option(
            "--version",
            "-v",
            help=(
                "Major version(s) to fetch. Use 'all' for all versions, "
                "or comma-separated list (e.g., '6-2,6-1')."
            ),
        ),
    ] = "all",
    output: Annotated[
        Path,
        typer.Option(
            "--output",
            "-o",
            help="Output JSON file path for the bug database.",
        ),
    ] = Path("assets/bugdb.json"),
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help="Overwrite existing file.",
        ),
    ] = False,
    incremental: Annotated[
        bool,
        typer.Option(
            "--incremental",
            "-i",
            help="Only fetch versions not already in the output file. Requires existing data file.",
        ),
    ] = False,
    headless: Annotated[
        bool,
        typer.Option(
            "--headless/--no-headless",
            help="Run browser in headless mode (legacy --use-browser path only).",
        ),
    ] = True,
    debug: Annotated[
        bool,
        typer.Option(
            "--debug",
            "-d",
            help="Enable debug logging for detailed crawler output.",
        ),
    ] = False,
    report: Annotated[
        bool,
        typer.Option(
            "--report",
            "-r",
            help="Write a JSON report file alongside the data output.",
        ),
    ] = False,
    retry: Annotated[
        Path | None,
        typer.Option(
            "--retry",
            help="Path to a previously generated report JSON. Re-fetches only failed products.",
        ),
    ] = None,
    refresh_discovery: Annotated[
        bool,
        typer.Option(
            "--refresh-discovery",
            "-R",
            help=(
                "Bypass the persistent discovery cache at .cache/bugdb/discovery.json. "
                "Forces every crawler to re-probe URL patterns and re-discover "
                "version lists from upstream. Useful after a docs reorganisation "
                "or when debugging a crawl."
            ),
        ),
    ] = False,
    progress: Annotated[
        bool | None,
        typer.Option(
            "--progress/--no-progress",
            help=(
                "Show live progress bars and per-version updates. Default is "
                "auto-detect: rich live bars on a TTY, streaming plain lines "
                "when piped, suppressed entirely with --no-progress."
            ),
        ),
    ] = None,
    log_file: Annotated[
        str | None,
        typer.Option(
            "--log-file",
            "-l",
            help=(
                "Write a streaming fetch log with per-product events and a "
                "summary block at the end. Pass a path (-l fetch.log), or "
                "pass '-l auto' to default to <output>.log next to the bug "
                "database. Omit the flag to disable file logging entirely."
            ),
        ),
    ] = None,
    manifest: Annotated[
        Path | None,
        typer.Option(
            "--manifest",
            help="Path to the fetch manifest JSON (default: <output>.manifest.json).",
        ),
    ] = None,
    no_manifest: Annotated[
        bool,
        typer.Option(
            "--no-manifest",
            help="Disable manifest read/write (forces a full fetch for every URL).",
        ),
    ] = False,
    use_browser: Annotated[
        bool,
        typer.Option(
            "--use-browser",
            help="Use the legacy Playwright path instead of httpx + FluidTopics.",
        ),
    ] = False,
) -> None:
    """Fetch bug data from Palo Alto Networks release notes website."""
    import asyncio

    from datetime import UTC, datetime

    import httpx

    from bugdb.crawlers import (
        PRODUCT_WRAPPERS,
        FailedFetch,
        get_existing_versions,
        merge_databases,
    )
    from bugdb.discovery_cache import DiscoveryCache
    from bugdb.fetch_manifest import FetchManifest
    from bugdb.models import (
        BugDatabase,
        FetchReport,
        Metadata,
    )
    from bugdb.sitemap import SitemapIndex
    from bugdb.transport.fluidtopics_transport import FluidTopicsTransport
    from bugdb.transport.httpx_transport import HttpxDocsTransport

    # Resolve the --log-file flag. ``None`` disables file logging.
    # The literal sentinel ``"auto"`` means "next to the bug
    # database at <output>.log", mirroring ``--report``'s
    # ``<output>.report.json`` naming.
    resolved_log_file: Path | None
    if log_file is None:
        resolved_log_file = None
    elif log_file == "auto":
        resolved_log_file = output.with_suffix(".log")
    else:
        resolved_log_file = Path(log_file)

    # One DiscoveryCache instance shared across every crawler in this run.
    # Loading once keeps warm-run I/O to a single JSON read + single write.
    discovery_cache = DiscoveryCache()
    if refresh_discovery:
        console.print(
            "[dim]Refreshing discovery cache (ignoring any existing "
            ".cache/bugdb/discovery.json)...[/dim]"
        )
        discovery_cache.invalidate()

    # Handle incremental mode
    existing_database: BugDatabase | None = None
    existing_versions: dict[str, set[str]] = {}
    retry_mode = retry is not None

    if incremental:
        if not output.exists():
            console.print(
                f"[yellow]Warning:[/yellow] Incremental mode requested but {output} not found. "
                "Fetching all versions."
            )
        else:
            try:
                with open(output, encoding="utf-8") as f:
                    data = json.load(f)
                existing_database = BugDatabase.model_validate(data)
                existing_versions = get_existing_versions(existing_database)
                total_existing = sum(len(v) for v in existing_versions.values())
                console.print(
                    f"[dim]Incremental mode: Found {total_existing} existing versions "
                    f"in {output}[/dim]"
                )
            except (json.JSONDecodeError, ValidationError) as e:
                console.print(f"[red]Error:[/red] Failed to load existing data: {e}")
                raise typer.Exit(1) from e
    elif not retry_mode and output.exists() and not force:
        console.print(
            f"[red]Error:[/red] File {output} already exists. "
            "Use --force to overwrite or --incremental to add new versions."
        )
        raise typer.Exit(1)

    # Supported products are derived from PRODUCT_WRAPPERS, which is the
    # single source of truth in bugdb.crawlers.registry. Drift between this
    # CLI and the registry is prevented by tests/unit/test_registry.py.
    # Per-product dispatch goes through registry.dispatch_async so that
    # every crawler runs inside a SINGLE event loop and the shared httpx
    # Transport stays bound to that loop.
    supported_products = PRODUCT_WRAPPERS

    # Handle retry mode
    if retry_mode:
        if product is not None:
            console.print("[red]Error:[/red] --retry cannot be combined with a product argument.")
            raise typer.Exit(1)
        if incremental:
            console.print("[red]Error:[/red] --retry cannot be combined with --incremental.")
            raise typer.Exit(1)
        if version != "all":
            console.print("[red]Error:[/red] --retry cannot be combined with --version.")
            raise typer.Exit(1)

        if not retry.exists():
            console.print(f"[red]Error:[/red] Report file {retry} not found.")
            raise typer.Exit(1)

        try:
            with open(retry, encoding="utf-8") as f:
                report_data = json.load(f)
            prev_report = FetchReport.model_validate(report_data)
        except (json.JSONDecodeError, ValidationError) as e:
            console.print(f"[red]Error:[/red] Failed to load report: {e}")
            raise typer.Exit(1) from e

        if not prev_report.failed_fetches:
            console.print("[green]No failed fetches in the report. Nothing to retry.[/green]")
            raise typer.Exit(0)

        retry_products = {f.product for f in prev_report.failed_fetches}
        products_to_fetch = [p for p in retry_products if p in supported_products]

        if not products_to_fetch:
            console.print("[yellow]Warning:[/yellow] No retryable products found in the report.")
            raise typer.Exit(1)

        # Use bugdb_file from report unless --output was explicitly set.
        # The sentinel check `output == default` detects whether the user
        # passed --output or accepted the default; if they accepted the
        # default AND the report points somewhere else, follow the report.
        bugdb_path = Path(prev_report.bugdb_file)
        default_output = Path("assets/bugdb.json")
        if output == default_output and bugdb_path != default_output:
            output = bugdb_path

        if output.exists():
            try:
                with open(output, encoding="utf-8") as f:
                    data = json.load(f)
                existing_database = BugDatabase.model_validate(data)
            except (json.JSONDecodeError, ValidationError) as e:
                console.print(f"[red]Error:[/red] Failed to load existing data for retry: {e}")
                raise typer.Exit(1) from e
        else:
            console.print(f"[red]Error:[/red] Data file {output} not found for retry merge.")
            raise typer.Exit(1)

        major_versions = None
        product_display = f"retry: {', '.join(products_to_fetch)}"
        version_display = "all versions"

    # Normal mode: determine which products to fetch
    elif product is None:
        products_to_fetch = list(supported_products.keys())
        product_display = "all products"
    else:
        if product.lower() not in supported_products:
            console.print(
                f"[red]Error:[/red] Unsupported product '{product}'. "
                f"Supported: {', '.join(supported_products)}"
            )
            raise typer.Exit(1)
        products_to_fetch = [product.lower()]
        product_display = product

    # Parse version(s) (not used in retry mode, already set above)
    if not retry_mode:
        if version.lower() == "all":
            major_versions = None  # Will auto-discover
            version_display = "all versions"
        else:
            major_versions = [v.strip() for v in version.split(",")]
            version_display = ", ".join(v.replace("-", ".") for v in major_versions)

    console.print(f"[bold]Fetching {product_display} ({version_display})...[/bold]")

    all_failed_fetches: list[FailedFetch] = []

    # ----- Build shared sitemap + manifest ---------------------------------
    manifest_path = manifest or output.with_suffix(".manifest.json")
    if no_manifest:
        manifest_obj = FetchManifest()
    else:
        manifest_obj = FetchManifest.load(manifest_path)

    sitemap_index: SitemapIndex | None = None
    if not use_browser:
        sitemap_url = "https://docs.paloaltonetworks.com/sitemap.xml"
        console.print(f"[dim]Loading sitemap from {sitemap_url}...[/dim]")
        try:
            with httpx.Client(http2=True, follow_redirects=True, timeout=30.0) as c:
                resp = c.get(sitemap_url)
                resp.raise_for_status()
                sitemap_index = SitemapIndex.from_xml(resp.text)
            n_issue = sum(1 for _ in sitemap_index.issue_urls())
            console.print(f"[dim]Sitemap loaded ({n_issue} issue URLs).[/dim]")
        except Exception as e:
            console.print(
                f"[yellow]Warning:[/yellow] failed to load sitemap "
                f"({e}); falling back to legacy discovery."
            )
            sitemap_index = None

    # Lookup table for human-readable display names — used for the
    # progress bar's initial "discovering versions" label before the
    # crawler itself swaps in its own product_name via
    # _set_task_total(). Falls back to the product id if the lookup
    # misses (e.g. for future products added to the registry but not
    # to the class hierarchy).
    from bugdb.crawlers.registry import PRODUCT_CRAWLERS, dispatch_async

    def _display_name(pid: str) -> str:
        cls = PRODUCT_CRAWLERS.get(pid)
        return getattr(cls, "product_name", pid) if cls else pid

    # --debug streams log lines to stderr which tears Rich's live
    # progress bars. Force the Null reporter when debug is active so
    # the two modes don't fight over the terminal.
    effective_progress = False if debug else progress
    reporter = default_reporter(console, progress=effective_progress)
    with configure_fetch_logging(resolved_log_file, debug=debug):
        _fetch_logger.info("Fetch started: %s (%s)", product_display, version_display)
        _fetch_logger.info(
            "Targeting %d product(s); output=%s",
            len(products_to_fetch),
            output,
        )
        if resolved_log_file is not None:
            console.print(f"[dim]Writing log to {resolved_log_file}[/dim]\n")

        with reporter:
            outer_task = reporter.add_task(
                f"Fetching {len(products_to_fetch)} products",
                total=len(products_to_fetch),
            )

            all_products: list = []

            async def _run_all() -> None:
                """Run every product crawl in ONE event loop.

                Single asyncio.run keeps the shared httpx Transport bound
                to one loop across products — recreating it per product
                would tear down the connection pool between fetches and
                lose half the value of httpx+http2 reuse.
                """
                # Shared transports — one per host. Built INSIDE the
                # event loop that will use them so their httpx.AsyncClient
                # and asyncio primitives belong to that loop.
                docs_transport = (
                    None if use_browser else HttpxDocsTransport(concurrency=15)
                )
                fluidtopics = (
                    None if use_browser else FluidTopicsTransport(concurrency=10)
                )
                try:
                    for prod_name in products_to_fetch:
                        display_name = _display_name(prod_name)
                        skip_versions = existing_versions.get(prod_name, set())
                        if skip_versions:
                            sub_description = (
                                f"{display_name}: discovering "
                                f"(skipping {len(skip_versions)} existing versions)"
                            )
                        else:
                            sub_description = f"{display_name}: discovering versions"
                        sub_task = reporter.add_task(
                            sub_description,
                            total=None,
                            parent=outer_task,
                        )

                        kwargs: dict = dict(
                            headless=headless,
                            debug=debug,
                            skip_versions=skip_versions,
                            discovery_cache=discovery_cache,
                            reporter=reporter,
                            task=sub_task,
                        )
                        if not use_browser:
                            if prod_name == "cortex-xdr":
                                kwargs["fluidtopics"] = fluidtopics
                            else:
                                kwargs["transport"] = docs_transport
                            kwargs["sitemap"] = sitemap_index
                            kwargs["manifest"] = manifest_obj

                        try:
                            result = await dispatch_async(
                                prod_name, major_versions, **kwargs
                            )
                        except Exception as e:
                            reporter.complete(sub_task)
                            _fetch_logger.error(
                                "Error fetching %s: %s", prod_name, e
                            )
                            console.print(
                                f"[red]Error fetching {prod_name}:[/red] {e}"
                            )
                            raise typer.Exit(1) from e
                        reporter.complete(sub_task)
                        reporter.update(outer_task, advance=1)
                        all_products.extend(result.database.products)
                        all_failed_fetches.extend(result.failed_fetches)
                finally:
                    if docs_transport is not None:
                        await docs_transport.aclose()
                    if fluidtopics is not None:
                        await fluidtopics.aclose()

            asyncio.run(_run_all())

            # Flush the discovery cache after all crawlers have populated it,
            # so the next run can start warm. A cache-write failure must
            # never block a successful crawl — log and continue.
            try:
                discovery_cache.save()
            except OSError as cache_err:
                _fetch_logger.warning("Could not persist discovery cache: %s", cache_err)
                console.print(
                    f"[yellow]Warning:[/yellow] could not persist discovery cache "
                    f"({cache_err}); next run will start cold."
                )

            # Persist sitemap lastmod into the manifest for URLs we still keep.
            if not no_manifest and sitemap_index is not None:
                for entry in sitemap_index.issue_urls():
                    manifest_obj.record(entry.url, entry.lastmod)
                manifest_obj.save(manifest_path)

            # Create combined database
            database = BugDatabase(
                metadata=Metadata(
                    generated_at=datetime.now(UTC),
                    version="1.0.0",
                    source="Palo Alto Networks Release Notes",
                ),
                products=all_products,
            )

            # Merge with existing database if in incremental mode
            if existing_database is not None:
                _fetch_logger.info("Merging with existing data...")
                reporter.log("Merging with existing data...")
                try:
                    database = merge_databases(existing_database, database)
                except Exception as e:
                    _fetch_logger.error("Error merging databases: %s", e)
                    console.print(f"[red]Error merging databases:[/red] {e}")
                    raise typer.Exit(1) from e

            _fetch_logger.info("Writing %s", output)
            reporter.log(f"Writing {output}...")

            # Create output directory if needed
            output.parent.mkdir(parents=True, exist_ok=True)

            # Write JSON file — narrow except around the IO write so disk
            # errors report as "Error writing output" rather than a bare
            # "Error" attributable to anything in the pipeline.
            try:
                with open(output, "w", encoding="utf-8") as f:
                    json.dump(
                        database.model_dump(mode="json", exclude_none=True),
                        f,
                        indent=2,
                        default=str,
                    )
            except OSError as e:
                _fetch_logger.error("Error writing %s: %s", output, e)
                console.print(f"[red]Error writing {output}:[/red] {e}")
                raise typer.Exit(1) from e

        # Build the FetchReport from *only the products fetched in this
        # run* (``all_products``), NOT from the post-merge ``database``
        # which includes every pre-existing product from the incremental
        # base. Otherwise an incremental fetch of a single product
        # would report totals for the entire bugdb.json — misleading.
        fetched_database = BugDatabase(
            metadata=Metadata(
                generated_at=datetime.now(UTC),
                version="1.0.0",
                source="Palo Alto Networks Release Notes",
            ),
            products=all_products,
        )
        fetch_report = _build_fetch_report(fetched_database, output, all_failed_fetches)

        # Stream the summary through the fetch logger so it lands in
        # the log file (if any) with consistent timestamps. Lines are
        # self-contained so each one is independently emitted.
        for summary_line in format_fetch_summary(fetch_report).splitlines():
            _fetch_logger.info(summary_line)
        _fetch_logger.info("Fetch finished")

    # Write JSON report sidecar if --report was passed. Orthogonal to
    # --log-file: the text log file streams events, the report JSON
    # is a one-shot machine-readable snapshot.
    report_path = None
    if report:
        report_path = output.with_suffix("").with_suffix(".report.json")
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(
                fetch_report.model_dump(mode="json"),
                f,
                indent=2,
                default=str,
            )

    # Determine title based on mode
    if retry_mode:
        title = "Retry Fetch Complete"
    elif existing_database is not None:
        title = "Incremental Fetch Complete"
    else:
        title = "Fetch Complete"

    # Render the summary from the same FetchReport used for the log
    # file. Both channels see identical data, grouped by product with
    # per-product version lists — the only difference is formatting
    # (Rich panel vs timestamped log lines).
    summary_text = format_fetch_summary(fetch_report)

    # In --debug mode the summary is already streaming to stderr via
    # the logger — printing the Rich panel too would duplicate it.
    if not debug:
        report_info = f"\nReport: {report_path}" if report_path else ""
        log_info = f"\nLog:    {resolved_log_file}" if resolved_log_file else ""
        panel_body = (
            f"[green]✓[/green] Fetched release notes\n\n"
            f"{summary_text}\n\n"
            f"Output: {output}"
            f"{report_info}"
            f"{log_info}"
        )
        console.print(Panel(panel_body, title=title, border_style="green"))


@app.command()
def generate_release_notes(
    output: Annotated[
        Path,
        typer.Option(
            "--output",
            "-o",
            help="Output JSON file path (release notes).",
        ),
    ] = Path("assets/release-notes.json"),
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help="Overwrite existing file.",
        ),
    ] = False,
) -> None:
    """Generate release notes JSON file for the static site."""
    from bugdb.release_notes import get_release_notes

    # Check if file exists
    if output.exists() and not force:
        console.print(f"[red]Error:[/red] File {output} already exists. Use --force to overwrite.")
        raise typer.Exit(1)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task("Generating release notes...", total=None)

        # Get release notes data
        release_notes = get_release_notes()

        # Create output directory if needed
        output.parent.mkdir(parents=True, exist_ok=True)

        # Write JSON file
        with open(output, "w", encoding="utf-8") as f:
            json.dump(
                release_notes.model_dump(mode="json"),
                f,
                indent=2,
            )

    # Count releases and changes
    total_releases = len(release_notes.releases)
    total_changes = sum(len(r.changes) for r in release_notes.releases)

    console.print(
        Panel(
            f"[green]✓[/green] Generated release notes:\n"
            f"  • Releases: {total_releases}\n"
            f"  • Total changes: {total_changes}\n"
            f"  • Output: {output}",
            title="Release Notes Generated",
            border_style="green",
        )
    )


@app.command()
def build(
    output: Annotated[
        Path,
        typer.Option(
            "--output",
            "-o",
            help="Output directory for the static site.",
        ),
    ] = Path("dist"),
    bugdb: Annotated[
        Path,
        typer.Option(
            "--bugdb",
            "-b",
            help=("Bug database JSON file path (fetch writes here, build-site reads from here)."),
        ),
    ] = Path("assets/bugdb.json"),
    release_notes: Annotated[
        Path,
        typer.Option(
            "--release-notes",
            "-r",
            help=(
                "Release notes JSON file path (generate-release-notes writes here, "
                "build-site copies into the output site). Defaults to a sibling of "
                "the --bugdb file in the same directory."
            ),
        ),
    ] = Path("assets/release-notes.json"),
    skip_fetch: Annotated[
        bool,
        typer.Option(
            "--skip-fetch",
            help=(
                "Skip the fetch stage and use the existing bug database. "
                "Useful for iterative frontend work where the data is "
                "already populated."
            ),
        ),
    ] = False,
    incremental: Annotated[
        bool,
        typer.Option(
            "--incremental",
            "-i",
            help="Incremental fetch — only fetch versions not already in the bug database.",
        ),
    ] = False,
    headless: Annotated[
        bool,
        typer.Option(
            "--headless/--no-headless",
            help="Run the crawler browser in headless mode.",
        ),
    ] = True,
    debug: Annotated[
        bool,
        typer.Option(
            "--debug",
            help="Enable debug logging for the crawler.",
        ),
    ] = False,
    refresh_discovery: Annotated[
        bool,
        typer.Option(
            "--refresh-discovery",
            "-R",
            help="Bypass the persistent discovery cache and re-probe upstream URLs.",
        ),
    ] = False,
    progress: Annotated[
        bool | None,
        typer.Option(
            "--progress/--no-progress",
            help=(
                "Show live progress bars and per-version updates during fetch. "
                "Default is auto-detect: rich live bars on a TTY, streaming "
                "plain lines when piped, suppressed entirely with --no-progress."
            ),
        ),
    ] = None,
    log_file: Annotated[
        str | None,
        typer.Option(
            "--log-file",
            "-l",
            help=(
                "Write a streaming fetch log. Pass a path (-l fetch.log), "
                "or pass '-l auto' to default to <bugdb>.log. Omit to "
                "disable. When combined with --skip-fetch, the file is "
                "still created with a 'fetch stage skipped' marker."
            ),
        ),
    ] = None,
) -> None:
    """Fetch bug data, generate release notes, and build the static site.

    The unified one-command workflow for producing a deployable site with
    real data. Runs three stages in sequence:

    \b
    1. `bugdb fetch`               — crawls release notes into BUGDB
                                     (default: assets/bugdb.json)
    2. `bugdb generate-release-notes` — writes release notes JSON to
                                     RELEASE_NOTES (default:
                                     assets/release-notes.json, same
                                     folder as BUGDB)
    3. `bugdb build-site-cmd`      — builds the site into OUTPUT,
                                     baking BUGDB as bugdb.json and
                                     copying RELEASE_NOTES as
                                     release-notes.json under the
                                     output assets directory.

    Re-running `bugdb build` on a populated workspace overwrites the
    existing bugdb.json by default (force). Pass `--incremental` to
    fetch only new versions, or `--skip-fetch` to rebuild the site
    from existing data without hitting the network at all.
    """
    # Stage 1: fetch (unless --skip-fetch). Force overwrites existing
    # bugdb.json unless incremental mode is active.
    if skip_fetch:
        if not bugdb.exists():
            console.print(
                f"[red]Error:[/red] --skip-fetch was passed but {bugdb} does not exist. "
                f"Run without --skip-fetch first to populate it."
            )
            raise typer.Exit(1)
        console.print(f"[dim]Skipping fetch — reusing existing {bugdb}[/dim]")

        # Even when fetch is skipped, still write a minimal log file
        # so users running `build --log-file` always get *something*
        # next to their bug database. The log just notes that the
        # fetch stage was skipped so the absence of per-version
        # events is explained rather than mysterious.
        if log_file is not None:
            skip_log_path = bugdb.with_suffix(".log") if log_file == "auto" else Path(log_file)
            with configure_fetch_logging(skip_log_path, debug=debug):
                _fetch_logger.info(
                    "Fetch stage skipped (--skip-fetch). Reusing existing %s",
                    bugdb,
                )
    else:
        console.print(
            Panel(
                "[bold]Stage 1/3:[/bold] Fetching bug data from docs.paloaltonetworks.com",
                border_style="cyan",
            )
        )
        fetch(
            product=None,
            version="all",
            output=bugdb,
            force=not incremental,
            incremental=incremental,
            headless=headless,
            debug=debug,
            report=False,
            retry=None,
            refresh_discovery=refresh_discovery,
            progress=progress,
            log_file=log_file,
        )

    # Stage 2: regenerate release-notes.json. Always force — this is
    # the unified build's canonical output, stale content must lose.
    console.print(
        Panel(
            "[bold]Stage 2/3:[/bold] Generating release notes",
            border_style="cyan",
        )
    )
    generate_release_notes(
        output=release_notes,
        force=True,
    )

    # Stage 3: build the static site from the fetched data + release notes.
    console.print(
        Panel(
            "[bold]Stage 3/3:[/bold] Building static site",
            border_style="cyan",
        )
    )
    build_site_cmd(bugdb=bugdb, release_notes=release_notes, output=output)

    console.print(
        Panel(
            f"[green]✓[/green] Unified build complete!\n"
            f"  • Bugdb: {bugdb}\n"
            f"  • Site:  {output}/index.html\n\n"
            f"[dim]Open in browser:[/dim]\n"
            f"  open {output}/index.html",
            title="Build Finished",
            border_style="green",
        )
    )


if __name__ == "__main__":
    app()
