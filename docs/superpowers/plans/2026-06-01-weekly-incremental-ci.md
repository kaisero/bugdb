# Weekly incremental CI fetch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run `bugdb fetch --incremental` automatically once a week from GitLab CI, commit the refreshed `assets/bugdb.json` + `assets/bugdb.manifest.json` back to the `develop` branch, and let the existing Pages deploy stage publish the result. Drop the Playwright/Chromium install entirely.

**Architecture:** A new scheduled GitLab pipeline (`incremental-fetch`) runs on `develop` every Sunday. It reuses the new `httpx + sitemap + manifest` fetch path so each weekly run does O(changed-pages) work. A separate scheduled job (`full-fetch`) runs monthly to absorb any sitemap-`<lastmod>` lies. Pages deploy and the existing test job are unchanged.

**Tech Stack:** GitLab CI YAML, `python:3.12-slim` image, `gh`/`git` for committing back, GitLab Schedules UI for cron triggers, GitLab Project Access Token (write to `assets/bugdb*.json` only) for the push-back step.

**Out of scope:** Migrating CI to GitHub Actions. Reorganising the existing `pages` job. Removing `playwright` from `pyproject.toml` (defer until two clean weekly runs).

**Prerequisites — must be true before merging the changes in this plan:**
1. The `feat/sitemap-httpx-fetch` branch is merged into `develop`.
2. The parity check (`scripts/parity_check.py`) has passed at least once between the legacy fetch output and the new fetch output.
3. A `BUGDB_BOT_TOKEN` Project Access Token exists in GitLab with scope `write_repository` and write access limited via branch rules to the `develop` branch.

---

## File Structure

**Create:**
- `.gitlab/ci/incremental-fetch.yml` — the new scheduled job (included from `.gitlab-ci.yml`).
- `.gitlab/ci/full-fetch.yml` — the monthly belt-and-braces job.
- `docs/operations/scheduled-fetch.md` — short ops guide (how to trigger manually, how to recover from corrupted manifest, how to rotate the token).

**Modify:**
- `.gitlab-ci.yml` — include the two new files; remove `playwright install` from the `test` job once the legacy `--use-browser` path is no longer needed for tests.
- `README.md` — short section pointing operators at `docs/operations/scheduled-fetch.md`.

**Delete (deferred to follow-up PR after two clean weekly runs):**
- `playwright` from `pyproject.toml` runtime deps.
- `_legacy_crawl` from `cortex_xdr.py`.
- `_fetch_via_browser` from `base.py`.
- The probe-based `discover_versions` methods on each product crawler.

---

## Phase 1 — One-time setup outside CI

### Task 1: Create the Project Access Token

- [ ] **Step 1: In GitLab project Settings → Access Tokens, create `BUGDB_BOT_TOKEN`**

Use these exact settings:
- Name: `bugdb-weekly-fetch`
- Scopes: `write_repository`
- Expiry: 1 year (set a calendar reminder to rotate)
- Role: Developer
- Branch protection: under Settings → Repository → Protected branches, allow `Developer` role to push to `develop` (or, if `develop` is fully protected, configure a CODEOWNERS exemption for paths `assets/bugdb*.json`).

- [ ] **Step 2: Add the token as a masked CI variable**

In Settings → CI/CD → Variables:
- Key: `BUGDB_BOT_TOKEN`
- Value: the token from Step 1
- Type: Variable
- Protect variable: **No** (the scheduled pipeline doesn't run on a protected ref by default; if you protect `develop`, mark this `Yes` and also protect the schedule)
- Mask variable: **Yes**
- Expand variable reference: No

---

### Task 2: Define the GitLab Schedules

- [ ] **Step 1: Schedule the weekly incremental run**

Settings → CI/CD → Schedules → New schedule:
- Description: `Weekly incremental bugdb fetch`
- Interval pattern: `15 6 * * 0` (Sundays at 06:15 UTC)
- Cron timezone: UTC
- Target branch: `develop`
- Variables:
  - `BUGDB_JOB`: `incremental`

- [ ] **Step 2: Schedule the monthly full run**

Settings → CI/CD → Schedules → New schedule:
- Description: `Monthly full bugdb fetch (parity)`
- Interval pattern: `15 7 1 * *` (1st of month at 07:15 UTC)
- Target branch: `develop`
- Variables:
  - `BUGDB_JOB`: `full`

---

## Phase 2 — CI YAML changes

### Task 3: New `.gitlab/ci/incremental-fetch.yml`

**Files:**
- Create: `.gitlab/ci/incremental-fetch.yml`

- [ ] **Step 1: Write the job**

```yaml
# .gitlab/ci/incremental-fetch.yml
incremental-fetch:
  stage: data-refresh
  image: python:3.12-slim
  variables:
    PIP_DISABLE_PIP_VERSION_CHECK: "1"
    PIP_NO_CACHE_DIR: "1"
    GIT_DEPTH: "5"
  before_script:
    - apt-get update -qq && apt-get install -qq -y --no-install-recommends git ca-certificates
    - pip install -e .
    - git config user.email "bugdb-bot@dependencyhell.net"
    - git config user.name  "bugdb-bot"
  script:
    - mkdir -p assets
    - bugdb fetch
        -o assets/bugdb.json
        --incremental
        --manifest assets/bugdb.manifest.json
        --no-progress
        -l assets/bugdb.log
    - |
      if git diff --quiet -- assets/bugdb.json assets/bugdb.manifest.json; then
        echo "[i] No data changes; skipping commit."
        exit 0
      fi
    - git add assets/bugdb.json assets/bugdb.manifest.json
    - git commit -m "chore(data): weekly incremental refresh [skip ci]"
    - git push "https://oauth2:${BUGDB_BOT_TOKEN}@${CI_SERVER_HOST}/${CI_PROJECT_PATH}.git" "HEAD:${CI_COMMIT_REF_NAME}"
  artifacts:
    when: always
    paths:
      - assets/bugdb.log
      - assets/bugdb.json
      - assets/bugdb.manifest.json
    expire_in: 30 days
  rules:
    - if: '$CI_PIPELINE_SOURCE == "schedule" && $BUGDB_JOB == "incremental"'
```

- [ ] **Step 2: Verify the `script` block makes minimal HTTP traffic**

Pre-flight: run locally first. On a freshly-cloned checkout with an
existing `assets/bugdb.manifest.json` whose entries match the current
sitemap, `bugdb fetch --incremental --manifest assets/bugdb.manifest.json
--no-progress` must take less than 90 s and produce no diff. Confirm:

```bash
time uv run bugdb fetch --incremental \
  -o assets/bugdb.json \
  --manifest assets/bugdb.manifest.json \
  --no-progress -l assets/bugdb.log
git diff --stat assets/
```

Expected: under 90 s wall time, empty `git diff`.

- [ ] **Step 3: Commit**

```bash
git add .gitlab/ci/incremental-fetch.yml
git commit -m "ci: add weekly incremental fetch job"
```

---

### Task 4: New `.gitlab/ci/full-fetch.yml`

**Files:**
- Create: `.gitlab/ci/full-fetch.yml`

- [ ] **Step 1: Write the job (mirrors incremental but `-f`, no `--incremental`)**

```yaml
# .gitlab/ci/full-fetch.yml
full-fetch:
  stage: data-refresh
  image: python:3.12-slim
  variables:
    PIP_DISABLE_PIP_VERSION_CHECK: "1"
    PIP_NO_CACHE_DIR: "1"
    GIT_DEPTH: "5"
  before_script:
    - apt-get update -qq && apt-get install -qq -y --no-install-recommends git ca-certificates
    - pip install -e .
    - git config user.email "bugdb-bot@dependencyhell.net"
    - git config user.name  "bugdb-bot"
  script:
    - mkdir -p assets
    # Full refresh discards the manifest by passing --no-manifest then rewrites it.
    - bugdb fetch
        -o assets/bugdb.json
        --force
        --no-manifest
        --no-progress
        -l assets/bugdb.log
    # Now do a second pass with --incremental so the manifest is consistent
    # with the new bugdb.json (no-ops on URLs, just rebuilds the manifest).
    - bugdb fetch
        -o assets/bugdb.json
        --incremental
        --manifest assets/bugdb.manifest.json
        --no-progress
        -l assets/bugdb.log
    - |
      if git diff --quiet -- assets/bugdb.json assets/bugdb.manifest.json; then
        echo "[i] No data changes; skipping commit."
        exit 0
      fi
    - git add assets/bugdb.json assets/bugdb.manifest.json
    - git commit -m "chore(data): monthly full refresh [skip ci]"
    - git push "https://oauth2:${BUGDB_BOT_TOKEN}@${CI_SERVER_HOST}/${CI_PROJECT_PATH}.git" "HEAD:${CI_COMMIT_REF_NAME}"
  artifacts:
    when: always
    paths:
      - assets/bugdb.log
      - assets/bugdb.json
      - assets/bugdb.manifest.json
    expire_in: 90 days
  rules:
    - if: '$CI_PIPELINE_SOURCE == "schedule" && $BUGDB_JOB == "full"'
```

- [ ] **Step 2: Commit**

```bash
git add .gitlab/ci/full-fetch.yml
git commit -m "ci: add monthly full fetch job (parity belt-and-braces)"
```

---

### Task 5: Wire the new files into `.gitlab-ci.yml`

**Files:**
- Modify: `.gitlab-ci.yml`

- [ ] **Step 1: Read current `.gitlab-ci.yml`**

```bash
cat .gitlab-ci.yml
```

Expected: the file currently has `test:` and `pages:` jobs, no `stages:`
block, no `include:` block.

- [ ] **Step 2: Replace `.gitlab-ci.yml` with the new version**

```yaml
# .gitlab-ci.yml
image: python:3.12-slim

stages:
  - test
  - data-refresh
  - deploy

include:
  - local: .gitlab/ci/incremental-fetch.yml
  - local: .gitlab/ci/full-fetch.yml

test:
  stage: test
  script:
    - pip install ".[test]"
    # Playwright install kept only while the legacy --use-browser path
    # remains in the codebase. Remove once _legacy_crawl + _fetch_via_browser
    # are deleted.
    - playwright install --with-deps chromium
    - pytest --junitxml=report.xml -v
  artifacts:
    when: always
    reports:
      junit: report.xml
  rules:
    - if: $CI_COMMIT_BRANCH == "develop"
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'

pages:
  stage: deploy
  script:
    - pip install .
    - bugdb generate-sample
    - bugdb generate-release-notes
    - bugdb build-site-cmd -o public
    # Replace local data.json path with external URL
    - sed -i "s|fetch('assets/data.json')|fetch('https://dependencyhell.net/bugdb/data.json')|g" public/assets/app.js
    # Remove local data.json since we're using external
    - rm -f public/assets/data.json
  artifacts:
    paths:
      - public
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

- [ ] **Step 3: Validate locally with `gitlab-ci-lint` (if available) or just push and let GitLab validate**

```bash
# Optional but recommended:
gitlab-ci-lint .gitlab-ci.yml || true
```

- [ ] **Step 4: Commit**

```bash
git add .gitlab-ci.yml
git commit -m "ci: include data-refresh stage + jobs"
```

---

## Phase 3 — Smoke testing the pipeline before going live

### Task 6: Trigger a manual run of the incremental job

GitLab schedules can be played on demand from the Schedules page. Use it:

- [ ] **Step 1: Push the branch to GitLab**

```bash
git push origin feat/sitemap-httpx-fetch
```

- [ ] **Step 2: Create a one-off schedule pointing at the branch**

Settings → CI/CD → Schedules → New schedule:
- Description: `[temp] smoke-test incremental fetch`
- Interval pattern: `0 0 1 1 *` (won't actually fire — we manually play it)
- Target branch: `feat/sitemap-httpx-fetch`
- Variables:
  - `BUGDB_JOB`: `incremental`

- [ ] **Step 3: Click "Play"**

The job runs. Watch the logs.

Expected outcomes:
1. `bugdb fetch --incremental` exits 0 in under 90 s.
2. `git diff --quiet` either succeeds (no changes) or fails (changes found, then `git commit` + `git push` runs).
3. If the push runs, the merge-request UI on the branch shows a new commit
   from `bugdb-bot` touching only `assets/bugdb.json` and
   `assets/bugdb.manifest.json`.

Common failures and fixes:

| Symptom | Cause | Fix |
|---|---|---|
| HTTP 401 on `git push` | `BUGDB_BOT_TOKEN` missing or wrong scope | Recreate token with `write_repository`, update CI variable |
| HTTP 403 on `git push` | Branch protection rejects the bot's role | Add CODEOWNERS exemption for `assets/bugdb*.json`, or lower the protection level on `develop` for `Developer` role |
| `bugdb fetch` takes >5 min | Manifest is empty (first run) | Expected on the first run only. Subsequent runs use the manifest |
| Push triggers an infinite pipeline loop | `[skip ci]` not honored | Confirm the commit message contains the exact literal `[skip ci]` (case-sensitive on GitLab) |

- [ ] **Step 4: Delete the temporary smoke schedule**

Once you've seen one successful push from the branch, remove the
`[temp]` schedule so it can't fire again accidentally.

---

### Task 7: Verify the produced data still passes the parity check

- [ ] **Step 1: Pull the bot's commit locally**

```bash
git fetch origin feat/sitemap-httpx-fetch
git checkout feat/sitemap-httpx-fetch
git pull --ff-only
```

- [ ] **Step 2: Run the parity check against the pre-CI baseline**

```bash
uv run python scripts/parity_check.py \
  docs/superpowers/proof/baseline-bugdb.json \
  assets/bugdb.json --show-missing-ids
```

Expected: `[ok] new ≥ 100% of old for every (product,version)`.

If the parity check fails:
- Inspect the missing bug IDs.
- For each (product, version) regression, check whether the sitemap
  contained the URL the legacy fetch hit. If not, expand
  `bugdb.sitemap._PRODUCT_PREFIXES` and add a regression test.
- Iterate. Do NOT promote the schedule to `develop` until parity holds.

---

## Phase 4 — Going live

### Task 8: Merge to `develop` and activate the real schedules

- [ ] **Step 1: Open a merge request from `feat/sitemap-httpx-fetch` → `develop`**

Include in the description:
- Link to the perf-exploration report (`docs/perf-exploration.md`)
- Link to the parity check output from Task 7
- Note: the `pages` stage continues to publish from `develop`

- [ ] **Step 2: After merge, confirm the schedules created in Phase 1 Task 2 are active**

Settings → CI/CD → Schedules — both `Weekly incremental bugdb fetch` and
`Monthly full bugdb fetch (parity)` should be listed with `Active: Yes`.

- [ ] **Step 3: Watch the first real Sunday run**

The Monday morning after merge, inspect the pipeline. Expected:
- Wall time: < 90 s.
- Job log says `[i] No data changes` OR a small commit lands.

---

## Phase 5 — Cleanup (defer until two clean weekly runs)

### Task 9: Drop Playwright after two clean incremental runs

After two consecutive weekly runs ship clean data, the legacy
`--use-browser` path is unused in production. Remove it.

**Files:**
- Modify: `pyproject.toml` — remove `playwright>=1.40.0`
- Modify: `.gitlab-ci.yml` — remove `playwright install --with-deps chromium` from the `test` job
- Modify: `src/bugdb/crawlers/base.py` — delete `_fetch_via_browser`, `__aenter__`/`__aexit__` Playwright branches, `_new_page`, `_fetch_page`, `_fetch_cortex_page_with_semaphore`, `_fetch_cortex_page`
- Modify: `src/bugdb/crawlers/products/cortex_xdr.py` — delete `_legacy_crawl` and the `_parse_cortex_xdr_*_page` helpers it depends on (keep the FluidTopics path's `_parse_cortex_xdr_release_page_html`)
- Modify: each product crawler — drop the `discover_versions()` JS-probe methods that are now dead code
- Modify: `tests/conftest.py` — remove `MockPlaywright`/`MockBrowser`/`MockPage` if no test references them after the deletion above. (Some tests may still need fixture-driven mocks; convert those to `respx` mocks instead.)
- Modify: `src/bugdb/cli.py` — drop the `--use-browser` flag and the `headless` plumbing

- [ ] **Step 1: Run the test suite to confirm nothing depends on Playwright**

```bash
uv run pytest -x
```

If failures: keep Playwright a while longer; the tests still rely on it.

- [ ] **Step 2: Delete and re-run**

Apply each deletion file-by-file, re-run `pytest -x` between each.

- [ ] **Step 3: Commit**

```bash
git commit -m "chore: drop Playwright runtime dependency (two clean weekly runs)"
```

---

## Self-review

**Spec coverage:**
- ✅ Weekly scheduled incremental fetch (Phase 2 Task 3, schedule in Phase 1)
- ✅ Sitemap-driven incremental + manifest persistence (already shipped on the feature branch; just consumed here)
- ✅ Commit back to `develop` with `[skip ci]` to avoid loops (Task 3 step 1)
- ✅ Monthly full refresh to absorb sitemap lies (Task 4)
- ✅ Token + branch protection (Task 1)
- ✅ Smoke-test on the feature branch before activating (Task 6)
- ✅ Eventual Playwright removal (Task 9)

**Placeholder scan:** none. Every CI block is shown in full.

**Type consistency:** YAML keys and variable names (`BUGDB_JOB`,
`BUGDB_BOT_TOKEN`) match across all jobs and the Schedule UI variables.

**Risks called out:**
- Forgetting `[skip ci]` in the bot's commit message would trigger a loop
  (mitigated: hard-coded in the script block).
- A corrupted manifest can't be auto-recovered. Operators can:
  - Trigger the monthly full job on demand (re-run from Schedules UI).
  - Or push a manual commit deleting `assets/bugdb.manifest.json` — the
    next incremental run will rebuild it.
- The `data-refresh` stage runs *between* `test` and `deploy` in the
  default pipeline definition, but the `rules:` blocks ensure those
  three jobs never run together (`test` runs on commits/MRs, the
  refresh jobs only on schedules, `pages` only on default branch).
  Verify with the GitLab pipeline graph after merge.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-01-weekly-incremental-ci.md`. Execution requires GitLab admin access for Phase 1 (token + schedules) — this is an operator step, not a code-change step. The CI YAML files in Phase 2 are pure code and can be implemented by any agent or human with repo write access.**

**Suggested execution order:**
1. Phase 1 (operator, ~10 min)
2. Phase 2 (code; can run as Inline Execution via superpowers:executing-plans)
3. Phase 3 (operator + agent in concert; manual schedule play)
4. Phase 4 (operator MR + merge)
5. Phase 5 (agent, two weeks later)
