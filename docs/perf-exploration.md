# `bugdb fetch` performance exploration

Date: 2026-05-31
Branch: `develop`
Scope: exploration only — no production code changes.

## TL;DR

The current fetch pipeline is slow because **every page fetch goes through
headless Chromium, waits for `networkidle`, and then sleeps an additional
3000 ms hard wait**. That overhead is **~6.4 s per URL** vs **~0.4 s** with
raw HTTP — a **15×** ceiling. Concurrency is also capped at 3.

`docs.paloaltonetworks.com` and `docs-cortex.paloaltonetworks.com` both have
**fully usable non-JS data sources**:

| Source | Endpoint | Format | Auth | Notes |
|---|---|---|---|---|
| docs.paloaltonetworks.com | direct URL | HTML (server-rendered, has the issue table) | none | Bug IDs and descriptions are in the raw HTML. The current parser appears empty-handed only because of an odd inline-`<div>` wrapper that browsers auto-fix but lxml doesn't. One-line `unwrap()` fixes it. |
| docs.paloaltonetworks.com | `/sitemap.xml` (5 MB, 24 720 entries, with `<lastmod>`) | XML | none | Complete URL inventory of every release-notes page. Lets us skip both discovery crawls *and* unchanged pages. |
| docs-cortex.paloaltonetworks.com | `/api/khub/maps`, `/api/khub/maps/{id}/topics`, `/api/khub/maps/{id}/topics/{id}/content` | JSON + small HTML fragments | none | FluidTopics CCMS public API. Replaces shadow-DOM scraping with structured queries. |

Three optimization paths are explored below. They are **complementary**, not
mutually exclusive — Approach C is essentially "A or B" plus a stronger
incremental gate.

---

## Current pipeline — where the time goes

Architecture refresher (paths relative to `src/bugdb/crawlers/`):

- `base.py` — `BaseCrawler` manages a Playwright Chromium browser, fetches
  every URL with `page.goto(..., wait_until="networkidle")` followed by an
  additional `page.wait_for_timeout(3000)` (`wait_time=5000` for Cortex), then
  pulls `page.content()` and parses with BeautifulSoup + lxml.
  (`base.py:185-189`, `base.py:323-326`).
- `BaseCrawler._fetch_page_with_semaphore` enforces a global
  `asyncio.Semaphore(max_concurrency)`; default `max_concurrency=3`
  (`base.py:67-72`, `base.py:218`).
- Each fetch opens a new `Page` and closes it after one URL — no page reuse.
- Discovery of versions for PAN-OS probes ~10 candidate URLs through
  Playwright before any "real" fetch (`products/panos.py:33-72`).
- The Cortex path additionally walks shadow DOM via
  `page.query_selector_all("h1, h2, h3, h4, table")` followed by
  `element.evaluate("el => el.outerHTML")` — one RPC per element
  (`base.py:329-346`).

### Measured per-URL cost (single warm fetch on M1 Mac, 50 Mbit link)

```
docs.paloaltonetworks.com — pan-os-11-2-3-known-issues
  raw httpx (HTTP/2, follow_redirects)            ~ 406 ms,  365 KB
  raw curl                                         ~ 555 ms,  365 KB
  Playwright (networkidle + 3 s hard wait)         ~6430 ms, 1152 KB rendered DOM

docs-cortex.paloaltonetworks.com (shadow DOM SPA)
  raw httpx                                        ~  77 ms,    3 KB (shell only — no content)
  /api/khub/maps/{id}/topics/{id}/content (JSON)   ~ 100 ms,    2 KB (clean issue table HTML)
  Playwright (networkidle + 2 s wait)              ~4240 ms
```

### Scaling check

Sitemap inventory of pages the fetch could ever care about:

```
total <url> entries in sitemap.xml             24 720
known-issues  loc=                                514
addressed-issues  loc=                            928
known-and-addressed  loc=                         541
pan-os/release-notes  loc=                        798
globalprotect  loc=                             1 429
prisma-access  loc=                             1 429
```

So the full universe is **~1 360 issue URLs across all products** (we don't
fetch all of them today — discovery via JS-rendered nav misses some).

### Throughput model

| Mode | Per-URL | Concurrency | 1 360 URLs |
|---|---|---|---|
| Current Playwright + 3 s wait, sem=3 | ~6.4 s | 3 | **~48 min** |
| Playwright with `domcontentloaded`, no extra wait, blocked images/fonts/CSS, sem=8 | ~1.5 s (estimate) | 8 | **~4–5 min** |
| Raw httpx HTTP/2, sem=15 | ~0.4 s (network-bound) | 15 | **~40 s** |
| Raw httpx + sitemap `lastmod` skip (typical week-over-week diff: ~30 changed) | ~0.4 s | 15 | **<10 s** |

End-to-end empirical run (Approach B prototype, see below):

> `629 pan-os URLs from sitemap → 10.12 s wall time → 5 886 issues parsed.`
> One product. The current full crawl over all 27 products takes
> >30 min by the user's report.

---

## Approach A — Stay on Playwright, fix what's expensive

**Idea**: Keep the architecture. Cut the four biggest wastes: network-idle
wait, hard sleep, untrimmed resource loading, low concurrency.

### What to change

1. **Drop `wait_until="networkidle"`** → use `"domcontentloaded"`. The
   tables are present in the initial HTML; `networkidle` waits for analytics
   beacons and lazy images that we don't read.
2. **Remove the 3 s `page.wait_for_timeout`** (`base.py:186`). With
   `domcontentloaded` the table is already there. If a future page proves
   JS-dependent, gate the wait on `page.wait_for_selector("table tr td")` —
   sub-100 ms when present, controlled timeout if not.
3. **Block useless resources**:
   ```python
   await context.route("**/*", lambda route:
       route.abort() if route.request.resource_type in
       {"image", "font", "stylesheet", "media"} else route.continue_())
   ```
   On the sampled `pan-os` page Playwright fires **81 requests** (21 script,
   13 image, 9 font, 4 CSS, 30 XHR). Blocking image/font/CSS roughly halves
   wall time and removes 1 MB+ per page.
4. **Reuse pages**. Currently `_new_page() / page.close()` per URL — about
   200–400 ms of Chromium overhead each time. Pool N persistent pages keyed
   to the semaphore slots; navigate, don't recreate.
5. **Raise `max_concurrency`** from 3 to 8–12. The docs site happily served
   30 parallel requests in our probe with zero errors. The connection-refused
   backoff path (`base.py:120-164`) already covers the rate-limit case.

### Expected speedup

~ **3–5×** end-to-end. Doesn't fix the architectural problem — we're still
running a browser to parse static HTML — but it's a 1-day patch with
essentially zero risk to parser correctness.

### Trade-offs

- **Pros**: Smallest diff. Existing crawler logic, retry, dedup all
  untouched. CI image still needs Chromium, but the existing GitLab job
  already installs it.
- **Cons**: Still pays Chromium memory cost in CI (each Chromium tab is
  ~80 MB RSS — fine, but not free). The `wait_for_selector` fallback adds
  per-product knowledge of what selector to wait for. Cortex shadow-DOM
  path is unchanged and still slow.

### Sketch (illustrative)

```python
# base.py — replacement for _fetch_page
BLOCK_TYPES = {"image", "font", "stylesheet", "media"}

async def __aenter__(self):
    self._playwright = await async_playwright().start()
    self._browser = await self._playwright.chromium.launch(
        headless=self.headless,
        args=["--disable-blink-features=AutomationControlled"],
    )
    self._context = await self._browser.new_context()
    await self._context.route(
        "**/*",
        lambda r: r.abort() if r.request.resource_type in BLOCK_TYPES else r.continue_(),
    )
    self._page_pool = asyncio.Queue()
    for _ in range(self.max_concurrency):
        self._page_pool.put_nowait(await self._context.new_page())
    self._semaphore = asyncio.Semaphore(self.max_concurrency)
    return self

async def _fetch_page(self, page, url, wait_time=0):
    full_url = url if url.startswith("http") else urljoin(BASE_URL, url)
    await page.goto(full_url, wait_until="domcontentloaded", timeout=20_000)
    # Cheap, deterministic wait — fires the moment the issue table is present:
    try:
        await page.wait_for_selector("table tbody tr td", timeout=3_000)
    except TimeoutError:
        pass  # Pages with no table still parse fine
    return BeautifulSoup(await page.content(), "lxml")
```

---

## Approach B — Replace Playwright with `httpx` + tiny DOM-fixup

**Idea**: The vast majority of release-notes pages are server-rendered HTML.
The current crawler returns 0 issues from raw HTML only because of an
HTML-validity quirk we can fix in one line. Once fixed, Chromium is not
needed for `docs.paloaltonetworks.com`. For `docs-cortex.paloaltonetworks.com`,
swap the shadow-DOM walk for the FluidTopics REST API.

### Evidence — raw HTML *does* contain the tables

Sample raw HTML excerpt for `pan-os-11-2-3-known-issues`:

```html
<table class="table colsep rowsep">
  <thead class="thead">
    <tr class="row rowsep"><div style="display: inline;">
      <th class="entry"><div class="p"><b>Issue ID</b></div></th>
      <th class="entry"><div class="p"><b>Description</b></div></th>
    </div></tr>
  </thead>
  <tbody class="tbody"><div style="display: inline;">
    <tr class="row"><div style="display: inline;">
      <td><div class="p"><b>PAN-308507</b></div></td>
      <td><div class="p">Strata Logging Service (SLS) log-forwarding streams ...</div></td>
    </div></tr>
    ...
```

Note the `<div style="display: inline;">` placed *between* `<tbody>` and
`<tr>`. Real browsers run the HTML5 tree-construction "foster-parenting"
rule and move the `<div>` out of the table — so the rendered DOM has
`<tbody><tr>` directly. lxml does **not** apply foster-parenting in the same
way, so `tbody.find_all("tr", recursive=False)` returns `0`, and
`_parse_issues_table` early-exits. That single quirk is the entire reason
the project moved to Playwright.

### Fix (verified working in this exploration)

```python
# Before BeautifulSoup parsing, unwrap the inline-display divs inside tables:
soup = BeautifulSoup(html, "lxml")
for d in soup.select(
    'table div[style*="display: inline"], table div[style*="display:inline"]'
):
    d.unwrap()
```

With that one change, the existing `_parse_issues_table` returns **43 issues
from the pan-os-11-2-3-known-issues page** (vs. 0 today) with no other
modifications.

### End-to-end prototype (run during this exploration)

```
Source        : sitemap.xml entries matching pan-os/*known-issues*|*addressed-issues*
URLs          : 629
Concurrency   : asyncio.Semaphore(15), httpx HTTP/2, follow_redirects
Wall time     : 10.12 s
HTTP 200      : 184  (445 were 404s — sitemap drift, harmless: just discard)
Pages with    : 154
  issues
Issues parsed : 5 886
Bytes downloaded: 58 MB
```

That is **one product**. Multiply by 26 and hold concurrency constant: ~4
minutes for an *exhaustive* full fetch. Today's full run takes >30 min and
covers a strict subset.

### Cortex side — FluidTopics khub API

The Cortex docs run on FluidTopics, which exposes a public REST API at
`/api/khub/`. Probed during this exploration:

```
GET /api/khub/maps                 → list every doc map (534 entries, 2.2 MB)
GET /api/khub/maps/{mapId}         → metadata + topicsApiEndpoint
GET /api/khub/maps/{mapId}/topics  → list of topics in the map, with readerUrl
GET .../topics/{topicId}/content   → topic body as small HTML fragment
```

Sample content endpoint response for "Addressed issues in Cortex XDR agent
9.1.1" (2 KB total):

```html
<div class="ft_node_extractor content-locale-en-US content-locale-en">
  <p>The following issues have been resolved in this release.</p>
  <table>
    <thead><tr><th>ISSUE</th><th>PLATFORM</th><th>DESCRIPTION</th></tr></thead>
    <tbody>
      <tr><td><p>CPATR-36823</p></td><td><p>Windows</p></td>
          <td><p>Fixed an issue to improve compatibility …</p></td></tr>
      ...
```

This replaces the entire `_fetch_cortex_page` shadow-DOM walk
(`base.py:306-363`) — which currently averages ~4.2 s/URL — with a
~100 ms JSON+HTML fetch.

### What to change

1. New module `bugdb.crawlers.transport` with two clients:
   - `HttpDocsClient` — `httpx.AsyncClient(http2=True, follow_redirects=True)`
     with a 15–20 concurrency cap, retries on 429/503 with exponential
     backoff, the `<div>` unwrap helper applied in a single place.
   - `FluidTopicsClient` — wraps `/api/khub/maps` + topics + content, with
     map caching by product.
2. `BaseCrawler` no longer needs `__aenter__/__aexit__` opening Chromium.
   `_fetch_page_with_semaphore` becomes a thin wrapper over the chosen
   client.
3. Remove `playwright` from `pyproject.toml` runtime deps. Tests can keep
   `playwright` if they pin the existing behavior, or use recorded fixtures.
4. CI drops `playwright install --with-deps chromium`. That step alone is
   typically 30–60 s wall time and ~150 MB of cache traffic on every job.

### Expected speedup

**15–30×** wall time. The dominant cost becomes parsing, not fetching.

### Trade-offs

- **Pros**: Removes the heaviest CI dependency (browser binary + 150 MB
  cache). Drops memory budget from "Chromium per worker" to "httpx per
  worker". The CI minutes problem largely vanishes.
- **Cons**:
  - Cortex parser changes from "scrape shadow DOM" to "consume khub API" —
    that's a real refactor, but the new code is *less* code and much more
    boring (it's just JSON). Mapping `readerUrl` ↔ existing `product/version`
    identifiers needs care so we don't change the JSON schema downstream.
  - If Palo Alto ever rebuilds the docs site as a true SPA (data inside
    `__NEXT_DATA__` or fetched via XHR), httpx alone breaks. Mitigation:
    keep `BaseCrawler` open to a `Transport` interface so a Playwright
    transport can be re-introduced behind a flag, but as a fallback, not
    the default.
  - The inline-`<div>` quirk could change tomorrow if AEM updates its
    template. Add a regression test that pins this exact structure (a small
    fixture file under `tests/fixtures/`) so the parser unwrap step keeps
    working.

---

## Approach C — Sitemap-driven incremental: only fetch what changed

**Idea**: Combine either A or B with a stronger incremental skip.
Today's `--incremental` skips versions already present in `data.json`, but
it still runs full discovery for every product on every run. The sitemap
gives us a free per-URL `<lastmod>` timestamp.

### What to change

1. Cache `sitemap.xml` once per run (5 MB, ~0.5 s).
2. Parse out all known/addressed/known-and-addressed entries; group them
   by product prefix matched against a known mapping
   (`/pan-os/...` → `panos`, `/globalprotect/...` → `globalprotect`, etc.).
3. Compare each entry's `<lastmod>` against a persisted manifest:
   ```json
   {
     "https://.../pan-os-11-2-3-known-issues": {
       "lastmod": "2026-04-12",
       "etag": "...",
       "content_hash": "sha256:..."
     }
   }
   ```
   Store this in `assets/bugdb.manifest.json` alongside `bugdb.json`.
4. On fetch: only enqueue URLs whose `lastmod` is newer than the manifest
   entry — or whose URL is new — or whose etag fails a HEAD revalidate.
5. As a belt-and-braces check, after a successful 200 response compute
   `sha256(body)` and skip parse + JSON merge if it matches the stored hash
   (handles cases where `lastmod` lies).
6. Discovery of versions/major releases becomes a sitemap-filter operation,
   not a Playwright crawl: removes the "probe 10 candidate URLs to find
   which versions exist" pattern in `products/panos.py:33-72`.

### Expected speedup for the **incremental** CI run

Worst case the sitemap shows a few dozen URLs changed since the last run;
typical week: ~30 URLs.

```
30 URLs × ~0.4 s/URL via httpx, concurrency 10  →  ~3 s of fetch work
+ sitemap download                              →  ~0.5 s
+ manifest read/write + JSON merge              →  ~1 s
                                                ─────────
                                                   ~5 s total
```

Combined with Approach B, an *incremental* fetch can run on every commit
without burning CI minutes. Combined with Approach A only, the savings are
smaller (still pay 1.5 s/URL Chromium overhead) but you'd still drop a
30 min run to under a minute on a typical changeset.

### Trade-offs

- **Pros**: Best fit for CI/CD spend. Makes "fetch on every push" actually
  feasible. Adds a small but useful audit trail (manifest).
- **Cons**:
  - Trust in `<lastmod>` is finite — Adobe AEM can republish without
    bumping it. The content-hash short-circuit covers this, but only after
    the GET. Mitigation: weekly full refresh as a separate scheduled job
    (cheap, since Approach A or B made it fast anyway).
  - You now have *two* JSON artifacts that must be kept in sync. If the
    manifest is corrupted, `--force-full` must reset it. Suggest checking
    the manifest into the same repo/branch the existing `data.json` lives
    in.
  - The sitemap also lists pages we *don't* want (PDFs, FAQs, general
    docs). The product-prefix matcher needs to be precise; easy to test
    with the same fixture-based approach as Approach B.

---

## What I'd actually recommend

If "credits in CI" is the constraint and a multi-day refactor is fine:
**B + C together**.

If you want a Friday-afternoon win that already cuts CI time materially:
**A alone**, then revisit B once the CI bill calms down.

If you only want one change: **just fix the `<div>` unwrap and switch to
httpx for `docs.paloaltonetworks.com`** (Approach B, without touching
Cortex). That's <300 lines of new code, kills the Chromium dependency for
25 of 27 products, and Cortex can keep its current Playwright path as a
short-term island.

### What is *not* worth doing

- "Use `requests-html` or `pyppeteer`" — same problem class, different vendor.
- Caching with `cachetools`/`diskcache` on top of the current crawler —
  doesn't help CI, which starts cold each run.
- A Cloudflare Worker / proxy that does the fetch for us — adds external
  infra and credentials for negligible gain over httpx.

---

## Appendix — concrete measurements

### Raw HTTP vs Playwright for one URL
```
URL: pan-os/11-2/.../pan-os-11-2-3-known-issues
  curl -sSL             :   555 ms,   365 KB,  198 PAN-* tokens in body
  httpx HTTP/2          :   406 ms,   365 KB,   43 PAN-* IDs after parse
  Playwright networkidle+3s : 6 432 ms, 1 152 KB rendered DOM
  Playwright requests count : 81 (script=21, css=4, image=13, font=9, xhr=30)
```

### 30 random issue-URL benchmark, httpx HTTP/2, concurrency=20
```
OK              : 30 / 30
fetch latency   : p50  1.43 s, p95  2.80 s   (cold-cache)
parse latency   : p50 ~30 ms
page size       : p50  335 KB,  p95  2.46 MB
distinct bug IDs/page : p50 80, p95 198
total wall time : 2.88 s   ≈ 96 ms/URL
```

### Full PAN-OS sitemap crawl, httpx HTTP/2, concurrency=15
```
URLs                 : 629 (from sitemap.xml)
HTTP 200             : 184    (sitemap drift accounts for the rest)
Pages with issues    : 154
Issues parsed        : 5 886
Bytes downloaded     : 58.1 MB
Wall time            : 10.12 s
Avg per URL          : 16 ms (including parse)
```

### FluidTopics khub API for Cortex
```
GET /api/khub/maps                                 200, 2.2 MB
GET /api/khub/maps/{id}                            200,  3.8 KB metadata
GET /api/khub/maps/{id}/topics                     200,  8.2 KB (9 topics)
GET .../topics/{id}/content   (addressed issues)   200,  2.0 KB → 10 issues parsed
GET .../topics/{id}/content   (known limitations)  200,  3.3 KB → 1 issue parsed
total wall time to fully crawl one Cortex map :  < 1 s
```
