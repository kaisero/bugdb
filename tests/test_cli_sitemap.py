"""End-to-end test: CLI fetch via sitemap + httpx transport, writes manifest."""

import json
from pathlib import Path

import httpx
import respx
from typer.testing import CliRunner

from bugdb.cli import app

_SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://docs.paloaltonetworks.com/pan-os/11-2/pan-os-release-notes/pan-os-11-2-3-known-and-addressed-issues/pan-os-11-2-3-known-issues</loc>
    <lastmod>2026-04-01</lastmod>
  </url>
</urlset>
"""

_ISSUE_PAGE = """<html><body>
<table>
  <thead><tr><th>Issue ID</th><th>Description</th></tr></thead>
  <tbody>
    <tr><td>PAN-42</td><td>desc</td></tr>
  </tbody>
</table>
</body></html>
"""


@respx.mock
def test_fetch_uses_sitemap_and_writes_manifest(tmp_path: Path):
    respx.get("https://docs.paloaltonetworks.com/sitemap.xml").mock(
        return_value=httpx.Response(200, text=_SITEMAP)
    )
    respx.get(
        "https://docs.paloaltonetworks.com/pan-os/11-2/pan-os-release-notes/pan-os-11-2-3-known-and-addressed-issues/pan-os-11-2-3-known-issues"
    ).mock(return_value=httpx.Response(200, text=_ISSUE_PAGE))

    out = tmp_path / "bugdb.json"
    manifest_path = tmp_path / "bugdb.manifest.json"

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "fetch",
            "panos",
            "-o",
            str(out),
            "-f",
            "--manifest",
            str(manifest_path),
            "--no-progress",
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(out.read_text())
    assert len(data["products"]) == 1
    assert data["products"][0]["id"] == "panos"
    versions = data["products"][0]["versions"]
    assert any(v["version"] == "11.2.3" for v in versions)
    # Manifest captured the sitemap lastmod
    assert manifest_path.exists()
    mdata = json.loads(manifest_path.read_text())
    assert any("pan-os-11-2-3-known-issues" in k for k in mdata["entries"])


@respx.mock
def test_fetch_no_manifest_does_not_write_manifest(tmp_path: Path):
    respx.get("https://docs.paloaltonetworks.com/sitemap.xml").mock(
        return_value=httpx.Response(200, text=_SITEMAP)
    )
    respx.get(
        "https://docs.paloaltonetworks.com/pan-os/11-2/pan-os-release-notes/pan-os-11-2-3-known-and-addressed-issues/pan-os-11-2-3-known-issues"
    ).mock(return_value=httpx.Response(200, text=_ISSUE_PAGE))

    out = tmp_path / "bugdb.json"
    manifest_path = tmp_path / "bugdb.manifest.json"

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "fetch",
            "panos",
            "-o",
            str(out),
            "-f",
            "--manifest",
            str(manifest_path),
            "--no-manifest",
            "--no-progress",
        ],
    )
    assert result.exit_code == 0, result.output
    assert out.exists()
    assert not manifest_path.exists()


@respx.mock
def test_fetch_with_manifest_skips_known_url(tmp_path: Path):
    """When manifest lastmod matches sitemap, the issue URL is not fetched."""
    respx.get("https://docs.paloaltonetworks.com/sitemap.xml").mock(
        return_value=httpx.Response(200, text=_SITEMAP)
    )
    issue_route = respx.get(
        "https://docs.paloaltonetworks.com/pan-os/11-2/pan-os-release-notes/pan-os-11-2-3-known-and-addressed-issues/pan-os-11-2-3-known-issues"
    ).mock(return_value=httpx.Response(200, text=_ISSUE_PAGE))

    out = tmp_path / "bugdb.json"
    manifest_path = tmp_path / "bugdb.manifest.json"
    # Pre-seed the manifest so the URL's lastmod already matches.
    manifest_path.write_text(
        json.dumps(
            {
                "entries": {
                    "https://docs.paloaltonetworks.com/pan-os/11-2/pan-os-release-notes/pan-os-11-2-3-known-and-addressed-issues/pan-os-11-2-3-known-issues": {
                        "lastmod": "2026-04-01"
                    }
                }
            }
        )
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "fetch",
            "panos",
            "-o",
            str(out),
            "-f",
            "--manifest",
            str(manifest_path),
            "--no-progress",
        ],
    )
    assert result.exit_code == 0, result.output
    # The known-issue page was never fetched because the manifest skipped it.
    assert issue_route.call_count == 0
