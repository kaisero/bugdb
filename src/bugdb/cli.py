"""CLI commands for BugDB."""

import json
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from bugdb import __version__
from bugdb.models import BugDatabase
from bugdb.sample_data import generate_sample_data
from bugdb.site_builder import build_site

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
def generate_sample(
    output: Annotated[
        Path,
        typer.Option(
            "--output",
            "-o",
            help="Output JSON file path.",
        ),
    ] = Path("assets/data.json"),
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help="Overwrite existing file.",
        ),
    ] = False,
) -> None:
    """Generate sample bug database JSON file."""
    # Check if file exists
    if output.exists() and not force:
        console.print(f"[red]Error:[/red] File {output} already exists. Use --force to overwrite.")
        raise typer.Exit(1)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task("Generating sample data...", total=None)

        # Generate sample data
        database = generate_sample_data()

        # Create output directory if needed
        output.parent.mkdir(parents=True, exist_ok=True)

        # Write JSON file
        with open(output, "w", encoding="utf-8") as f:
            json.dump(
                database.model_dump(mode="json", exclude_none=True),
                f,
                indent=2,
                default=str,
            )

    # Count issues
    total_known = sum(len(v.known_issues) for p in database.products for v in p.versions)
    total_addressed = sum(len(v.addressed_issues) for p in database.products for v in p.versions)

    console.print(
        Panel(
            f"[green]✓[/green] Generated sample data:\n"
            f"  • Products: {len(database.products)}\n"
            f"  • Known issues: {total_known}\n"
            f"  • Addressed issues: {total_addressed}\n"
            f"  • Output: {output}",
            title="Sample Data Generated",
            border_style="green",
        )
    )


@app.command()
def build_site_cmd(
    data: Annotated[
        Path,
        typer.Option(
            "--data",
            "-d",
            help="Input JSON data file.",
        ),
    ] = Path("assets/data.json"),
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
    # Check if data file exists
    if not data.exists():
        console.print(f"[red]Error:[/red] Data file {data} not found.")
        console.print("[dim]Hint: Run 'bugdb generate-sample' to create sample data.[/dim]")
        raise typer.Exit(1)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task("Building static site...", total=None)

        try:
            build_site(data, output)
        except ValidationError as e:
            progress.stop()
            console.print(f"[red]Error:[/red] Invalid data file: {e}")
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
    data_file: Annotated[
        Path,
        typer.Argument(help="JSON data file to validate."),
    ],
) -> None:
    """Validate a bug database JSON file against the schema."""
    if not data_file.exists():
        console.print(f"[red]Error:[/red] File {data_file} not found.")
        raise typer.Exit(1)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task("Validating schema...", total=None)

        try:
            with open(data_file, encoding="utf-8") as f:
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
            help="Output JSON file path.",
        ),
    ] = Path("assets/data.json"),
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
            help="Run browser in headless mode.",
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
) -> None:
    """Fetch bug data from Palo Alto Networks release notes website."""
    from datetime import UTC, datetime

    from bugdb.crawlers import (
        PRODUCT_WRAPPERS,
        FailedFetch,
        get_existing_versions,
        merge_databases,
    )
    from bugdb.models import (
        BugDatabase,
        FailedFetchEntry,
        FetchReport,
        Metadata,
        ProductStats,
    )

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

        # Use data_file from report unless --output was explicitly set
        data_path = Path(prev_report.data_file)
        if output == Path("assets/data.json") and data_path != Path("assets/data.json"):
            output = data_path

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
                f"Supported: {', '.join(supported_products.keys())}"
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
    console.print("[dim]This may take a while as we need to load multiple pages.[/dim]\n")

    all_failed_fetches: list[FailedFetch] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Launching browser and crawling pages...", total=None)

        try:
            all_products = []

            for prod_name in products_to_fetch:
                progress.update(task, description=f"Fetching {prod_name}...")
                crawler_func = supported_products[prod_name]

                # Get skip_versions for this product (if in incremental mode)
                skip_versions = existing_versions.get(prod_name, set())
                if skip_versions:
                    progress.update(
                        task,
                        description=(
                            f"Fetching {prod_name} "
                            f"(skipping {len(skip_versions)} existing versions)..."
                        ),
                    )

                result = crawler_func(
                    major_versions,
                    headless=headless,
                    debug=debug,
                    skip_versions=skip_versions,
                )
                all_products.extend(result.database.products)
                all_failed_fetches.extend(result.failed_fetches)

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
                progress.update(task, description="Merging with existing data...")
                database = merge_databases(existing_database, database)

            progress.update(task, description="Writing JSON file...")

            # Create output directory if needed
            output.parent.mkdir(parents=True, exist_ok=True)

            # Write JSON file
            with open(output, "w", encoding="utf-8") as f:
                json.dump(
                    database.model_dump(mode="json", exclude_none=True),
                    f,
                    indent=2,
                    default=str,
                )

        except Exception as e:
            progress.stop()
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(1) from e

    # Count issues
    total_versions = sum(len(p.versions) for p in database.products)
    total_known = sum(len(v.known_issues) for p in database.products for v in p.versions)
    total_addressed = sum(len(v.addressed_issues) for p in database.products for v in p.versions)

    # Write report if requested
    report_path = None
    if report:
        product_stats = []
        for p in database.products:
            failed_for_product = [f for f in all_failed_fetches if f.product == p.id]
            product_stats.append(
                ProductStats(
                    product_id=p.id,
                    product_name=p.name,
                    versions_fetched=len(p.versions),
                    known_issues_count=sum(len(v.known_issues) for v in p.versions),
                    addressed_issues_count=sum(len(v.addressed_issues) for v in p.versions),
                    failed_fetch_count=len(failed_for_product),
                )
            )

        fetch_report = FetchReport(
            generated_at=datetime.now(UTC),
            data_file=str(output),
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

        report_path = output.with_suffix("").with_suffix(".report.json")
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(
                fetch_report.model_dump(mode="json"),
                f,
                indent=2,
                default=str,
            )

    # Build product list for display
    product_names = ", ".join(p.name for p in database.products)

    # Determine title based on mode
    if retry_mode:
        title = "Retry Fetch Complete"
        mode_info = f"  • Products retried: {', '.join(products_to_fetch)}\n"
    elif existing_database is not None:
        title = "Incremental Fetch Complete"
        new_versions_count = total_versions - sum(len(v) for v in existing_versions.values())
        mode_info = f"  • New versions added: {new_versions_count}\n"
    else:
        title = "Fetch Complete"
        mode_info = ""

    report_info = f"  • Report: {report_path}\n" if report_path else ""

    console.print(
        Panel(
            f"[green]✓[/green] Fetched release notes:\n"
            f"  • Products: {product_names}\n"
            f"  • Total versions: {total_versions}\n"
            f"{mode_info}"
            f"  • Known issues: {total_known}\n"
            f"  • Addressed issues: {total_addressed}\n"
            f"  • Output: {output}\n"
            f"{report_info}".rstrip("\n"),
            title=title,
            border_style="green",
        )
    )

    # Display failed fetches report if any
    if all_failed_fetches:
        console.print()
        failed_summary = "\n".join(
            f"  • {f.product}"
            + (f" {f.version}" if f.version else "")
            + f" ({f.issue_type}): {f.error[:80]}..."
            if len(f.error) > 80
            else f"  • {f.product}"
            + (f" {f.version}" if f.version else "")
            + f" ({f.issue_type}): {f.error}"
            for f in all_failed_fetches
        )
        console.print(
            Panel(
                f"[yellow]⚠[/yellow] Failed to fetch {len(all_failed_fetches)} page(s) "
                f"after retries:\n{failed_summary}",
                title="Failed Fetches",
                border_style="yellow",
            )
        )


@app.command()
def generate_release_notes(
    output: Annotated[
        Path,
        typer.Option(
            "--output",
            "-o",
            help="Output JSON file path.",
        ),
    ] = Path("src/bugdb/templates/assets/release-notes.json"),
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


if __name__ == "__main__":
    app()
