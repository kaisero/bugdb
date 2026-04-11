# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `bugdb build` — unified one-command workflow for end users. Runs
  `fetch` → `generate-release-notes` → `build-site-cmd` in sequence
  so a single invocation produces a deployable site with real data.
  Flags: `--skip-fetch` (rebuild from existing data.json), `-i`
  (incremental fetch), `--refresh-discovery` (bypass probe cache),
  `--headless`, `--debug`.
- Persistent discovery cache at `.cache/bugdb/discovery.json`
  (project-scoped, gitignored, 24-hour TTL) that survives across
  `bugdb fetch` invocations. Each run loads the cache once via a
  shared `DiscoveryCache` instance and flushes it once after all
  crawlers complete. New module `src/bugdb/discovery_cache.py` with
  22 unit tests covering round-trip, TTL expiry, corrupt-file
  recovery, schema-version mismatch, atomic writes, and per-product
  and wholesale invalidation.
- `bugdb fetch --refresh-discovery` / `-R` flag that bypasses the
  persistent cache and forces a full re-probe. Useful after a docs
  reorganisation or when debugging a crawl.
- `BaseCrawler._resolve_version_infos` — a cache-aware helper that
  centralises the "which versions do we need to crawl" decision
  across all probing product crawlers. Five crawlers (panos,
  globalprotect, prisma_access, prisma_access_agent, prisma_sdwan)
  now use it in their `crawl()` methods.

### Changed
- PAN-OS crawler persists the URL pattern it resolves per major
  version (e.g. `12-1` → `/ngfw/release-notes/12-1`) in the new
  discovery cache. Previously `PANOSCrawler._base_url_for_version`
  was instance-scoped, so every `bugdb fetch` invocation re-probed
  all candidates from scratch. Warm runs now skip ~20 probe requests.
- Probing crawlers (panos, globalprotect, prisma_access,
  prisma_access_agent, prisma_sdwan) skip their entire discovery
  phase on warm incremental runs when the cache is fresh — no
  candidate probing, no per-major index fetches — saving ~125-210
  HTTP requests per run across all five.
- GitLab CI `pages` deploy job is now explicitly branch-gated to
  `$CI_COMMIT_BRANCH == "main"` (previously used `$CI_DEFAULT_BRANCH`,
  which could silently change behaviour if the repo's default branch
  were switched) and additionally requires
  `$CI_PIPELINE_SOURCE == "push"` so that schedule, web-manual, tag,
  and merge-request-event pipelines cannot accidentally trigger a
  deploy. In practice, the deploy now fires exactly when a merge
  request is merged into `main`.

### Removed
- `bugdb generate-sample` command and `src/bugdb/sample_data.py`
  module. Superseded by the new `bugdb build` unified workflow which
  fetches real data instead of generating placeholder data. Tests that
  previously invoked `generate-sample` to seed a data file now use a
  local `_write_minimal_data_file()` helper in `tests/unit/test_cli.py`
  that constructs a minimal `BugDatabase` via the Pydantic models.
  The GitLab CI `pages` deploy job now inlines a tiny empty-database
  JSON placeholder (~1 line of Python) for the same purpose — the
  deployed site loads real data from the CDN at runtime anyway.

### Fixed
- Six crawlers (panos, globalprotect, prisma_access,
  prisma_access_agent, prisma_sdwan, plugins) previously fetched
  `known-and-addressed-issues` hub URLs during discovery. These are
  link-only index pages with no issue tables, so fetching them was
  pure waste (~55 wasted HTTP requests per PAN-OS run, similar
  volumes for other products). `discover_version_pages` now filters
  them out before classification. Regression pin:
  `TestPaloAltoCrawlerAsync::test_panos_discover_skips_known_and_addressed_hub_pages`.
- `BaseCrawler._log` restored to its pre-v1.0.2 behaviour — prints to
  stdout when `verbose=True` AND calls `logger.info` unconditionally.
  v1.0.2 made it logger-only on the assumption that the "double-emit"
  was a bug, but in default Python `logger.info` is a silent no-op
  with no handler attached, so the original code only printed in
  practice (no double-emit). Users running `bugdb fetch --verbose`
  were getting no progress output after v1.0.2, which was the real
  regression. Regression pin:
  `TestCrawlerConfiguration::test_crawler_logging_when_verbose`.
- GitLab CI `test` job now runs `uv run playwright install --with-deps
  chromium` before pytest. v1.0.2 removed this step on the (incorrect)
  assumption that all crawler tests use the MockPlaywright fixture;
  in reality several tests (`TestCortexXDRCrawlerAsync`,
  `TestADEMCrawler`, `TestSCMCrawler`, `TestCloudNGFW*`,
  `TestDeviceSecurityCrawler`, `TestPluginVersionDiscovery`) patch
  individual fetch methods but enter the crawler via
  `async with CrawlerClass()`, which triggers
  `BaseCrawler.__aenter__` → `async_playwright().start()` and needs
  real Chromium. 27 tests were silently failing in environments
  without Chromium installed. The proper architectural fix (lazy
  `__aenter__` or complete MockPlaywright coverage) is tracked as
  roadmap item D3.

## [1.0.2] - 2026-04-11

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
- Pydantic models in `src/bugdb/models.py` all now declare
  `model_config = ConfigDict(extra="forbid")` via a shared
  `STRICT_MODEL_CONFIG`. Unexpected fields in serialized JSON fail
  validation loudly instead of silently dropping data, catching schema
  drift at load time.
- `BugDatabase` serialization in `cli.py` and `site_builder.py` now
  passes `exclude_none=True` to `model_dump`. The generated
  `data.json` is ~30–40% smaller because optional fields set to None
  (workaround, symptoms, fix_info, affected_components, release_date)
  are omitted entirely instead of written as `null`. The frontend uses
  truthiness checks so `null` and `undefined` behave identically.
- `SiteBuilder.env` now uses `jinja2.select_autoescape(["html", "htm",
  "xml"])` instead of the blanket `autoescape=True`. Aligns with
  Jinja2's recommended pattern — only HTML/XML templates are escaped,
  not CSS or JS templates.
- `BaseCrawler._log` no longer double-emits to both `print` (when
  verbose) and `logger.info`. It's now logger-only; callers that want
  console output attach a `RichHandler` via the CLI.
- `cli.py::fetch` now narrows its exception scope around the per-product
  crawl loop, the database merge, and the JSON write. Previously a
  single `except Exception` wrapped the entire ~100-line block and
  printed a generic "Error: {e}" on exit, hiding which product failed.
  Errors now surface as "Error fetching <product_name>: {e}" or
  "Error writing <path>: {e}" so users and bug reports can pin the
  failure to a specific stage.
- `src/bugdb/crawler.py` is collapsed to a thin `from bugdb.crawlers
  import *` shim (plus a `PaloAltoCrawler = BaseCrawler` alias and a
  `DeprecationWarning`). It was never actually deprecated — the
  project's own CLI imported from it — but v1.0.2 moved the CLI to
  `bugdb.crawlers` and this commit reduces the shim to pure re-export
  so that the "deprecated" label now matches reality.
- GitLab CI pipeline restructured from 3 stages (`test`, `integration`,
  `deploy`) to 5 (`lint`, `test`, `integration`, `canary`, `deploy`).
  `lint` moved to its own stage ahead of `test` so lint-only changes
  get feedback without waiting on test setup. The fast `test` job no
  longer runs `playwright install --with-deps chromium` — all fast-tier
  crawler tests use the MockPlaywright fixture, so installing ~200 MB
  of Chromium on every commit was pure waste. `data-baseline-integration`
  and `upstream-canary` now live in separate stages so a canary flake
  can't block a green data-baseline run. The fast `test` stage also
  now runs on MRs (previously develop-only) so merge requests get full
  unit coverage before merge.
- `cli.py::fetch` now derives its `supported_products` mapping from
  `PRODUCT_WRAPPERS` in `src/bugdb/crawlers/registry.py`, instead of
  maintaining a parallel hand-written dict. Drift between the CLI and
  the registry was previously silent — a product added to the registry
  but forgotten in the CLI would fail lookup at runtime. The new test
  file `tests/unit/test_registry.py` pins the invariant.
- `cli.py` now imports from `bugdb.crawlers` (the modular package)
  rather than `bugdb.crawler` (the deprecated backward-compat shim), so
  the shim is no longer on the live production path.
- `FetchResult` dataclass no longer does `from bugdb.models import BugDatabase`
  inside its class body — the import is hoisted to module scope where it
  belongs. The inline form was a brittle workaround for a perceived
  circular import that didn't actually exist.
- `PluginConfig` default factories for `known_issues_keywords` and
  `addressed_issues_keywords` now use `field(default_factory=...)`
  instead of `= None` + `__post_init__`, which was lying about the
  declared type.
- `datetime.timezone.utc` replaced with `datetime.UTC` (Python 3.11+
  idiom) in `src/bugdb/models.py` and `src/bugdb/cli.py`.
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
- `cortex_xdr.fetch_release` return-type annotation now uses `BeautifulSoup`
  instead of the builtin `any` (a typo for `typing.Any`) — readers were
  misled and type checkers rejected the old form.
- `bugdb/__init__.py::_read_version` now catches the specific
  `PackageNotFoundError` instead of the bare `Exception` class, so
  genuine import errors in `importlib.metadata` bubble up.
- `PluginCrawler` now records `FailedFetch` entries for **addressed-issue**
  fetch errors. Previously the exception branch only logged addressed-issue
  failures at debug level and dropped them, so the retry pass and the
  fetch-report JSON never saw them for any of the 11 plugin crawlers.
- `BaseCrawler._parse_issues_page` now propagates fetch and parse
  exceptions to its callers instead of swallowing them and returning
  an empty list. Previously the silent swallow rendered the
  `asyncio.gather(..., return_exceptions=True)` dispatcher in
  `_crawl_version` dead code — failures were invisible to the
  `FailedFetch` accounting and to the retry loop. Propagating lets the
  existing dispatcher do its job. Related known issue: the retry loop
  itself still discards recovered issues (they are returned but every
  caller ignores them); fixing that properly requires threading
  `product_versions` through every product crawler's `crawl()` call
  site and is tracked as roadmap item D6 in `docs/roadmap.md`.
- `BaseCrawler._fetch_page_with_semaphore` and
  `_fetch_cortex_page_with_semaphore` previously raised a confusing
  `TypeError` (instead of the real failure) when `max_retries == 0`, and
  would raise `UnboundLocalError` in the `finally` block if
  `_new_page()` itself failed before the `try`. Both methods now guard
  the `last_error is None` case and only call `page.close()` when a page
  was actually created.
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

[Unreleased]: https://gitlab.com/dependencyhell/bugdb/-/compare/v1.0.2...HEAD
[1.0.2]: https://gitlab.com/dependencyhell/bugdb/-/compare/v1.0.1...v1.0.2
[1.0.1]: https://gitlab.com/dependencyhell/bugdb/-/compare/v1.0.0...v1.0.1
[1.0.0]: https://gitlab.com/dependencyhell/bugdb/-/tags/v1.0.0
