"""Tests for FluidTopicsTransport."""

from pathlib import Path

import httpx
import pytest
import respx

from bugdb.transport.fluidtopics_transport import FluidTopicsTransport

FX = Path(__file__).parent / "fixtures" / "fluidtopics"


@pytest.mark.asyncio
@respx.mock
async def test_lists_maps_filtered_by_product():
    respx.get("https://docs-cortex.paloaltonetworks.com/api/khub/maps").mock(
        return_value=httpx.Response(200, text=(FX / "maps.json").read_text())
    )
    async with FluidTopicsTransport() as t:
        maps = await t.list_maps(product="Cortex XDR")
    assert len(maps) == 1
    assert maps[0]["id"] == "abc123"


@pytest.mark.asyncio
@respx.mock
async def test_lists_maps_without_filter_returns_all():
    respx.get("https://docs-cortex.paloaltonetworks.com/api/khub/maps").mock(
        return_value=httpx.Response(200, text=(FX / "maps.json").read_text())
    )
    async with FluidTopicsTransport() as t:
        maps = await t.list_maps()
    assert len(maps) == 2


@pytest.mark.asyncio
@respx.mock
async def test_lists_topics_in_a_map():
    respx.get(
        "https://docs-cortex.paloaltonetworks.com/api/khub/maps/abc123/topics"
    ).mock(return_value=httpx.Response(200, text=(FX / "topics.json").read_text()))
    async with FluidTopicsTransport() as t:
        topics = await t.list_topics(map_id="abc123")
    assert {tp["id"] for tp in topics} == {"t-9-1", "t-9-1-1-addr", "t-9-1-known"}


@pytest.mark.asyncio
@respx.mock
async def test_fetch_topic_content_returns_html_fragment():
    respx.get(
        "https://docs-cortex.paloaltonetworks.com/api/khub/maps/abc123/topics/t-9-1-1-addr/content"
    ).mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text=(FX / "content-addressed-issues.html").read_text(),
        )
    )
    async with FluidTopicsTransport() as t:
        page = await t.fetch_topic(map_id="abc123", topic_id="t-9-1-1-addr")
    assert page.status_code == 200
    assert "CPATR-1" in page.html


@pytest.mark.asyncio
@respx.mock
async def test_fetch_protocol_method_works():
    respx.get("https://docs-cortex.paloaltonetworks.com/any").mock(
        return_value=httpx.Response(200, text="x")
    )
    async with FluidTopicsTransport() as t:
        page = await t.fetch("https://docs-cortex.paloaltonetworks.com/any")
    assert page.status_code == 200
    assert page.html == "x"
