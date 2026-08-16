"""div.topic blocks nest; only the leaves are issues.

The AI Access Security and Enterprise DLP pages wrap their per-issue
div.topic blocks in an outer div.topic. Matching the wrapper produced a
phantom issue carrying the first inner bug id and the whole page's text.
"""

from pathlib import Path

from bs4 import BeautifulSoup

from bugdb.crawlers.base import BaseCrawler

FIXTURE = Path(__file__).parent / "fixtures" / "ai-access-security" / "addressed-issues.html"


def _parse():
    soup = BeautifulSoup(FIXTURE.read_text(), "lxml")
    return BaseCrawler()._parse_topic_format_issues(soup)


def test_only_leaf_topics_become_issues():
    assert [i.bug_id for i in _parse()] == ["NETVIS-2045", "NETVIS-1973", "NETVIS-1825"]


def test_no_phantom_wrapper_issue():
    """The wrapper would emit NETVIS-2045 a second time with page-wide text."""
    ids = [i.bug_id for i in _parse()]
    assert len(ids) == len(set(ids))


def test_leaf_description_is_scoped_to_its_own_block():
    first = _parse()[0]
    assert first.description.startswith("AI Access Security displays User count")
    assert "unable to change the application tag" not in first.description


def test_workaround_is_extracted_from_the_bold_marker():
    second = _parse()[1]
    assert second.workaround is not None
    assert "Select Configuration" in second.workaround
