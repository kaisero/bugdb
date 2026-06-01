"""Tests for the Cortex XDR crawler's FluidTopics path."""

import pytest

from bugdb.crawlers.products.cortex_xdr import CortexXDRCrawler
from bugdb.transport.base import FetchedPage


_ADDRESSED_HTML = (
    "<div><table>"
    "<thead><tr><th>ISSUE</th><th>DESCRIPTION</th></tr></thead>"
    "<tbody>"
    "<tr><td>CPATR-1</td><td>fixed A</td></tr>"
    "<tr><td>CPATR-2</td><td>fixed B</td></tr>"
    "</tbody></table></div>"
)
_KNOWN_HTML = (
    "<div><table>"
    "<thead><tr><th>ISSUE</th><th>DESCRIPTION</th></tr></thead>"
    "<tbody>"
    "<tr><td>CPATR-99</td><td>known X</td></tr>"
    "</tbody></table></div>"
)


class _StubFluidTopics:
    def __init__(self, *, maps, topics, contents):
        self._maps = maps
        self._topics = topics
        self._contents = contents

    async def list_maps(self, *, product=None):
        return self._maps

    async def list_topics(self, *, map_id):
        return self._topics

    async def fetch_topic(self, *, map_id, topic_id):
        return FetchedPage(
            url=f"/api/khub/maps/{map_id}/topics/{topic_id}/content",
            status_code=200,
            html=self._contents[topic_id],
        )

    async def aclose(self):
        pass


@pytest.mark.asyncio
async def test_crawl_returns_issues_grouped_by_version():
    stub = _StubFluidTopics(
        maps=[
            {
                "id": "m1",
                "title": "Cortex XDR Agent Release Notes",
                "metadata": [{"key": "Product", "values": ["Cortex XDR"]}],
            }
        ],
        topics=[
            {
                "title": "Addressed issues in Cortex XDR agent 9.1",
                "id": "addr-9-1",
                "contentApiEndpoint": "/api/khub/maps/m1/topics/addr-9-1/content",
                "metadata": [{"key": "Version", "values": ["9.1"]}],
            },
            {
                "title": "Cortex XDR agent known limitations",
                "id": "kl-9-1",
                "contentApiEndpoint": "/api/khub/maps/m1/topics/kl-9-1/content",
                "metadata": [{"key": "Version", "values": ["9.1"]}],
            },
        ],
        contents={"addr-9-1": _ADDRESSED_HTML, "kl-9-1": _KNOWN_HTML},
    )
    crawler = CortexXDRCrawler(fluidtopics=stub)
    result = await crawler.crawl()
    assert result.product.id == "cortex-xdr"
    assert len(result.product.versions) == 1
    v = result.product.versions[0]
    assert v.version == "9.1"
    assert {i.bug_id for i in v.addressed_issues} == {"CPATR-1", "CPATR-2"}
    assert {i.bug_id for i in v.known_issues} == {"CPATR-99"}


@pytest.mark.asyncio
async def test_crawl_skips_versions_in_skip_set():
    stub = _StubFluidTopics(
        maps=[
            {
                "id": "m1",
                "title": "Cortex XDR Agent Release Notes",
                "metadata": [{"key": "Product", "values": ["Cortex XDR"]}],
            }
        ],
        topics=[
            {
                "title": "Addressed issues in Cortex XDR agent 9.1",
                "id": "addr-9-1",
                "contentApiEndpoint": "/api/khub/maps/m1/topics/addr-9-1/content",
                "metadata": [{"key": "Version", "values": ["9.1"]}],
            },
            {
                "title": "Addressed issues in Cortex XDR agent 8.5",
                "id": "addr-8-5",
                "contentApiEndpoint": "/api/khub/maps/m1/topics/addr-8-5/content",
                "metadata": [{"key": "Version", "values": ["8.5"]}],
            },
        ],
        contents={"addr-9-1": _ADDRESSED_HTML, "addr-8-5": _ADDRESSED_HTML},
    )
    crawler = CortexXDRCrawler(fluidtopics=stub)
    result = await crawler.crawl(skip_versions={"8.5"})
    versions = {v.version for v in result.product.versions}
    assert versions == {"9.1"}


@pytest.mark.asyncio
async def test_crawl_ignores_topics_without_issue_tables():
    stub = _StubFluidTopics(
        maps=[
            {
                "id": "m1",
                "title": "Cortex XDR Agent Release Notes",
                "metadata": [{"key": "Product", "values": ["Cortex XDR"]}],
            }
        ],
        topics=[
            {
                "title": "Cortex XDR Agent 9.1 Release Information",
                "id": "intro",
                "contentApiEndpoint": "/api/khub/maps/m1/topics/intro/content",
                "metadata": [{"key": "Version", "values": ["9.1"]}],
            }
        ],
        contents={"intro": "<div><p>Welcome to the release.</p></div>"},
    )
    crawler = CortexXDRCrawler(fluidtopics=stub)
    result = await crawler.crawl()
    assert result.product.versions == []


@pytest.mark.asyncio
async def test_crawl_produces_no_versions_when_all_topic_fetches_fail():
    class FailingStub(_StubFluidTopics):
        async def fetch_topic(self, *, map_id, topic_id):
            raise RuntimeError("boom")

    stub = FailingStub(
        maps=[
            {
                "id": "m1",
                "title": "Cortex XDR Agent Release Notes",
                "metadata": [{"key": "Product", "values": ["Cortex XDR"]}],
            }
        ],
        topics=[
            {
                "title": "Addressed issues in Cortex XDR agent 9.1",
                "id": "addr-9-1",
                "contentApiEndpoint": "/api/khub/maps/m1/topics/addr-9-1/content",
                "metadata": [{"key": "Version", "values": ["9.1"]}],
            }
        ],
        contents={},
    )
    crawler = CortexXDRCrawler(
        fluidtopics=stub, max_retries=1, retry_delay=0.0
    )
    result = await crawler.crawl()
    # No versions returned when the only topic fetch fails.
    assert result.product.versions == []
