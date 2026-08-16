"""div.topic blocks nest; only the leaves are issues.

The AI Access Security and Enterprise DLP pages wrap their per-issue
div.topic blocks in an outer div.topic. Matching the wrapper produced a
phantom issue carrying the first inner bug id and the whole page's text.
"""

from pathlib import Path

from bs4 import BeautifulSoup

from bugdb.crawlers.base import BaseCrawler

FIXTURE = Path(__file__).parent / "fixtures" / "ai-access-security" / "addressed-issues.html"

NESTED_CHAIN_FIXTURE = (
    Path(__file__).parent / "fixtures" / "plugin-aws" / "known-issues-522-nested-chain.html"
)


def _parse():
    soup = BeautifulSoup(FIXTURE.read_text(), "lxml")
    return BaseCrawler()._parse_topic_format_issues(soup)


def _parse_nested_chain():
    soup = BeautifulSoup(NESTED_CHAIN_FIXTURE.read_text(), "lxml")
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


# --- Nested chain (Task 2b): a non-leaf topic can still be a real issue ---
#
# On the plugin-aws 5.2.2 page, PLUG-12161's topic physically contains the
# FWAAS-5817 and FWAAS-6961 topics as descendants (a genuine bug-tracker
# nesting artifact, not a wrapper). PLUG-12161 has its own shortdesc/p/
# workaround and must be recovered, scoped to its own content only.


def test_non_leaf_topic_with_own_content_is_recovered():
    """PLUG-12161 must not be dropped just because it contains nested topics."""
    ids = [i.bug_id for i in _parse_nested_chain()]
    assert "PLUG-12161" in ids


def test_all_issues_in_the_chain_are_present():
    ids = [i.bug_id for i in _parse_nested_chain()]
    assert ids == ["PLUG-15577", "PLUG-12161", "FWAAS-5817", "FWAAS-6961"]


def test_no_duplicate_bug_ids_in_the_chain():
    ids = [i.bug_id for i in _parse_nested_chain()]
    assert len(ids) == len(set(ids))


def test_non_leaf_description_excludes_nested_topic_text():
    """PLUG-12161's description must be its own text, not the nested FWAAS text."""
    by_id = {i.bug_id: i for i in _parse_nested_chain()}
    plug_12161 = by_id["PLUG-12161"]
    assert "GovCloud" in plug_12161.description
    assert "FWAAS-5817" not in plug_12161.description
    assert "does not display any error message" not in plug_12161.description
    assert "first time tenant linked" not in plug_12161.description


def test_non_leaf_workaround_excludes_nested_topic_text():
    """PLUG-12161's "Workaround:" marker sits alone in its own div.p, with
    the actual steps in later sibling div.p elements — the existing
    single-paragraph workaround extraction doesn't reach those siblings, so
    ``workaround`` comes back None. That's a known, pre-existing extraction
    gap (unrelated to nesting), not something this test is trying to fix.
    Asserting the exact value, instead of only checking it when non-None,
    pins the gap: if scoping logic ever changes and the nested FWAAS-*
    workaround text leaks in, this test fails loudly instead of silently
    passing.
    """
    by_id = {i.bug_id: i for i in _parse_nested_chain()}
    plug_12161 = by_id["PLUG-12161"]
    assert plug_12161.workaround is None


def test_nested_leaf_descriptions_stay_scoped_to_themselves():
    by_id = {i.bug_id: i for i in _parse_nested_chain()}
    fwaas_5817 = by_id["FWAAS-5817"]
    fwaas_6961 = by_id["FWAAS-6961"]
    assert "does not display any error message" in fwaas_5817.description
    assert "first time tenant linked" not in fwaas_5817.description
    assert "first time tenant linked" in fwaas_6961.description
    assert fwaas_6961.workaround is not None
    assert "Refresh Vpc" in fwaas_6961.workaround
