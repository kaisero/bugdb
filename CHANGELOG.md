# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `ruff` linting and formatting, enforced via a local pre-commit hook
  (`astral-sh/ruff-pre-commit`) and a GitLab CI `lint` job that runs on
  every develop commit and merge request. Conservative starter ruleset
  (`E, W, F, I, B, UP, SIM, RUF`), line-length 100, per-file ignores for
  tests.
- `dev` dependency group in `pyproject.toml` for contributor tooling
  (ruff, pre-commit) — kept separate from the `test` group so the fast
  CI tier doesn't pull lint tools and the lint job doesn't pull Playwright.
- `.pre-commit-config.yaml` with `ruff-check --fix` and `ruff-format`
  hooks, version-pinned to match the ruff version in `dev`.
- Data-fidelity integration test tier (`tests/integration/`, `@pytest.mark.data_baseline`)
  that compares `assets/data.json` against a committed baseline snapshot
  (`tests/baselines/data_baseline.json`) and fails if any previously-fetched product,
  version, issue count, or bug_id regresses.
- Upstream-version canary tier (`tests/canary/`, `@pytest.mark.canary`) that probes
  `docs.paloaltonetworks.com` directly to catch new major versions the crawler's
  hard-coded candidate list doesn't yet know about.
- `src/bugdb/baseline.py` module with `Baseline`, `BaselineSnapshot`, and a
  `python -m bugdb.baseline refresh|diff` CLI for baseline management.
- GitLab CI `integration` stage with `data-baseline-integration` (scheduled nightly
  + MR-on-data-changes) and `upstream-canary` (scheduled nightly, `allow_failure: true`)
  jobs.
- Regression test pinning the PAN-OS 12.1 URL-pattern fix
  (`tests/crawler/test_crawler.py::test_panos_12_1_only_discoverable_via_ngfw_url`).
- `CHANGELOG.md` (this file).
- `docs/design-decisions.md` lightweight ADR log for non-obvious design decisions.

### Changed
- Codebase reformatted and linted by ruff as a one-time mechanical sweep
  (no behaviour changes). Findings fixed: import ordering, `Optional`/`Union`
  converted to `X | None`/`X | Y`, `raise ... from err` added inside
  `except` blocks, nested `if` collapsed, unused unpacked variables renamed
  to `_prefix`, `zip(..., strict=True)` added, and long lines wrapped.
  Commit recorded in `.git-blame-ignore-revs` so `git blame` skips it.
- Project now uses [uv](https://github.com/astral-sh/uv) for dependency and Python
  version management instead of pip/venv. `pyproject.toml` uses `[dependency-groups]`
  instead of `[project.optional-dependencies]`; Python version is pinned via
  `.python-version`; CI uses the `ghcr.io/astral-sh/uv:python3.12-bookworm-slim`
  image and `uv sync --locked` for reproducible installs.
- PAN-OS crawler now probes both `/ngfw/release-notes/<v>` and the legacy
  `/pan-os/<v>/pan-os-release-notes` URL patterns and caches the resolved
  per-major-version base URL. This restores PAN-OS 12.1.x fetching after Palo Alto
  moved 12.1+ release notes to the `/ngfw/release-notes` tree.
- Tests reorganised into `tests/unit/`, `tests/crawler/`, `tests/integration/`,
  and `tests/canary/` subdirectories.
- `pyproject.toml` `[tool.pytest.ini_options]` uses `--strict-markers` and excludes
  heavy tiers by default via `addopts = "--strict-markers -m 'not data_baseline and not canary'"`.

### Fixed
- PAN-OS 12.1.x release notes were silently skipped because the crawler only knew
  the legacy `/pan-os/<v>/pan-os-release-notes` URL pattern, which 404s for 12.1+.
  Crawler now falls back to `/ngfw/release-notes/<v>`.
- Stale fixture mapping in `tests/conftest.py` that mapped both the legacy and
  NGFW PAN-OS 12.1 URLs to the same fixture file, masking the above bug. The legacy
  mapping has been removed and a regression test pins the correct behaviour.

## [1.0.1] - 2026-03-31

### Added
- Centralised version management via a top-level `VERSION` file consumed by
  `hatch.version` and the webapp release-notes view.
- Release-notes generation in the `pages` deploy stage plus an in-webapp view.
- Playwright browser install step in the `test` CI job so crawler tests have
  Chromium available.
- `develop` branch pipeline separate from `main`.
- Various crawler bug fixes and a fix for a webapp dropdown filter issue.

### Changed
- Crawler package refactored from a single `crawler.py` into a modular
  `src/bugdb/crawlers/` package (`base.py`, `models.py`, `registry.py`, `utils.py`,
  and `products/*`).
- `src/bugdb/templates/assets` is now force-included in the built wheel so the
  CI pages job can build the static site from the installed package.

### Fixed
- Multiple crawler parser bugs surfaced after the 1.0.0 release.
- Webapp dropdown filter behaviour (incorrect selection state on reload).

## [1.0.0] - 2026-03-29

First tagged release. The project is a static HTML site generator for browsing
Palo Alto Networks release-note bugs and known issues, backed by a fleet of
product-specific web crawlers.

### Added
- Typer-based `bugdb` CLI with `fetch`, `build-site-cmd`, and `generate-sample`
  commands.
- Pydantic data models (`Issue`, `ProductVersion`, `Product`, `BugDatabase`).
- Initial crawler with incremental fetch support (`1d46e28`).
- Product crawlers for: PAN-OS (with hotfix release support), GlobalProtect,
  Cortex XDR, Prisma Access, Prisma Access Agent, Prisma SD-WAN, SCM, ADEM,
  Cloud NGFW for AWS, Cloud NGFW for Azure, AI Runtime Security, Remote Browser
  Isolation, Strata Logging Service, Device Security, plus Panorama plugins
  and SaaS products.
- Workaround extraction from issue descriptions.
- `fix_info` extraction from issue descriptions.
- `Fix Available` feature with PAN-OS hotfix release tracking.
- Pagination and global request backoff in the crawler base class.
- Jinja2-based static site builder with Product/Version/Type filter autocomplete.
- Sample-data generator for local demos.
- GitLab Pages deployment configuration.
- README with full product list and CLI usage examples.

[Unreleased]: https://gitlab.com/dependencyhell/bugdb/-/compare/v1.0.1...HEAD
[1.0.1]: https://gitlab.com/dependencyhell/bugdb/-/compare/v1.0.0...v1.0.1
[1.0.0]: https://gitlab.com/dependencyhell/bugdb/-/tags/v1.0.0
