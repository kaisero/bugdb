"""Tests for the Transport protocol and FetchedPage dataclass."""

from bugdb.transport.base import FetchedPage, Transport


def test_fetched_page_holds_url_status_and_html():
    p = FetchedPage(url="https://x/y", status_code=200, html="<table></table>", lastmod=None)
    assert p.url == "https://x/y"
    assert p.status_code == 200
    assert p.html == "<table></table>"
    assert p.lastmod is None


def test_fetched_page_carries_optional_lastmod():
    p = FetchedPage(url="https://x/y", status_code=200, html="", lastmod="2026-03-01")
    assert p.lastmod == "2026-03-01"


def test_transport_protocol_requires_fetch_and_close():
    assert hasattr(Transport, "fetch")
    assert hasattr(Transport, "aclose")
