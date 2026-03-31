"""Static site builder for BugDB."""

import json
import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from bugdb import __version__
from bugdb.models import BugDatabase


class SiteBuilder:
    """Builds static HTML site from bug database."""

    def __init__(self, output_dir: Path):
        """Initialize the site builder.

        Args:
            output_dir: Directory where the static site will be generated.
        """
        self.output_dir = output_dir
        self.templates_dir = Path(__file__).parent / "templates"
        self.env = Environment(
            loader=FileSystemLoader(self.templates_dir),
            autoescape=True,
        )

    def build(self, database: BugDatabase) -> None:
        """Build the static site from the bug database.

        Args:
            database: The bug database to generate the site from.
        """
        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Create assets directory
        assets_dir = self.output_dir / "assets"
        assets_dir.mkdir(exist_ok=True)

        # Copy JavaScript file
        self._copy_assets(assets_dir)

        # Generate data.json
        self._generate_data_json(database, assets_dir)

        # Render HTML template
        self._render_html(database)

    def _copy_assets(self, assets_dir: Path) -> None:
        """Copy static assets to output directory.

        Args:
            assets_dir: Target assets directory.
        """
        source_assets = self.templates_dir / "assets"
        if source_assets.exists():
            for asset_file in source_assets.iterdir():
                if asset_file.is_file():
                    shutil.copy2(asset_file, assets_dir / asset_file.name)

    def _generate_data_json(self, database: BugDatabase, assets_dir: Path) -> None:
        """Generate the data.json file for client-side use.

        Args:
            database: The bug database.
            assets_dir: Target assets directory.
        """
        data_file = assets_dir / "data.json"
        with open(data_file, "w", encoding="utf-8") as f:
            json.dump(
                database.model_dump(mode="json"),
                f,
                indent=2,
                default=str,
            )

    def _render_html(self, database: BugDatabase) -> None:
        """Render the HTML template.

        Args:
            database: The bug database (for any server-side rendering needs).
        """
        template = self.env.get_template("index.html")
        html_content = template.render(database=database, app_version=__version__)

        output_file = self.output_dir / "index.html"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(html_content)


def build_site(
    data_file: Path,
    output_dir: Path,
) -> None:
    """Build static site from a JSON data file.

    Args:
        data_file: Path to the bug database JSON file.
        output_dir: Directory where the static site will be generated.
    """
    # Load and validate data
    with open(data_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    database = BugDatabase.model_validate(data)

    # Build the site
    builder = SiteBuilder(output_dir)
    builder.build(database)


def build_site_from_database(
    database: BugDatabase,
    output_dir: Path,
) -> None:
    """Build static site from a BugDatabase object.

    Args:
        database: The bug database object.
        output_dir: Directory where the static site will be generated.
    """
    builder = SiteBuilder(output_dir)
    builder.build(database)
