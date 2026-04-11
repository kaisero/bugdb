# Roadmap

This file tracks work that has been explicitly scoped and deferred to a
future release. It is distinct from `docs/design-decisions.md` — that
log captures the **why** behind decisions already made; this file
captures **planned but not-yet-done** refactors, each with enough context
that a future contributor (human or AI) can pick it up without starting
from scratch.

Entries are grouped by target milestone. Items are added when a review
or design discussion identifies them; they're removed when the
corresponding commit lands and a CHANGELOG entry is written.

---

## v1.1.0 — Crawler architecture collapse

The 2026-04-11 v1.0.2 architecture review (see commits `a4e90d7`,
`6275e18`, and the parallel `python-best-practices` +
`architecture-designer` skill dispatches) identified a series of
related refactors that are individually valuable but collectively too
big for a single release. They're tracked here so the context survives.

The "one refactor to rule them all" recommendation from the review is
to **collapse the crawler hierarchy around a config-driven template
method**. Items D1, D2, and D5 below are the three pieces of that
refactor; they are most efficient done in order and in the same
release.

### D1 — Template method `crawl()` in BaseCrawler

**Problem.** The `crawl()` method in 15 product crawler files
(`src/bugdb/crawlers/products/{panos,globalprotect,prisma_*,...}.py`)
is ~40 lines of near-identical orchestration: normalise skip_versions,
log "Discovering available X versions...", loop major versions, call
`_crawl_versions_parallel`, retry failed fetches, sort, wrap in
`CrawlResult`. The only product-specific parts are the version
discovery logic and the log strings. ~600 lines of copy-paste across
15 files, and the recent 5-product identical SIM102 fix is a symptom —
when a concern is duplicated 15 times, fixing it once costs 15×.

**Refactor.** Push `crawl()` into `BaseCrawler` as a concrete template
method. Product subclasses implement only `discover_versions()` and
`discover_version_pages()` as hooks. The template method handles
skip-set, logging, sort, retry, and `CrawlResult` assembly.

**Effort:** ~2-3 days. Touches `base.py` plus all 15 product files.
Covered by existing mock crawler tests for 3/15 products; D3 widens
that to all 15 before the refactor lands.

### D2 — Generalise `PluginConfig` to `ProductConfig`

**Problem.** The `plugins.py` file already demonstrates that one
`PluginCrawler` class parameterised by a `PluginConfig` dataclass can
cover 11 products. The "simple" crawlers outside the plugins family
(prisma_access, prisma_access_agent, prisma_sdwan, cloud_ngfw_aws,
cloud_ngfw_azure, sdwan_plugin, the three `saas.py` classes) are still
implemented as 7+ standalone classes that differ only in URL template
strings and keyword lists.

**Refactor.** Generalise `PluginConfig` → `ProductConfig` with fields
for landing-URL templates (list, for the PAN-OS dual-URL pattern),
version-candidate list, link-keyword filters, source-string template.
Fold `PrismaAccessCrawler`, `PrismaSDWANCrawler`, `CloudNGFW*Crawler`,
`SDWANPluginCrawler`, and the three `saas.py` crawlers into a single
`GenericDiscoveryCrawler` driven by a config registry. Leave `panos`,
`globalprotect`, `cortex_xdr`, and `scm` as explicit subclasses where
discovery genuinely differs.

**Effort:** ~2-3 days, depends on D1 landing first.

### D3 — Test fixture coverage and MockPage status codes

**Problem.** Only 3 of 15 product crawlers (globalprotect, panos,
prisma-access-agent) have mock-based tests — `tests/conftest.py:115-172`
defines URL mappings only for those three. The other 12 are exercised
only via the data-baseline integration tier and the canary tier. A
regression in `cortex_xdr.py` (the most complex after panos) ships
through the fast `test` stage green.

Worse, `MockPage` returns fixture HTML for any substring-matched URL
and has no concept of HTTP status codes. Real 404s become parseable
"not found" pages only if the fixture explicitly contains a 404 title.
This is *exactly* what masked the PAN-OS 12.1 URL-pattern bug in
v1.0.1 — the mock served the same fixture for both URL patterns, so
the probe logic couldn't be exercised.

**Refactor.** Two parts.

(a) Promote `MockPage` to return None/raise for unmapped URLs by
default, with an explicit opt-in allowlist. Add a `MockResponse`
concept with a `status_code` field so `_probe_landing_url` can
exercise real 404 semantics.

(b) Make fixture authoring cheap: add a `tools/snapshot_fixture.py`
dev command that takes a real URL and writes a fixture file with
provenance metadata. Pair with a pytest parametrised "smoke" test per
product that asserts `discover_versions()` returns non-empty against a
minimal fixture set for all 15 products.

**Effort:** ~1 day for (a), ~2-3 days for (b). Can land independently
of D1/D2.

### D4 — Split `BaseCrawler` into PageFetcher / IssueParser / CrawlOrchestrator

**Problem.** `BaseCrawler` is a 1005-line god class that owns three
distinct concerns: browser lifecycle (`__aenter__`/`__aexit__`,
`_new_page`, `_fetch_page_with_semaphore`, `_fetch_cortex_page_*`,
`_trigger_global_backoff`), parsing (`_parse_issues_page`,
`_parse_issues_table`, `_parse_issues_table_with_feature`,
`_parse_topic_format_issues`), and orchestration (`_crawl_version`,
`_crawl_versions_parallel`, `_retry_failed_fetches_sequentially`). The
three concerns have different test needs: fetching needs Playwright
mocks, parsing needs raw HTML fixtures, orchestration needs both.
Today you cannot unit-test the table parser without also instantiating
the Playwright stack — which is why the PAN-OS 12.1 parser could not
be unit-tested in isolation.

**Refactor.** Split `BaseCrawler` into three collaborators:
- `PageFetcher` — browser lifecycle, semaphore, retries, backoff
  (~400 lines)
- `IssueParser` — stateless module taking `BeautifulSoup` and
  returning `list[Issue]` (~400 lines)
- `CrawlOrchestrator` — template method from D1, holds a `PageFetcher`
  and an `IssueParser` (~200 lines)

Product subclasses become `ProductConfig` data plus optional hooks.
The parser becomes testable with raw HTML strings and no async
machinery.

**Effort:** ~3-4 days, high architectural leverage. Do after D1 and D2
stabilise, because those make the subclass responsibilities small
enough that the remaining god-class structure becomes obviously wrong
and easy to break apart.

### D5 — Plugin-style scaffold and auto-import for new products

**Problem.** Adding a new product crawler today touches **9 files**:
`products/foo.py`, `products/__init__.py`, `registry.py` (3
edits: PRODUCT_CRAWLERS, PRODUCT_WRAPPERS, the `_crawl_foo_async` +
`crawl_foo` wrappers), `crawlers/__init__.py`, `tests/conftest.py`,
`tests/fixtures/foo/`, and `tests/crawler/test_crawler.py`. Six of
those edits are boilerplate the computer could derive from one
declaration. The manual wiring is the substrate where the PAN-OS 12.1
fixture-masking bug lived.

**Refactor.** After D1-D2 land, adding a product should be:

1. Create `crawlers/products/foo.py` with one class declaring
   `product_id`, `product_name`, `source_template`, and either a
   `ProductConfig` or custom `discover_*` hooks.
2. Register via a class decorator `@register_crawler` that populates
   `PRODUCT_CRAWLERS` on import.
3. Auto-import products via `pkgutil.walk_packages(products.__path__)`
   in `products/__init__.py`.
4. Ship a `bugdb scaffold-crawler <id>` dev command that writes the
   skeleton file plus a fixture directory stub.
5. Collapse `registry.py`'s 20 hand-written `_crawl_*_async` and
   `crawl_*` sync wrappers into a single `make_sync_wrapper(product_id)`
   factory that reads the class from `PRODUCT_CRAWLERS`. Target: ~839
   lines → ~150.

`tests/unit/test_registry.py` (landed in v1.0.2) already pins the
invariant that `PRODUCT_CRAWLERS.keys() == PRODUCT_WRAPPERS.keys()`;
the auto-import scaffold just needs to preserve that.

Also: delete `src/bugdb/crawler.py` (the backward-compat shim that
v1.0.2 collapsed to a pure re-export) or gate its removal on a major
version bump.

**Effort:** ~1 day, depends on D1 and D2.

### D6 — Merge recovered issues back into ProductVersion after retry

**Problem.** `BaseCrawler._retry_failed_fetches_sequentially` returns
`(recovered_issues, still_failed)` but every one of the 15 product
crawler call sites assigns `_recovered, still_failed = ...` and
discards the `_recovered` list. If a retry actually recovers issues
(which it can, now that v1.0.2's `a4e90d7` fixed `_parse_issues_page`
to propagate errors), those issues are silently thrown away.

**Refactor.** Change the retry method to take `product_versions` as a
mutable parameter and merge recovered issues back into the matching
`ProductVersion` entries in place, keyed by `(version, issue_type)`.
Every caller loses the `_recovered` unpack. This requires threading
`product_versions` through the retry call site in each product
crawler's `crawl()` method — which is exactly the 15 call sites that
D1 is going to rewrite. The cleanest move is to land D6 as part of
D1, so the template-method implementation gets the recovered-issue
merge correct from the start.

**Effort:** trivial if folded into D1; ~1 day standalone.

---

## Pre-existing test fragility (not blocking anything)

Two unit tests in `tests/unit/test_cli.py` fail in the devcontainer
because Rich wraps long tmpdir paths across newlines, splitting the
asserted substrings `"not found"` and `"already exists"` across two
lines:

- `TestGenerateSample::test_generate_sample_refuses_overwrite_without_force`
- `TestFetchWithRetry::test_retry_missing_data_file`

Both were pre-existing before v1.0.2 (they fail against `main` without
any of this release's changes). Not tracked as a roadmap item — fix
when someone hits it in anger, by either widening the CliRunner
terminal width or loosening the substring assertion.
