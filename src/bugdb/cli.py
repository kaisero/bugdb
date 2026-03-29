"""CLI commands for BugDB."""

import json
from pathlib import Path
from typing import Annotated, Optional

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from bugdb import __version__
from bugdb.models import BugDatabase
from bugdb.sample_data import generate_sample_data
from bugdb.site_builder import build_site, build_site_from_database

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
        Optional[bool],
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
        console.print(
            f"[red]Error:[/red] File {output} already exists. Use --force to overwrite."
        )
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
                database.model_dump(mode="json"),
                f,
                indent=2,
                default=str,
            )

    # Count issues
    total_known = sum(
        len(v.known_issues)
        for p in database.products
        for v in p.versions
    )
    total_addressed = sum(
        len(v.addressed_issues)
        for p in database.products
        for v in p.versions
    )

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
        console.print(
            "[dim]Hint: Run 'bugdb generate-sample' to create sample data.[/dim]"
        )
        raise typer.Exit(1)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Building static site...", total=None)

        try:
            build_site(data, output)
        except ValidationError as e:
            progress.stop()
            console.print(f"[red]Error:[/red] Invalid data file: {e}")
            raise typer.Exit(1)
        except Exception as e:
            progress.stop()
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(1)

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
            with open(data_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            database = BugDatabase.model_validate(data)

        except json.JSONDecodeError as e:
            progress.stop()
            console.print(f"[red]Error:[/red] Invalid JSON: {e}")
            raise typer.Exit(1)
        except ValidationError as e:
            progress.stop()
            console.print(f"[red]Error:[/red] Schema validation failed:")
            for error in e.errors():
                loc = " -> ".join(str(x) for x in error["loc"])
                console.print(f"  • {loc}: {error['msg']}")
            raise typer.Exit(1)

    # Count statistics
    total_products = len(database.products)
    total_versions = sum(len(p.versions) for p in database.products)
    total_known = sum(
        len(v.known_issues)
        for p in database.products
        for v in p.versions
    )
    total_addressed = sum(
        len(v.addressed_issues)
        for p in database.products
        for v in p.versions
    )

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
        Optional[str],
        typer.Argument(help="Product to fetch (e.g., 'globalprotect'). If not specified, fetches all products."),
    ] = None,
    version: Annotated[
        str,
        typer.Option(
            "--version",
            "-v",
            help="Major version(s) to fetch. Use 'all' for all versions, or comma-separated list (e.g., '6-2,6-1').",
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
) -> None:
    """Fetch bug data from Palo Alto Networks release notes website."""
    from datetime import datetime, timezone

    from bugdb.crawler import (
        FailedFetch,
        crawl_adem,
        crawl_cloud_ngfw_aws,
        crawl_cloud_ngfw_azure,
        crawl_globalprotect,
        crawl_panos,
        crawl_prisma_access,
        crawl_prisma_access_agent,
        crawl_prisma_sdwan,
        crawl_scm,
        crawl_sdwan_plugin,
        get_existing_versions,
        merge_databases,
    )
    from bugdb.models import BugDatabase, Metadata

    # Handle incremental mode
    existing_database: Optional[BugDatabase] = None
    existing_versions: dict[str, set[str]] = {}

    if incremental:
        if not output.exists():
            console.print(
                f"[yellow]Warning:[/yellow] Incremental mode requested but {output} not found. "
                "Fetching all versions."
            )
        else:
            try:
                with open(output, "r", encoding="utf-8") as f:
                    data = json.load(f)
                existing_database = BugDatabase.model_validate(data)
                existing_versions = get_existing_versions(existing_database)
                total_existing = sum(len(v) for v in existing_versions.values())
                console.print(
                    f"[dim]Incremental mode: Found {total_existing} existing versions in {output}[/dim]"
                )
            except (json.JSONDecodeError, ValidationError) as e:
                console.print(f"[red]Error:[/red] Failed to load existing data: {e}")
                raise typer.Exit(1)
    elif output.exists() and not force:
        console.print(
            f"[red]Error:[/red] File {output} already exists. "
            "Use --force to overwrite or --incremental to add new versions."
        )
        raise typer.Exit(1)

    # Define supported products and their crawlers
    supported_products = {
        "adem": crawl_adem,
        "cloud-ngfw-aws": crawl_cloud_ngfw_aws,
        "cloud-ngfw-azure": crawl_cloud_ngfw_azure,
        "globalprotect": crawl_globalprotect,
        "panos": crawl_panos,
        "prisma-access": crawl_prisma_access,
        "prisma-access-agent": crawl_prisma_access_agent,
        "prisma-sdwan": crawl_prisma_sdwan,
        "scm": crawl_scm,
        "sdwan-plugin": crawl_sdwan_plugin,
    }

    # Determine which products to fetch
    if product is None:
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

    # Parse version(s)
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
                        description=f"Fetching {prod_name} (skipping {len(skip_versions)} existing versions)..."
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
                    generated_at=datetime.now(timezone.utc),
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
                    database.model_dump(mode="json"),
                    f,
                    indent=2,
                    default=str,
                )

        except Exception as e:
            progress.stop()
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(1)

    # Count issues
    total_versions = sum(len(p.versions) for p in database.products)
    total_known = sum(
        len(v.known_issues)
        for p in database.products
        for v in p.versions
    )
    total_addressed = sum(
        len(v.addressed_issues)
        for p in database.products
        for v in p.versions
    )

    # Build product list for display
    product_names = ", ".join(p.name for p in database.products)

    # Determine title based on mode
    if existing_database is not None:
        title = "Incremental Fetch Complete"
        new_versions_count = total_versions - sum(len(v) for v in existing_versions.values())
        mode_info = f"  • New versions added: {new_versions_count}\n"
    else:
        title = "Fetch Complete"
        mode_info = ""

    console.print(
        Panel(
            f"[green]✓[/green] Fetched release notes:\n"
            f"  • Products: {product_names}\n"
            f"  • Total versions: {total_versions}\n"
            f"{mode_info}"
            f"  • Known issues: {total_known}\n"
            f"  • Addressed issues: {total_addressed}\n"
            f"  • Output: {output}",
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


if __name__ == "__main__":
    app()
