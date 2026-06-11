# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.5] - 2026-06-11

### Changed
- **Baseline refreshed against the sitemap/httpx crawler generation.**
  `tests/baselines/data_baseline.json` is now a fingerprint of the
  2026-06-02 Package Registry artifact (the first crawl produced by the
  new sitemap-driven fetch). The April baseline fingerprinted the old
  Playwright/DOM crawler, whose version keying no longer matches:
  Prisma Access majors gained a `.0` patch component (`4.0` → `4.0.0`),
  GlobalProtect combined hotfix/build pages are keyed by build tag
  (`6.2.8-h2` → `6.2.8-c243`), PAN-OS addressed issues are split into
  per-hotfix versions instead of aggregated under the base release, and
  Cortex XDR labels follow the FluidTopics API. Net delta: +1,600
  versions discovered, ~200 baseline bug ids relocated to more precise
  version keys, junk artifacts of the old DOM parser dropped
  (`1.9932.4796-a4d6`, `CPATR-23499Windows`).
- **PAN-OS 10.0.x accepted as an EOL drop.** Palo Alto delisted the
  10.0 release notes from `sitemap.xml`; sitemap-driven discovery can
  no longer see them (the pages themselves still resolve). The 26
  versions / 199 bug ids are intentionally absent from the refreshed
  baseline.
- **`fetch` stage now precedes `integration` in CI.** A red
  data-baseline run used to skip the scheduled `update-bugdb` job,
  freezing the registry artifact until the baseline was fixed (this
  starved refreshes between 2026-06-02 and 2026-06-10). The baseline
  tier now validates the artifact that was *just* fetched and never
  blocks the next fetch. `upstream-canary` gets `needs: []` so upstream
  probing is independent of both.
- **Version-format invariant accepts bare numeric hotfix suffixes.**
  Upstream really publishes `pan-os-8-1-25-2-addressed-issues` (no `h`
  in the slug), so `VERSION_RE` now allows `8.1.25-2` alongside
  `12.1.5-h2` / `6.2.8-c223` / `6.2.9-linux`.

## [1.0.4] - 2026-06-02

### Added
- **httpx-based Transport layer.** New `Transport` protocol +
  `FetchedPage` dataclass in `src/bugdb/transport/` lets `BaseCrawler`
  take an injected fetcher instead of always launching Playwright.
  `HttpxDocsTransport` handles the public docs site over HTTP/2 with
  shared connection reuse; `FluidTopicsTransport` talks to the Cortex
  khub JSON API. `BaseCrawler.__init__` gains `transport=` and the
  fetch path forks via `_fetch_page_with_semaphore` →
  `_fetch_via_transport` / `_fetch_via_browser`. The Playwright path
  is preserved as a fallback (`--use-browser`).
- **Sitemap-driven URL discovery.** New `SitemapIndex` in
  `src/bugdb/sitemap.py` parses
  `https://docs.paloaltonetworks.com/sitemap.xml` once at the start of
  a fetch, classifies every URL by product prefix (`_PRODUCT_PREFIXES`),
  and exposes `for_product(product_id)` plus a per-entry
  `major_version` derived by `extract_dotted_version` (dashed,
  run-together, 2-dashed major-minor path-segment fallbacks). Replaces
  per-product JS-rendered version probing for PAN-OS, GlobalProtect,
  Prisma Access, Prisma Access Agent, Prisma SD-WAN, Device Security,
  Panorama plugins, and the SaaS family (AIRS, RBI, Cloud NGFW
  AWS/Azure, SLS). New shared helpers in
  `src/bugdb/crawlers/sitemap_discovery.py`
  (`discover_major_versions`, `discover_version_pages`,
  `discover_saas_urls`, `group_into_version_infos`,
  `filter_unchanged`).
- **Fetch manifest for incremental skipping.**
  `src/bugdb/fetch_manifest.py` introduces `FetchManifest`, a JSON
  sidecar (default: `<output>.manifest.json`) that records each URL's
  last-seen sitemap `<lastmod>`. On subsequent runs,
  `FetchManifest.should_skip(url, lastmod)` drops URLs whose
  upstream timestamp hasn't moved — sitemap is the gate, manifest is
  the memory. Honoured by every sitemap-driven discovery path.
- **FluidTopics-based Cortex XDR crawl.** `CortexXDRCrawler` now
  dispatches via `_crawl_via_fluidtopics` when a `fluidtopics` client
  is injected, walking the khub `/api/khub/maps` and
  `/api/khub/topics` endpoints to extract release-notes per agent
  version. The legacy shadow-DOM Playwright path remains as
  `_legacy_crawl` for offline-debug parity. Eliminates the
  Playwright launch on Cortex on CI runners and dev machines without
  a Chromium binary.
- **New `bugdb fetch` flags.**
  - `--manifest PATH` — explicit manifest file location (default:
    `<output>.manifest.json`).
  - `--no-manifest` — disable manifest read/write entirely; forces a
    full fetch of every URL even when sitemap timestamps match.
  - `--use-browser` — opt out of the httpx + FluidTopics path and use
    the legacy Playwright fetch for every product. Useful when the
    sitemap is unreachable or for debugging upstream parser changes
    that need a real browser.
- **`scripts/parity_check.py`** — compare two `bugdb.json` snapshots
  and fail when the new run regresses against the baseline. Defaults
  to exact parity (`--min-ratio 1.0`); supports per-product version
  counts and known/addressed issue counts. Used as a guard rail when
  switching from the Playwright path to the httpx + sitemap path.
- **`BaseCrawler._needs_browser()` hook.** Returns `True` iff the
  crawler will actually use Playwright. Default checks `self._transport
  is None`. `CortexXDRCrawler` overrides it to also return False when
  `self._fluidtopics` is set, so the FluidTopics path doesn't try to
  launch a browser that isn't needed (and on most CI runners, isn't
  installed).

### Changed
- **Shared httpx client across all products in one event loop.** The
  CLI dispatches every product crawl through `dispatch_async` inside
  a single `asyncio.run(_run_all())`, so one `HttpxDocsTransport` and
  one `FluidTopicsTransport` are constructed inside that loop and
  reused for every product. Previously each product spun up and tore
  down its own `asyncio.run`, orphaning the httpx connection pool
  between products and losing all of HTTP/2's connection-reuse value.
  Tests that mock `PRODUCT_WRAPPERS` via `patch.dict` still work — a
  frozen `_ORIGINAL_PRODUCT_WRAPPERS` snapshot lets `dispatch_async`
  detect a patched wrapper and route through `asyncio.to_thread`
  instead.
- **SaaS crawlers (AIRS, RBI, Cloud NGFW AWS+Azure, SLS) now
  discover URLs from the sitemap.** The previous hardcoded paths
  under `/cloud-ngfw/{aws,azure}/release-notes/` 301-redirect; the
  addressed-issues redirect lands on a "What's New" page with no bug
  table, so the legacy code was silently fetching the wrong content.
  Corrected prefixes (`/cloud-ngfw-aws/`, `/cloud-ngfw-azure/`) plus
  sitemap-first discovery via `discover_saas_urls` recovers the real
  pages.
- **GlobalProtect sitemap prefix narrowed to `/globalprotect/release-notes/`.**
  The sitemap lists both the canonical `/globalprotect/release-notes/...`
  pages (200 OK) and a stale parallel `/globalprotect/<v>/globalprotect-app-release-notes/...`
  layout (301-redirects). The old `/globalprotect/` prefix matched both
  forms, so a GlobalProtect fetch ate ~500 HTTP requests (200 OK
  responses plus ~300 redirects) instead of the ~92 it should — and
  the stale form redirected to the same canonical content anyway,
  contributing zero new data while inflating the `failed_fetches`
  retry queue when a redirect happened to 404.
- **Device Security switched to `/iot/release-notes/`** with
  year-based slug bucketing (`-in-YYYY`). The legacy
  `/iot/iot-security-release-notes` index 404s on the current docs
  site, so the previous crawl returned 0 versions. Sitemap-driven
  discovery now pairs known/addressed URLs per year, tolerating a
  year that has only one of them (no false failed-fetch).

### Fixed
- **PAN-OS sitemap landing-page double-counting.** Every PAN-OS minor
  version appears in the sitemap as three URLs: a landing page
  (`/.../pan-os-X-Y-Z-known-and-addressed-issues`) plus dedicated
  known-issues and addressed-issues subpages. `group_into_version_infos`
  was matching the issue-type keyword anywhere in the URL and adding
  the landing page to both the known and addressed bucket — which
  caused PAN-OS counts to look like `known == addressed` (inflated)
  while also wasting ~300 GETs per crawl re-fetching landing pages
  that have zero `<table>` elements. Fix classifies by the final URL
  segment, then drops the landing from a bucket when a specific
  sibling exists for the same version.
- **Prisma Access sitemap fallback.** Prisma Access URLs encode
  major.minor as a 2-digit path segment (`/prisma-access/release-notes/4-0/...`)
  — neither the dashed-triple nor the run-together regex in
  `extract_dotted_version` matched, so all 71 sitemap URLs were
  silently dropped. Added a last-resort `/(\d+)-(\d+)/` path-segment
  fallback that resolves `4-0` → `4.0.0` without false-positiving on
  run-together slugs like `aws-plugin-534` (still goes through the
  triple regex first). Recovers 9 versions, 752 known + 603 addressed
  issues.
- **Prisma Access Agent version discovery + consolidated addressed
  index.** Version is encoded inside the slug
  (`prisma-access-agent-26-2-1-known-issues`), not as a path segment,
  so the generic `_MAJOR_VERSION_RE` returned None. Override
  `discover_versions_from_sitemap` /
  `discover_version_pages_from_sitemap` to derive majors from
  `extract_dotted_version` output; new
  `_VERSION_TWO_DASHED_BEFORE_MARKER_RE` catches 2-dashed versions
  right before a known/addressed/fixed marker (`agent-26-2-known-issues`
  → `26.2.0`). Separately, the new docs layout consolidates ALL
  addressed-issues onto one `/prisma-access-agent-addressed-issues`
  index page with `<h2>`-grouped tables (one section per agent
  version) instead of per-version pages; new
  `_find_addressed_index_url` + `_parse_addressed_index_by_version`
  fetch it once and merge each `<h2>`/`<table>` pair into the
  matching version. Recovers 19 versions, 65 known + 31 addressed
  issues.
- **Panorama plugin version extraction + sitemap prefixes.**
  `extract_dotted_version` only handled the dashed `5-2-2` form; the
  Azure, Cisco ACI / TrustSec, GCP, and Kubernetes URL slugs use the
  run-together `522` form (`azure-plugin-522`). Added a fallback
  `(?<!\d)(\d)(\d)(\d)(?!\d)` regex that captures these without
  matching arbitrary 3-digit IDs. Separately, the sitemap prefixes
  for `plugin-vmware-nsx` (was `panorama-plugin-for-nsx`, real:
  `panorama-plugin-for-vmware-nsx`) and `plugin-ztp` (was
  `zero-touch-provisioning-ztp-plugin`, real:
  `panorama-plugin-for-zero-touch-provisioning`) were wrong, dropping
  most plugin URLs. End-to-end: 7 of 11 plugins went from 0 versions
  to fully populated (NSX 0 → 25 versions, Azure 0 → 20, vm-series
  18 → 65).
- **Sitemap-driven discovery now honours the manifest even when the
  discovery cache is fresh.** `BaseCrawler._resolve_version_infos`'s
  cache-hit path returned cached `VersionInfo` lists wholesale,
  bypassing the manifest's per-URL `lastmod` filter — so on a warm
  run, URLs that hadn't moved upstream were re-fetched anyway. Fixed
  by gating Path 2 (cache hit) on `self._sitemap is None`: when the
  sitemap is loaded, discovery always re-runs through
  `discover_version_pages_from_sitemap` (which is essentially free —
  parse the in-memory XML and apply the manifest filter), so
  incremental fetches actually skip unchanged URLs.
- **`BaseCrawler.__aexit__` no longer closes an injected Transport.**
  The CLI builds one `HttpxDocsTransport` and one `FluidTopicsTransport`
  for the whole run; closing them inside a per-product `__aexit__`
  broke every subsequent product fetched in the same run (the second
  product hit a closed `httpx.AsyncClient`). The transport's
  lifecycle is now owned by the caller; only the locally-launched
  Playwright instance is closed.

## [1.0.3] - 2026-04-11

### Added
- **Live per-version progress reporting on `bugdb fetch` and `bugdb build`.**
  A cold `bugdb fetch` takes 10-20 minutes and previously gave the
  user only a single spinner whose label bumped once per product —
  inside a product there was no signal at all, so any run over a
  minute looked indistinguishable from a hang. New `--progress /
  --no-progress` flag (default: auto-detect TTY) surfaces both which
  product and which version is currently in flight, plus a running
  `N/M` completion counter.
  - On a TTY: Rich live bar with spinner, description, bar, N/M
    counter, and elapsed time. Two levels: outer "Fetching N
    products" bar + inner per-product task updating on each
    version completion.
  - Piped stdout (CI, `| cat`): auto-degrades to one
    grep-friendly line per event.
  - `--no-progress`: suppresses all progress output.
  - Reusable `ProgressReporter` protocol in `src/bugdb/progress.py`
    with Rich, Plain, and Null implementations.
- **Streaming fetch log via `--log-file / -l`.** Writes a timestamped
  log of every fetch operation with a human-readable summary block
  at the end (totals, per-product breakdown with version lists,
  failed fetches with URLs and error messages).
  - `-l PATH`: explicit log path. `-l auto`: defaults to
    `<output>.log`. Omit to disable.
  - `bugdb build -l` forwards to the fetch stage; with
    `--skip-fetch` a "fetch stage skipped" marker is written.

### Changed
- **Retired `BaseCrawler._log()` and the `verbose` kwarg.** All
  crawler status messages now go through stdlib `logger` directly.
  The new `configure_fetch_logging()` context manager owns handler
  attachment for `--log-file` (file) and `--debug` (stderr).
  `--debug` now correctly emits from every `bugdb.*` logger to
  stderr (previously scoped to a single module). Progress bars are
  automatically disabled when `--debug` is active to avoid tearing.
- **Unified `assets/` working directory and `bugdb.json` filename.**
  Previously the CLI spread its artifacts across three locations:
  `assets/data.json` (fetched bug database),
  `src/bugdb/templates/assets/release-notes.json` (generated release
  notes, committed inside the Python package tree), and
  `dist/assets/` (built site). The mismatch made it unclear where
  end users were supposed to run `bugdb generate-release-notes`.
  v1.0.3 consolidates:
  - `bugdb fetch` default output: `assets/bugdb.json` (was
    `assets/data.json`)
  - `bugdb generate-release-notes` default output:
    `assets/release-notes.json` (was `src/bugdb/templates/assets/release-notes.json`)
  - `bugdb build-site-cmd` default input: `assets/bugdb.json`, and
    accepts a new `--release-notes` / `-r` flag defaulting to
    `<data_dir>/release-notes.json` with auto-discovery if the file
    exists
  - `bugdb build` default data: `assets/bugdb.json`, default release
    notes: `assets/release-notes.json`
  - Frontend fetches from `assets/bugdb.json` instead of
    `assets/data.json`
  - `SiteBuilder.build(database, release_notes_file=None)` takes an
    optional pre-generated release notes file and copies it into the
    output `<assets>/release-notes.json`. The file no longer lives in
    the template tree at all — `_copy_assets` now only ships static
    assets that don't change between builds (`app.js`, `tailwind.css`).
  - `src/bugdb/templates/assets/release-notes.json` has been removed
    from the repo; it's a build artifact regenerated by
    `bugdb generate-release-notes` on each build.
  - GitLab Pages deploy now explicitly runs
    `bugdb generate-release-notes -o assets/release-notes.json --force`
    before `build-site-cmd`, and rewrites the frontend fetch URL from
    `assets/bugdb.json` to the external CDN URL
    `https://repo.dependencyhell.net/bugdb/bugdb.json`.

  This is a **breaking change for any external script** that
  referenced `assets/data.json` — per project policy the build always
  uses the latest release, so there is no migration layer. Version is
  bumped accordingly.

- **CLI flag and Python API rename: `data` → `bugdb`.** Follow-up to
  the `data.json` → `bugdb.json` rename above, finishing the job so
  the CLI vocabulary, Python API, Pydantic schema, and test
  infrastructure all read consistently on `bugdb`.
  - `bugdb build-site-cmd` and `bugdb build` now accept `--bugdb` /
    `-b` instead of `--data` / `-d`. `bugdb build -d assets/bugdb.json`
    no longer works — use `bugdb build -b assets/bugdb.json`.
  - `bugdb validate`'s positional argument is renamed from `DATA_FILE`
    to `BUGDB_FILE` in `--help` output.
  - `python -m bugdb.baseline refresh|diff` argparse sub-CLI: `--data`
    renamed to `--bugdb`.
  - Python API: `site_builder.build_site(data_file=...)` renamed to
    `site_builder.build_site(bugdb_file=...)`. All internal callers
    updated.
  - **BREAKING: `FetchReport` schema.** The `FetchReport.data_file`
    Pydantic field is renamed to `FetchReport.bugdb_file`. Any
    `.report.json` file from a pre-rename run becomes incompatible
    and must be regenerated. No compatibility shim per project
    policy; since v1.0.3 has not actually released yet, no external
    consumers are affected.
  - Test infrastructure: `tests/integration/conftest.py` renames
    `DEFAULT_DATA_PATH` → `DEFAULT_BUGDB_PATH`, the `--data-path`
    pytest CLI option → `--bugdb-path`, and the `data_path` /
    `data_json` session fixtures → `bugdb_path` / `bugdb_json`. All
    integration test consumers updated.

### Security
- **Dropped Tailwind Play CDN; added Content Security Policy.** The
  previous `index.html` loaded `https://cdn.tailwindcss.com` without
  Subresource Integrity and compiled Tailwind at runtime via
  `'unsafe-eval'` — a supply-chain attack surface and a blocker for
  any meaningful CSP. This commit ships a pre-built 15 KB minified
  `tailwind.css` in `src/bugdb/templates/assets/` (tree-shaken from
  the HTML + JS templates via `tailwindcss@3.4.17`), removes the
  CDN script and the inline `tailwind.config = {...}` block from
  `index.html`, and adds a `<meta http-equiv="Content-Security-Policy">`
  tag with `default-src 'none'` plus explicit allowlists:
  `script-src 'self'; style-src 'self' 'unsafe-inline'; img-src
  'self' data:; font-src 'self'; connect-src 'self'; base-uri
  'none'; form-action 'none'`. Clickjacking protection via
  `frame-ancestors` is intentionally omitted from the meta-CSP
  because browsers ignore it there — that directive has to come
  from an HTTP header set by the deploy target (GitLab Pages
  already sends `X-Frame-Options: SAMEORIGIN`).
  - Verified in headless Chromium against the same adversarial
    data.json payload as the XSS commit below: zero CSP violations,
    zero alert dialogs, Tailwind styles correctly applied (card
    backgrounds, spacing, colors all computed as expected), and all
    modal click flows still work.
  - Rebuilding Tailwind (only needed when HTML/JS templates add or
    remove utility classes): `bash tools/rebuild-tailwind.sh`. The
    script requires Node.js at rebuild time but the generated CSS
    is committed, so `bugdb build` and the GitLab Pages deploy
    never touch Node.

- **XSS hardening in the static frontend.** The previous
  `src/bugdb/templates/assets/app.js` built card markup and modal
  content via template-literal string concatenation with inline
  `onclick=` handlers (`onclick="showKnownIssueModal('${escapeHtml(issue.bug_id)}', ...)"`),
  and its `escapeHtml` helper used the `div.textContent = x; return
  div.innerHTML` idiom which does NOT escape single or double quotes.
  A vendor-controlled `bug_id`, `productId`, or `version` containing
  `'` could break out of the JS string literal and execute arbitrary
  code in the user's browser. The chain was not exploitable in
  practice today (crawled fields match safe regexes) but the code
  was fundamentally unsafe and any regex relaxation would activate
  the vulnerability silently. Fixed by:
  - Rewriting `escapeHtml` with an explicit character map
    (`& < > " ' /`) so attribute-context callers have a safe fallback.
  - Wrapping all of `app.js` in an IIFE with `'use strict'` so no
    function leaks onto `window`.
  - Rebuilding `createIssueCard`, the shared fix/known-issue modal,
    and the release-notes modal with `createElement` + `textContent`
    + `addEventListener`. Every badge, button, description, and list
    row is now a real DOM node; zero `innerHTML` interpolation with
    vendor data anywhere on the render path.
  - Replacing the sole inline `onclick=` in `index.html` (on the
    `#release-notes-link` element) with an `addEventListener` wired
    up inside the IIFE. The `<a href="#">` also becomes a `<button
    type="button">` for semantic correctness.
  - Unifying `showFixModal` and `showKnownIssueModal` into a single
    `renderReleaseListModal` helper so the list-rendering fix lives
    in one place.
  - Replacing `getChangeTypeIcon`'s SVG string literals with a
    `createSvgIcon(pathD, className)` helper that builds nodes via
    `createElementNS`.
  - Consolidating two stacked `document` Escape handlers into a
    single delegated listener (was M1 in the review).
  - Adding `validateBugDatabase()` runtime validation of the
    fetched `data.json` payload before feeding it to the render
    pipeline (was H3) — logs a warning on unexpected content-type
    and throws early on malformed structure.
  - Replacing the `Array`-based `HIDDEN_VERSIONS` + five `.includes`
    call sites with a `Set` + `isHiddenVersion` helper (was H6).
  - Swapping `innerHTML` out of the init error path for
    `createElement` + `textContent` (was L3).
  - Batching issue-card rendering into a `DocumentFragment` to
    avoid per-card reflow on filter keystrokes (was M4).
  - Upgrading `loadReleaseNotes` error path from `console.log` to
    `console.warn` with the actual error (was M2).
  - Verified end-to-end in headless Chromium: an adversarial
    `data.json` with `bug_id = "PAN-EVIL',alert('xss'),'"`,
    `description = "<script>alert('xss')</script>"`, and
    `affected_components = ["Component <img src=x onerror=alert(1)>"]`
    fires zero alert dialogs and renders every field as visible
    text. All functional flows (Fix Available modal, Known Issue
    modal, Escape-to-close) continue to work.

  Note: this commit intentionally does NOT add a CSP meta tag yet —
  the Tailwind Play CDN (`cdn.tailwindcss.com`) compiles at runtime
  via `'unsafe-eval'`, which is incompatible with a strong CSP. CSP
  + Tailwind precompile will land as a follow-up commit.

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

[Unreleased]: https://gitlab.com/dependencyhell/bugdb/-/compare/v1.0.3...HEAD
[1.0.3]: https://gitlab.com/dependencyhell/bugdb/-/compare/v1.0.2...v1.0.3
[1.0.2]: https://gitlab.com/dependencyhell/bugdb/-/compare/v1.0.1...v1.0.2
[1.0.1]: https://gitlab.com/dependencyhell/bugdb/-/compare/v1.0.0...v1.0.1
[1.0.0]: https://gitlab.com/dependencyhell/bugdb/-/tags/v1.0.0
