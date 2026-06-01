"""Static site builder for BugDB.

The builder takes three kinds of input and writes them into a single
output directory shaped like this::

    dist/
    ├── index.html
    └── assets/
        ├── app.js              (copied from templates/assets/)
        ├── tailwind.css        (copied from templates/assets/)
        ├── bugdb.json          (generated from the BugDatabase)
        └── release-notes.json  (copied from a caller-supplied path,
                                 optional — the frontend handles its
                                 absence by hiding the release-notes link)

The working-directory convention is `assets/bugdb.json` +
`assets/release-notes.json` — both in the same folder, both fed into
the same output subdir.
"""

import json
import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from bugdb import __version__
from bugdb.models import BugDatabase

# Canonical filename for the bug database JSON across the CLI, the
# generated static site, and the frontend fetch URL. Keep these in
# sync with `app.js` which calls `fetch('assets/bugdb.json')`.
BUGDB_JSON_FILENAME = "bugdb.json"
RELEASE_NOTES_FILENAME = "release-notes.json"


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
            autoescape=select_autoescape(["html", "htm", "xml"]),
        )

    def build(
        self,
        database: BugDatabase,
        release_notes_file: Path | None = None,
    ) -> None:
        """Build the static site from the bug database.

        Args:
            database: The bug database to generate the site from.
            release_notes_file: Optional path to a ``release-notes.json``
                file produced by ``bugdb generate-release-notes``. If
                provided and the file exists, it's copied to
                ``<output>/assets/release-notes.json``. If ``None`` or
                missing, the site is built without a release notes
                artifact and the frontend hides the Release Notes link.
        """
        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Create assets directory
        assets_dir = self.output_dir / "assets"
        assets_dir.mkdir(exist_ok=True)

        # Copy static assets (app.js, tailwind.css, etc.)
        self._copy_assets(assets_dir)

        # Generate bugdb.json from the database
        self._generate_bugdb_json(database, assets_dir)

        # Optional release notes pass-through
        if release_notes_file is not None and release_notes_file.exists():
            self._copy_release_notes(release_notes_file, assets_dir)

        # Render HTML template
        self._render_html(database)

    def _copy_assets(self, assets_dir: Path) -> None:
        """Copy static assets to the output directory.

        Every file in ``templates/assets/`` is copied verbatim. This
        covers ``app.js`` and ``tailwind.css``. It deliberately does NOT
        cover ``release-notes.json`` — that artifact lives outside the
        template tree now (see module docstring) and is handled by
        ``_copy_release_notes``.
        """
        source_assets = self.templates_dir / "assets"
        if source_assets.exists():
            for asset_file in source_assets.iterdir():
                if asset_file.is_file():
                    shutil.copy2(asset_file, assets_dir / asset_file.name)

    def _generate_bugdb_json(self, database: BugDatabase, assets_dir: Path) -> None:
        """Write the bug database to ``<assets>/bugdb.json`` for client use."""
        bugdb_file = assets_dir / BUGDB_JSON_FILENAME
        with open(bugdb_file, "w", encoding="utf-8") as f:
            # exclude_none=True drops optional fields whose value is None
            # (workaround, symptoms, fix_info, affected_components,
            # release_date), shrinking the generated bugdb.json by
            # ~30-40%. The frontend already uses truthiness checks, so
            # `null` and "missing key" behave identically in app.js.
            json.dump(
                database.model_dump(mode="json", exclude_none=True),
                f,
                indent=2,
                default=str,
            )

    def _copy_release_notes(self, release_notes_file: Path, assets_dir: Path) -> None:
        """Copy a generated release-notes.json into ``<assets>/``."""
        shutil.copy2(release_notes_file, assets_dir / RELEASE_NOTES_FILENAME)

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
    bugdb_file: Path,
    output_dir: Path,
    release_notes_file: Path | None = None,
) -> None:
    """Build static site from a bug database JSON file.

    Args:
        bugdb_file: Path to the bug database JSON file (typically
            ``assets/bugdb.json``).
        output_dir: Directory where the static site will be generated.
        release_notes_file: Optional path to a release-notes.json file.
            If omitted, auto-discover as
            ``<bugdb_file.parent>/release-notes.json`` — which is the
            convention used by ``bugdb build`` and the unified
            ``assets/`` workflow. Pass ``None`` explicitly to build a
            site without any release notes.
    """
    # Load and validate the bug database
    with open(bugdb_file, encoding="utf-8") as f:
        data = json.load(f)

    database = BugDatabase.model_validate(data)

    # Auto-discover release-notes.json next to the bug database file
    # if the caller didn't specify. This is the default for `bugdb
    # build-site-cmd` when the user has the unified assets/ layout.
    resolved_release_notes = release_notes_file
    if resolved_release_notes is None:
        candidate = bugdb_file.parent / RELEASE_NOTES_FILENAME
        if candidate.exists():
            resolved_release_notes = candidate

    # Build the site
    builder = SiteBuilder(output_dir)
    builder.build(database, release_notes_file=resolved_release_notes)


def build_site_from_database(
    database: BugDatabase,
    output_dir: Path,
    release_notes_file: Path | None = None,
) -> None:
    """Build static site from a BugDatabase object.

    Args:
        database: The bug database object.
        output_dir: Directory where the static site will be generated.
        release_notes_file: Optional path to a release-notes.json file.
    """
    builder = SiteBuilder(output_dir)
    builder.build(database, release_notes_file=release_notes_file)
