# BugDB

A Python CLI application that crawls Palo Alto Networks release notes and generates a static HTML website for browsing and searching bug/issue data.

## Features

- **Automated Crawling**: Fetch known and addressed issues directly from Palo Alto Networks documentation
- **26 Supported Products**: PAN-OS, Prisma Access, GlobalProtect, Cloud NGFW, and more
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

```bash
# Clone the repository
cd bugdb

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install in development mode
pip install -e .

# Install Playwright for web crawling
playwright install chromium
```

## Usage

### Fetch Release Notes

Crawl release notes from Palo Alto Networks documentation:

```bash
# Fetch a single product
bugdb fetch panos -o data/data.json

# Fetch all supported products
bugdb fetch -o data/data.json

# Fetch specific version(s)
bugdb fetch panos --version 11-2 -o data/data.json
bugdb fetch panos --version 11-2,11-1,10-2 -o data/data.json

# Incremental update (add new versions to existing data)
bugdb fetch panos -o data/data.json --incremental

# Force overwrite existing file
bugdb fetch panos -o data/data.json --force
```

### Build Static Site

Generate the HTML website from bug data:

```bash
bugdb build-site-cmd                     # Uses assets/data.json, outputs to dist/
bugdb build-site-cmd -d data/data.json   # Custom data file
bugdb build-site-cmd -o output/          # Custom output directory
```

### View the Site

After building, open the generated site in your browser:

```bash
open dist/index.html
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `bugdb fetch <product>` | Fetch release notes for a product |
| `bugdb fetch` | Fetch all supported products |
| `bugdb build-site-cmd` | Build static HTML site |
| `bugdb generate-sample` | Generate sample data for testing |
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
pytest                           # Run all tests
pytest tests/test_crawler.py -v  # Run crawler tests with verbose output
pytest -k "plugin" -v            # Run tests matching "plugin"
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
│   └── data.json               # Bug database
├── dist/                       # Generated static site
└── tests/
    ├── test_cli.py
    ├── test_crawler.py
    ├── test_models.py
    └── test_site_builder.py
```

## License

MIT
