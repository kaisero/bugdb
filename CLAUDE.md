# Claude Code Project Instructions

## Git Commits

- Do NOT include "Co-Authored-By" lines in commit messages

## Development Guidelines

### Testing New Product Crawlers

When implementing a new product crawler, **do not run a full fetch of all products** for testing. This causes very long testing times due to multiple web crawler tasks.

Follow this workflow:

1. **Initial testing** - Test only the new product with a separate output file:
   ```bash
   # Good - test only the new product
   bugdb fetch new-product -o data/new-product.json -f

   # Bad - fetches ALL products (takes a very long time)
   bugdb fetch
   ```

2. **After verifying the crawler works** - Add the new product to the existing database using incremental mode:
   ```bash
   # Add new product to existing data.json
   bugdb fetch new-product -o data/data.json --incremental
   ```

3. **Build the site** to verify everything works:
   ```bash
   bugdb build-site-cmd
   ```

### Running Tests

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_crawler.py -v

# Run tests matching a pattern
pytest -k "cloud_ngfw" -v
```

### Building the Site

```bash
# Build static site from data.json
bugdb build-site-cmd

# Open in browser
open dist/index.html
```
