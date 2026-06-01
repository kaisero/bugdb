"""Compare two bugdb JSON snapshots issue-count-wise.

Usage:
  python scripts/parity_check.py old.json new.json [--min-ratio 1.0]

Exits 0 if for every (product, version) the new snapshot has
at least min_ratio * old count of known and addressed issues.

Used after switching from the Playwright fetch path to the
httpx + sitemap path to confirm we haven't lost issues.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _by_pv(db: dict) -> dict[tuple[str, str], tuple[int, int]]:
    out: dict[tuple[str, str], tuple[int, int]] = {}
    for p in db.get("products", []):
        for v in p.get("versions", []):
            out[(p["id"], v["version"])] = (
                len(v.get("known_issues", [])),
                len(v.get("addressed_issues", [])),
            )
    return out


def _by_bug_id(db: dict) -> dict[tuple[str, str, str], set[str]]:
    """Index of (product, version, kind) -> set of bug IDs."""
    out: dict[tuple[str, str, str], set[str]] = {}
    for p in db.get("products", []):
        for v in p.get("versions", []):
            for kind in ("known_issues", "addressed_issues"):
                out[(p["id"], v["version"], kind)] = {
                    issue["bug_id"] for issue in v.get(kind, [])
                }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("old", type=Path)
    ap.add_argument("new", type=Path)
    ap.add_argument(
        "--min-ratio",
        type=float,
        default=1.0,
        help="Per-(product,version) ratio of new/old counts required. "
        "Default 1.0 = no regressions tolerated.",
    )
    ap.add_argument(
        "--show-missing-ids",
        action="store_true",
        help="Print the bug IDs missing from the new snapshot for each regression.",
    )
    args = ap.parse_args()

    old_doc = json.loads(args.old.read_text())
    new_doc = json.loads(args.new.read_text())
    old = _by_pv(old_doc)
    new = _by_pv(new_doc)
    failed = []
    for key, (ko, ao) in old.items():
        kn, an = new.get(key, (0, 0))
        if ko > 0 and kn < ko * args.min_ratio:
            failed.append((key, "known", ko, kn))
        if ao > 0 and an < ao * args.min_ratio:
            failed.append((key, "addressed", ao, an))

    only_new = set(new) - set(old)
    if only_new:
        print(f"[i] {len(only_new)} (product,version) pairs new in new.json")
        for k in sorted(only_new)[:20]:
            print(f"    + {k}")
    only_old = set(old) - set(new)
    if only_old:
        print(f"[!] {len(only_old)} (product,version) pairs missing in new.json:")
        for k in sorted(only_old):
            print(f"    {k}")

    if failed:
        print(f"\n[x] {len(failed)} issue counts regressed:")
        if args.show_missing_ids:
            old_ids = _by_bug_id(old_doc)
            new_ids = _by_bug_id(new_doc)
            for (pid, ver), kind, o, n in failed:
                missing = sorted(
                    old_ids.get((pid, ver, f"{kind}_issues"), set())
                    - new_ids.get((pid, ver, f"{kind}_issues"), set())
                )
                print(f"    {pid} {ver} {kind}: old={o} new={n} missing={missing[:20]}")
        else:
            for (pid, ver), kind, o, n in failed:
                print(f"    {pid} {ver} {kind}: old={o} new={n}")
        return 1
    print("[ok] new ≥ %.0f%% of old for every (product,version)" % (args.min_ratio * 100))
    return 0


if __name__ == "__main__":
    sys.exit(main())
