# Claude Code Project Instructions

## Git Commits

- Do NOT include "Co-Authored-By" lines in commit messages

## Project Documentation

Two living documents must be kept current alongside code changes:

### CHANGELOG.md

Every user-visible change — new features, enhancements, bug fixes, breaking
changes, deprecations, security fixes — **must** be recorded in
`CHANGELOG.md` as part of the same change (commit or PR). The changelog
follows the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format
and [Semantic Versioning](https://semver.org/). Unreleased work goes under
the `## [Unreleased]` heading; on release, that section is renamed to the
new version with the release date and a fresh `## [Unreleased]` stub is
added above it. Do not batch changelog updates — write the entry when you
write the code.

Categories (in order): `Added`, `Changed`, `Deprecated`, `Removed`,
`Fixed`, `Security`.

### docs/design-decisions.md

Architectural and design decisions — anything a future contributor would
benefit from knowing the *why* behind — must be captured in
`docs/design-decisions.md`. This is a lightweight ADR log: each entry has a
short title, date, context (what problem forced the decision), the
decision itself, and the consequences/trade-offs accepted. Update or add an
entry whenever you:

- Choose between non-obvious alternatives (framework, library, data model,
  CI layout, testing strategy)
- Add or change a project-wide convention (e.g., linter config, marker
  semantics, baseline snapshot format)
- Accept a known trade-off that would surprise someone reading only the
  code (e.g., "we tolerate N xfails here because…")
- Introduce or retire a subsystem

Keep entries short — a paragraph each is fine. The goal is future-proofing
context, not exhaustive documentation.

## Development Guidelines

### Package Management

This project uses **uv** for dependency and Python version management. Do not
use `pip` or `python -m venv` directly.

- `uv sync` — install runtime dependencies into `.venv`
- `uv sync --group test` — also install the `test` dependency group
- `uv run <cmd>` — run a command inside the project environment
- `uv add <pkg>` / `uv remove <pkg>` — manage dependencies (updates
  `pyproject.toml` and `uv.lock`)
- `uv lock` — refresh `uv.lock` after manual edits to `pyproject.toml`

The Python interpreter is pinned in `.python-version`. `uv.lock` is committed
and CI runs `uv sync --locked` — never hand-edit the lockfile.

### Testing New Product Crawlers

When implementing a new product crawler, **do not run a full fetch of all products** for testing. This causes very long testing times due to multiple web crawler tasks.

Follow this workflow:

1. **Initial testing** - Test only the new product with a separate output file:
   ```bash
   # Good - test only the new product
   uv run bugdb fetch new-product -o data/new-product.json -f

   # Bad - fetches ALL products (takes a very long time)
   uv run bugdb fetch
   ```

2. **After verifying the crawler works** - Add the new product to the existing database using incremental mode:
   ```bash
   # Add new product to existing data.json
   uv run bugdb fetch new-product -o data/data.json --incremental
   ```

3. **Build the site** to verify everything works:
   ```bash
   uv run bugdb build-site-cmd
   ```

### Running Tests

```bash
# Run all tests
uv run pytest

# Run specific test file
uv run pytest tests/crawler/test_crawler.py -v

# Run tests matching a pattern
uv run pytest -k "cloud_ngfw" -v
```

### Building the Site

```bash
# Build static site from data.json
uv run bugdb build-site-cmd

# Open in browser
open dist/index.html
```
