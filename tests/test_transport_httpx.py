"""Tests for HttpxDocsTransport."""

from pathlib import Path

import httpx
import pytest
import respx

from bugdb.transport.httpx_transport import HttpxDocsTransport, _fix_inline_div_tables

FIXTURE = (Path(__file__).parent / "fixtures" / "inline-div-table.html").read_text()


@pytest.mark.asyncio
@respx.mock
async def test_fetch_returns_html_for_200():
    respx.get("https://docs.paloaltonetworks.com/page").mock(
        return_value=httpx.Response(200, text="<html><body>ok</body></html>")
    )
    async with HttpxDocsTransport(concurrency=2) as t:
        page = await t.fetch("https://docs.paloaltonetworks.com/page")
    assert page.status_code == 200
    assert "ok" in page.html


@pytest.mark.asyncio
@respx.mock
async def test_fetch_unwraps_inline_div_inside_tables():
    respx.get("https://docs.paloaltonetworks.com/issues").mock(
        return_value=httpx.Response(200, text=FIXTURE)
    )
    async with HttpxDocsTransport(concurrency=2) as t:
        page = await t.fetch("https://docs.paloaltonetworks.com/issues")
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(page.html, "lxml")
    tbody = soup.find("tbody")
    assert tbody is not None
    # After unwrap the rows are direct children of tbody (browser-like DOM).
    assert len(tbody.find_all("tr", recursive=False)) == 2


@pytest.mark.asyncio
@respx.mock
async def test_fetch_propagates_404():
    respx.get("https://docs.paloaltonetworks.com/missing").mock(
        return_value=httpx.Response(404, text="not found")
    )
    async with HttpxDocsTransport(concurrency=2) as t:
        page = await t.fetch("https://docs.paloaltonetworks.com/missing")
    assert page.status_code == 404


@pytest.mark.asyncio
@respx.mock
async def test_fetch_retries_on_5xx():
    route = respx.get("https://docs.paloaltonetworks.com/flaky").mock(
        side_effect=[
            httpx.Response(503, text="busy"),
            httpx.Response(200, text="ok"),
        ]
    )
    async with HttpxDocsTransport(
        concurrency=2, max_retries=3, retry_base_delay=0.01
    ) as t:
        page = await t.fetch("https://docs.paloaltonetworks.com/flaky")
    assert page.status_code == 200
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_fetch_gives_up_after_max_retries_on_5xx():
    route = respx.get("https://docs.paloaltonetworks.com/dead").mock(
        return_value=httpx.Response(503, text="busy")
    )
    async with HttpxDocsTransport(
        concurrency=2, max_retries=2, retry_base_delay=0.01
    ) as t:
        page = await t.fetch("https://docs.paloaltonetworks.com/dead")
    assert page.status_code == 503
    assert route.call_count == 2


def test_fix_inline_div_tables_noop_when_marker_absent():
    html = "<html><body><table><tr><td>x</td></tr></table></body></html>"
    assert _fix_inline_div_tables(html) is html


def test_fix_inline_div_tables_unwraps_when_marker_present():
    html = (
        "<table><tbody>"
        '<div style="display: inline;"><tr><td>x</td></tr></div>'
        "</tbody></table>"
    )
    out = _fix_inline_div_tables(html)
    # After unwrap, no inline-div remains inside the table
    assert 'style="display: inline' not in out.replace(" ", "")
