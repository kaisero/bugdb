# Design Decisions

This file is a lightweight ADR (Architecture Decision Record) log. It captures
the **why** behind non-obvious design, architecture, and tooling decisions so
a future contributor can understand the reasoning without archaeology through
git history.

Each entry follows the same shape:

```
## YYYY-MM-DD — Title

**Context:** What forced the decision — the problem, the constraint, the
stakeholder ask.

**Decision:** The choice that was made. Short and concrete.

**Consequences:** Trade-offs accepted, follow-on work implied, known limits.
```

Entries are append-only; update an existing entry only when the decision
itself is revised (and note the revision inline). Deprecated decisions stay
in the log but are annotated.

---

## 2026-04-11 — Discovery cache at `.cache/bugdb/` with 24-hour TTL

**Context:** A full `bugdb fetch` took 10-20 minutes end-to-end and hit
upstream rate limiting on docs.paloaltonetworks.com when parallelism was
raised. Static code analysis showed the bulk of requests were **repeat
work** — every invocation re-probed URL patterns and re-discovered
version lists from scratch, even in incremental mode where the user was
only looking for new minor versions. Roughly:

- ~60 URL-pattern probes per run across 5 crawlers (PAN-OS has 10
  candidates × 2 templates = 20 probes by itself)
- ~125-210 discovery fetches per warm incremental run (per-major index
  pages that rarely change)
- ~55 wasted fetches of hub pages that turned out to be link-only
  indexes with no issue tables

More concurrency was not an option — we were already at the upstream
rate-limit ceiling. The only way forward was **fewer requests**.

**Decision:** Persist two kinds of discovery state to a single JSON
file at `.cache/bugdb/discovery.json` (repo-root-relative, gitignored).
Schema:

- `url_patterns: {major: url}` per product — winning URL templates
  resolved by the PAN-OS dual-probe flow, so warm runs skip probing
  entirely.
- `version_infos: {major: [VersionInfo, ...]}` per product — cached
  output of `discover_version_pages`, so warm incremental runs skip
  the whole discovery phase (probing + per-major index fetches).

Single **global 24-hour TTL** per product entry. Fresh entries short-
circuit discovery; stale entries fall through to a fresh probe and are
overwritten on success. No per-field TTL — simpler to reason about,
and the upstream-canary tier already runs nightly so staleness is
bounded regardless.

Writes are atomic via `.tmp` + `os.replace` so a SIGKILL mid-save
can't corrupt the file. Corrupt or schema-mismatched caches are logged
and discarded; there is no migration path for schema v1.

The CLI exposes `--refresh-discovery` / `-R` to force cache bypass
after upstream docs reorganisations or during debugging.

**Consequences:**

- **In-repo, not `~/.cache/bugdb/`.** Project-scoped cache, easy to
  clear (`rm -rf .cache/`), easier to inspect during development. The
  trade-off is that re-clones start cold and CI runners need the path
  added to `.gitlab-ci.yml` cache paths if we ever want warm CI runs.
  For now the benefit is local-only which is where fetches happen.
- **24h TTL matches canary cadence.** A newly-shipped upstream major
  will be missed for up to 24h by the crawler, but the canary test
  tier that exists to detect this runs nightly — so the drift window
  is already bounded at 24h whether we cache discovery or not.
- **Shared cache instance per run.** The CLI instantiates one
  DiscoveryCache and threads it through every crawler wrapper in
  `registry.py`. One file-read at startup, one write at the end.
- **Schema is versioned.** If the cache shape ever needs to evolve,
  bumping `SCHEMA_VERSION` in `discovery_cache.py` invalidates all
  existing caches cleanly — readers log a warning and start fresh.
- **Five crawlers benefit today.** panos, globalprotect,
  prisma_access, prisma_access_agent, prisma_sdwan all use
  `BaseCrawler._resolve_version_infos` in their `crawl()` methods.
  sdwan_plugin, cortex_xdr, adem, scm, device_security, and the
  three saas.py crawlers use different discovery models and are
  excluded from this round. plugins.py could benefit but is entangled
  with the roadmap D1 template-method refactor — deferred to v1.1.0.

---

## 2026-04-11 — Ruff as the single linter and formatter

**Context:** The project had no enforced code style. Contributor diffs
mixed tab/space drift, inconsistent import ordering, and `Optional[X]` /
`X | None` spread randomly across the 19 files that had type hints. The
standard Python approach (black + flake8 + isort + pyupgrade + pydocstyle)
requires reconciling four tool configs that routinely disagree, and CI
cycles multiply.

**Decision:** Adopt [ruff](https://github.com/astral-sh/ruff) as the single
linter and formatter. Start with a conservative rule set
(`E, W, F, I, B, UP, SIM, RUF`) — enough to catch the important things
without triggering a multi-hundred-line rewrite on day one. Line length
100 (pragmatic middle ground between black's 88 and the 120 that long
assertion messages drift toward). Enforced two ways:

1. **Local pre-commit hook** (`.pre-commit-config.yaml`) runs
   `ruff check --fix` and `ruff format` on every commit.
2. **GitLab CI `lint` job** runs `ruff check` (with GitLab codequality
   output) and `ruff format --check` on every develop commit and MR.

The pre-commit hook `rev` must stay pinned to the same ruff version that
`[dependency-groups] dev` pins. Version drift between the two is the #1
pre-commit footgun and would cause "passes locally, fails in CI"
confusion.

**Consequences:** One tool, one config block in `pyproject.toml`, one
process to learn. First-pass auto-fix produces a medium mechanical diff
(~250–380 lines) that's landed in a dedicated commit recorded in
`.git-blame-ignore-revs` so `git blame` skips over it. Future rule
expansion is one line in `[tool.ruff.lint] select`. The `dev` group is
separate from `test` so CI's fast tier doesn't install lint tools it
doesn't need, and the lint job doesn't install Playwright (~30s saved
per pipeline).

## 2026-03-31 — Use uv for package and Python-version management

**Context:** The project started with pip + venv, which left the CI pipeline
repeatedly rebuilding environments from loose `pip install` calls with no
lockfile. Pre-release bugs were hard to reproduce because contributors
and CI had subtly different dependency trees. Python version was not
pinned.

**Decision:** Adopt [uv](https://github.com/astral-sh/uv) as the single tool
for dependency resolution, lockfile management, Python interpreter pinning,
and script execution. `pyproject.toml` uses `[dependency-groups]` (uv-native)
rather than `[project.optional-dependencies]`. `uv.lock` is committed.
`.python-version` pins the interpreter. CI uses the
`ghcr.io/astral-sh/uv:python3.12-bookworm-slim` image and `uv sync --locked`
for reproducible installs.

**Consequences:** Contributors must install uv (one-line curl). Lockfile
regeneration is authoritative — never hand-edit `uv.lock`. Fast, reproducible
envs across dev, CI, and release. The `[dependency-groups]` syntax is
newer than `[project.optional-dependencies]` and requires tooling that
understands it (hatchling, uv — both do).

## 2026-04-11 — PAN-OS crawler probes both NGFW and legacy URL patterns

**Context:** Palo Alto migrated PAN-OS 12.1+ release notes from the legacy
`/pan-os/<v>/pan-os-release-notes` tree to a new `/ngfw/release-notes/<v>`
tree. The crawler's hard-coded URL pattern only knew the legacy path, so
PAN-OS 12.1.x was silently dropped from every fetch. The mock fixture
mapping in `tests/conftest.py` had been mapping **both** URL patterns to
the same fixture, which masked the bug in unit tests.

**Decision:** `PANOSCrawler` now probes both URL templates per major version
and caches the first one that resolves (`_base_url_for_version[major]`).
The mock fixture mapping for the legacy 12.1 URL was removed, and a
regression test
(`tests/crawler/test_crawler.py::test_panos_12_1_only_discoverable_via_ngfw_url`)
pins the correct behaviour so the stale mapping cannot be re-introduced.

**Consequences:** One extra network probe per major version on cold start
(~15 requests for the current candidate list — negligible). Adding a future
URL pattern change is a 3-line edit to `_NGFW_BASE` / `_LEGACY_BASE` /
`_resolve_landing_url`. The probe swallows `Exception` intentionally so a
404 on a candidate path doesn't crash the crawl — this is the one place
in the codebase where a broad except is the correct pattern, and ruff's
`BLE001` is **not** enabled so it won't get flagged.

## 2026-04-11 — Baseline snapshot format v1 (hand-rolled JSON fingerprint)

**Context:** We need the integration test tier to detect regressions in
`assets/data.json` — specifically: every previously-fetched product, version,
known-issue count, addressed-issue count, and bug_id must still be present
after subsequent crawls. Third-party snapshot libraries (pytest-snapshot,
syrupy) are either too strict (byte-for-byte, fails on any whitespace drift)
or too opaque for our "monotonically non-decreasing" semantics.

**Decision:** Roll a minimal snapshot format in `src/bugdb/baseline.py` with
explicit dataclasses — `VersionFingerprint` (known count, addressed count,
sorted bug_id tuple), `ProductFingerprint`, `BaselineSnapshot`, `Baseline`.
The snapshot is serialized as JSON with a `schema_version` field
(currently `1`) so format evolution is explicit. A `python -m bugdb.baseline
refresh|diff` CLI handles build/compare. Refresh is **never** automatic —
it requires an explicit CLI invocation or `BUGDB_REFRESH_BASELINE` env var
so a failing test cannot "fix" itself by overwriting the baseline.

**Consequences:** ~650 KB committed JSON fingerprint (26 products, 473
versions, ~24k bug_ids). Diffs are readable in PR reviews because the
format is stable and sorted. A schema change requires a version bump and
a migration path — documented in `baseline.py` docstrings.

## 2026-04-11 — Three-tier CI pipeline gated by pytest markers and GitLab `rules`

**Context:** We have three very different test tiers with conflicting
runtime and failure-mode requirements:
1. **Fast unit / mock-crawler tests** — must run on every develop commit,
   <2 minutes, zero network.
2. **Data-fidelity integration** — loads 13 MB `data.json` once, parametrises
   ~1900 assertions per (product, version) pair. Too heavy for every commit
   but must run when data or baseline changes.
3. **Upstream-version canary** — probes `docs.paloaltonetworks.com` directly
   to catch new major versions (the PAN-OS 12.1 bug class). Must not block
   MRs on upstream network flakes.

**Decision:** Three separate pytest markers (`data_baseline`, `canary`,
unused `slow` reserved) + `--strict-markers` to prevent typos. Default
`addopts = "--strict-markers -m 'not data_baseline and not canary'"`
excludes heavy tiers unless explicitly opted in. GitLab CI has three jobs:
- `test` (fast): every develop commit.
- `data-baseline-integration`: nightly schedule + web-manual + MRs that
  touch `assets/data.json`, `tests/baselines/**`, `tests/integration/**`,
  or `src/bugdb/baseline.py`.
- `upstream-canary`: nightly schedule + web-manual only. `allow_failure: true`
  so network flakes don't page oncall.

**Consequences:** One piece of configuration (markers + addopts) governs
both local `pytest` ergonomics and CI layout. The `rules.changes` list for
`data-baseline-integration` must be kept in sync when new data-touching
files are added. The canary tier tolerates network failures at the
individual test level (probes retry with backoff, distinguish 404 from
network error, skip on mutual network failure).

## 2026-04-11 — `--strict-markers` and default-exclude heavy tests

**Context:** Earlier in the project, test tiers were distinguished only by
path (`tests/integration/`) and contributors accidentally ran the heavy
13 MB baseline comparison on every local `pytest` invocation, then got
frustrated and started passing `tests/unit/` explicitly. Typo'd markers
silently did nothing.

**Decision:** `[tool.pytest.ini_options]` uses `--strict-markers` so
unknown markers are a hard error, and `addopts` defaults to
`-m 'not data_baseline and not canary'` so `uv run pytest` Just Works
without remembering to exclude anything.

**Consequences:** Any new heavy test tier needs a new marker registered in
`[tool.pytest.ini_options].markers` AND added to the default exclude
expression. The trade-off is a tiny bit of boilerplate per tier in exchange
for a one-command local test loop.
