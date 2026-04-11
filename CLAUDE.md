# Claude Code Project Instructions

## Git Commits

- Do NOT include "Co-Authored-By" lines in commit messages

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
uv run pytest tests/test_crawler.py -v

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
