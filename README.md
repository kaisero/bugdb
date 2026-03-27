# BugDB

A Python CLI application that generates a static HTML website for browsing and searching bug/issue data from Palo Alto Networks release notes.

## Features

- Generate sample bug database with realistic PAN-OS, Panorama, and GlobalProtect issues
- Build static HTML site with client-side search and filtering
- Validate JSON data against schema
- Beautiful UI with Tailwind CSS
- Filter by product, version, issue type, and severity
- Full-text search across bug IDs, descriptions, symptoms, and workarounds

## Installation

```bash
# Clone the repository
cd bugdb

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install in development mode
pip install -e .

# Install test dependencies
pip install pytest
```

## Usage

### Generate Sample Data

Create a sample bug database JSON file:

```bash
bugdb generate-sample                    # Creates data/bugs.json
bugdb generate-sample -o custom.json     # Custom output path
bugdb generate-sample --force            # Overwrite existing file
```

### Build Static Site

Generate the HTML website from bug data:

```bash
bugdb build-site                         # Uses data/bugs.json, outputs to dist/
bugdb build-site -d custom.json          # Custom data file
bugdb build-site -o output/              # Custom output directory
```

### Validate Data

Validate a JSON file against the schema:

```bash
bugdb validate data/bugs.json
```

### View the Site

After building, open the generated site in your browser:

```bash
open dist/index.html
```

## JSON Schema

The bug database uses this structure:

```json
{
  "metadata": {
    "generated_at": "2026-03-26T10:00:00Z",
    "version": "1.0.0",
    "source": "Palo Alto Networks Release Notes"
  },
  "products": [
    {
      "id": "pan-os",
      "name": "PAN-OS",
      "versions": [
        {
          "version": "11.1.3",
          "release_date": "2026-03-15",
          "known_issues": [
            {
              "bug_id": "PAN-300637",
              "description": "Issue description",
              "severity": "medium",
              "symptoms": "Observable symptoms",
              "workaround": "Known workaround",
              "affected_components": ["Hardware", "Networking"]
            }
          ],
          "addressed_issues": [
            {
              "bug_id": "PAN-201910",
              "description": "Fixed issue description",
              "severity": "high"
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
| `severity` | No | critical, high, medium, low, or info |
| `symptoms` | No | Observable symptoms |
| `workaround` | No | Known workaround |
| `affected_components` | No | Array of affected components |

## Development

### Running Tests

```bash
pytest
```

### Project Structure

```
bugdb/
├── pyproject.toml              # Project config and dependencies
├── README.md
├── .gitignore
├── src/bugdb/
│   ├── __init__.py             # Package version
│   ├── cli.py                  # Typer CLI commands
│   ├── models.py               # Pydantic data models
│   ├── sample_data.py          # Sample data generation
│   ├── site_builder.py         # Static site generator
│   └── templates/
│       ├── index.html          # Main HTML template
│       └── assets/
│           └── app.js          # Search/filter JavaScript
├── data/
│   └── bugs.json               # Bug database
├── dist/                       # Generated static site
└── tests/
    ├── test_cli.py
    ├── test_models.py
    └── test_site_builder.py
```

## License

MIT
