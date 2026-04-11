# BugDB

A Python CLI application that crawls Palo Alto Networks release notes and generates a static HTML website for browsing and searching bug/issue data.

## Features

- **Automated Crawling**: Fetch known and addressed issues directly from Palo Alto Networks documentation
- **27 Supported Products**: PAN-OS, Prisma Access, GlobalProtect, Cloud NGFW, Cortex XDR, and more
- **Static Site Generation**: Build a fast, searchable HTML site with client-side filtering
- **Incremental Updates**: Add new products or versions without re-fetching existing data
- **Full-Text Search**: Search across bug IDs, descriptions, symptoms, and workarounds

## Supported Products

| Product | Supported |
|---------|:---------:|
| PAN-OS | ✅ |
| GlobalProtect | ✅ |
| Strata Cloud Manager (SCM) | ✅ |
| Prisma Access | ✅ |
| Prisma Access Agent | ✅ |
| Prisma SD-WAN | ✅ |
| Cloud NGFW for AWS | ✅ |
| Cloud NGFW for Azure | ✅ |
| Cortex XDR Agent | ✅ |
| Device Security | ✅ |
| VM-Series Plugin | ✅ |
| Panorama Plugin for AWS | ✅ |
| Panorama Plugin for Azure | ✅ |
| Panorama Plugin for GCP | ✅ |
| Panorama Plugin for VMware NSX | ✅ |
| Panorama Plugin for VMware vCenter | ✅ |
| Panorama Plugin for Kubernetes | ✅ |
| Panorama Plugin for Cisco ACI | ✅ |
| Panorama Plugin for Cisco TrustSec | ✅ |
| Panorama Plugin for Zero Touch Provisioning | ✅ |
| Panorama Plugin for Clustering | ✅ |
| Panorama SD-WAN Plugin | ✅ |
| Autonomous DEM (ADEM) | ✅ |
| AI Runtime Security | ✅ |
| Remote Browser Isolation | ✅ |
| Strata Logging Service | ✅ |

## Installation

This project uses [uv](https://docs.astral.sh/uv/) for dependency and Python
version management. Install uv first
([instructions](https://docs.astral.sh/uv/getting-started/installation/)),
then:

```bash
# Clone the repository
cd bugdb

# Create the virtual environment and install the project (including the
# pinned Python interpreter from .python-version)
uv sync

# Install Playwright browsers for web crawling
uv run playwright install chromium
```

All `bugdb` commands below should be prefixed with `uv run` (e.g.
`uv run bugdb fetch panos`), or you can activate the environment with
`source .venv/bin/activate` and drop the prefix.

## Usage

### Unified Build (Recommended)

Single command that fetches all bug data, regenerates release notes,
and builds the static site. This is the shortest path from a clean
checkout to a deployable website.

```bash
# Full build: fetch everything, build into dist/
bugdb build

# Incremental: only fetch versions not already in assets/bugdb.json
bugdb build --incremental

# Skip fetch entirely and just rebuild the site from existing data
# (useful for iterative frontend work)
bugdb build --skip-fetch

# Force re-probe of upstream URLs (bypasses 24-hour discovery cache)
bugdb build --refresh-discovery
```

### Fetch Release Notes

If you want more control over which products to fetch, use `bugdb fetch`
directly:

```bash
# Fetch a single product
bugdb fetch panos -o assets/bugdb.json

# Fetch all supported products
bugdb fetch -o assets/bugdb.json

# Fetch specific version(s)
bugdb fetch panos --version 11-2 -o assets/bugdb.json
bugdb fetch panos --version 11-2,11-1,10-2 -o assets/bugdb.json

# Incremental update (add new versions to existing data)
bugdb fetch panos -o assets/bugdb.json --incremental

# Force overwrite existing file
bugdb fetch panos -o assets/bugdb.json --force
```

### Build Static Site

If you already have a bug database file and just want to rebuild the HTML:

```bash
bugdb build-site-cmd                        # Uses assets/bugdb.json, outputs to dist/
bugdb build-site-cmd -b assets/bugdb.json   # Custom bug database
bugdb build-site-cmd -o output/             # Custom output directory
```

### View the Site

After building, open the generated site in your browser:

```bash
open dist/index.html
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `bugdb build` | Unified workflow: fetch → release notes → build site |
| `bugdb fetch <product>` | Fetch release notes for a single product |
| `bugdb fetch` | Fetch all supported products |
| `bugdb build-site-cmd` | Build the static HTML site from an existing bug database file |
| `bugdb generate-release-notes` | Regenerate the release notes JSON for the site |
| `bugdb validate` | Validate a bug database JSON file against the schema |
| `bugdb --version` | Show version |
| `bugdb --help` | Show help |

### Fetch Options

| Option | Description |
|--------|-------------|
| `-o, --output` | Output JSON file path |
| `-v, --version` | Version(s) to fetch (e.g., "11-2" or "11-2,11-1") |
| `--incremental` | Add to existing data instead of overwriting |
| `-f, --force` | Overwrite existing output file |
| `--headless/--no-headless` | Run browser in headless mode |
| `--debug` | Enable debug logging |

## JSON Schema

The bug database uses this structure:

```json
{
  "metadata": {
    "generated_at": "2026-03-29T10:00:00Z",
    "version": "1.0.0",
    "source": "Palo Alto Networks Release Notes"
  },
  "products": [
    {
      "id": "panos",
      "name": "PAN-OS",
      "versions": [
        {
          "version": "11.2.3",
          "known_issues": [
            {
              "bug_id": "PAN-300637",
              "description": "Issue description",
              "workaround": "Known workaround",
              "fix_info": "Fixed in 11.2.4",
              "affected_components": ["Hardware", "Networking"]
            }
          ],
          "addressed_issues": [
            {
              "bug_id": "PAN-201910",
              "description": "Fixed issue description"
            }
          ]
        }
      ]
    }
  ]
}
```

### Issue Fields

| Field | Required | Description |
|-------|----------|-------------|
| `bug_id` | Yes | Unique bug identifier (e.g., PAN-300637) |
| `description` | Yes | Issue description |
| `workaround` | No | Known workaround |
| `fix_info` | No | Fix availability information |
| `affected_components` | No | Array of affected components |
| `release_date` | No | Date when issue was addressed |

## Development

### Running Tests

```bash
# Sync the test dependency group, then run tests
uv sync --group test

uv run pytest                           # Run all tests
uv run pytest tests/test_crawler.py -v  # Run crawler tests with verbose output
uv run pytest -k "plugin" -v            # Run tests matching "plugin"
```

### Project Structure

```
bugdb/
├── pyproject.toml              # Project config and dependencies
├── README.md
├── src/bugdb/
│   ├── __init__.py             # Package version
│   ├── cli.py                  # Typer CLI commands
│   ├── crawler.py              # Web crawler for release notes
│   ├── models.py               # Pydantic data models
│   ├── sample_data.py          # Sample data generation
│   ├── site_builder.py         # Static site generator
│   └── templates/
│       └── index.html          # Main HTML template
├── data/
│   └── bugdb.json               # Bug database
├── dist/                       # Generated static site
└── tests/
    ├── test_cli.py
    ├── test_crawler.py
    ├── test_models.py
    └── test_site_builder.py
```

## License

MIT
