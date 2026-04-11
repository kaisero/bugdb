# Test Baselines

This directory holds committed JSON snapshots used by the
`tests/integration/` tier to detect regressions in fetched crawler data.

## What is a baseline?

A compressed fingerprint of `assets/bugdb.json` at a point in time. For every
`(product, version)` it records:

- `known` — number of known issues
- `addressed` — number of addressed issues
- `bug_ids` — sorted list of bug identifiers

Only these fields. The baseline is **not** a copy of `bugdb.json`.

## What it guarantees

The integration tests read the baseline and assert, against the current
`assets/bugdb.json`:

1. Every product in the baseline is still present.
2. Every `(product, version)` in the baseline is still present.
3. `current.known_count >= baseline.known_count` for every version.
4. `current.addressed_count >= baseline.addressed_count` for every version.
5. `baseline.bug_ids ⊆ current.bug_ids` for every version.

In short: **fetched data never silently loses ground.** A crawler refactor
that drops issues will fail the integration pipeline loudly.

## What it does NOT guarantee

- That a newly released upstream major version is being crawled.
  (See `tests/canary/` for that — the nightly upstream-version canary.)
- That the contents of individual issue descriptions are unchanged.
  (Palo Alto routinely edits descriptions. We'd drown in false positives.)

## How to refresh

Refreshing is always an **explicit human action**. It never happens
automatically and never happens in CI without manual intervention.

### Quick refresh (env var)

```bash
BUGDB_REFRESH_BASELINE=1 uv run pytest tests/integration/ -m data_baseline
```

This rewrites `data_baseline.json` from the current `assets/bugdb.json`,
then fails the test session with a clear banner telling you to review the
diff and commit it.

### Reviewable refresh (CLI, recommended for large changes)

```bash
uv run python -m bugdb.baseline refresh --bugdb assets/bugdb.json --baseline tests/baselines/data_baseline.json
```

Prints a human-readable diff (products/versions added or removed, count
deltas) and writes the new file only if you pass `--yes`.

### When to refresh

| Situation | Refresh? |
|---|---|
| Crawler fixed a parser bug and now extracts more issues | Yes — counts go up, baseline updates |
| Palo Alto shipped a new minor version | Yes, after fetching it |
| Crawler refactor that drops issues | **No** — investigate the loss first |
| Palo Alto retroactively removed an issue (rare) | Yes, with justification in the commit message |
| Unrelated code change | No — baseline should be untouched |

## PR checklist

Any PR that changes:

- `src/bugdb/crawlers/**`
- `src/bugdb/models.py`
- `src/bugdb/release_notes.py`
- the bug-id regex or schema

must include a regenerated baseline in the same PR, with the reason in the
commit message.
