"""A single issue-ID cell can hold more than one bug ID.

Upstream (RBI known-issues, verified 2026-08-16) emits two IDs as two
sibling <div class="p"> elements inside one <td>, sharing one
description. The old parser concatenated them into "ARBI-7796ARBI-7757"
and dropped the second ID entirely.
"""

from pathlib import Path

from bs4 import BeautifulSoup

from bugdb.crawlers.base import BaseCrawler
from bugdb.crawlers.utils import split_bug_id_cell

FIXTURE = Path(__file__).parent / "fixtures" / "remote-browser-isolation" / "known-issues.html"


def _issues_table():
    soup = BeautifulSoup(FIXTURE.read_text(), "lxml")
    tables = [t for t in soup.find_all("table") if not t.find_parent("table")]
    return tables[1]


def test_boilerplate_table_yields_no_issues():
    """The 'Where Can I Use This?' matrix must never parse as issues."""
    soup = BeautifulSoup(FIXTURE.read_text(), "lxml")
    boilerplate = next(t for t in soup.find_all("table") if not t.find_parent("table"))
    assert BaseCrawler()._parse_issues_table(boilerplate) == []


def test_both_ids_in_a_paired_cell_are_recovered():
    issues = BaseCrawler()._parse_issues_table(_issues_table())
    assert [i.bug_id for i in issues] == [
        "ARBI-10270",
        "ARBI-7796",
        "ARBI-7757",
        "ARBI-7752",
    ]


def test_paired_ids_share_the_row_description():
    issues = {i.bug_id: i for i in BaseCrawler()._parse_issues_table(_issues_table())}
    assert issues["ARBI-7796"].description == issues["ARBI-7757"].description
    assert "Clipboard copy" in issues["ARBI-7796"].description


def test_paired_id_does_not_leak_into_fix_info():
    """The old parser set fix_info='ARBI-7757' on ARBI-7796."""
    issues = {i.bug_id: i for i in BaseCrawler()._parse_issues_table(_issues_table())}
    assert issues["ARBI-7796"].fix_info is None


def test_split_bug_id_cell_single_value():
    soup = BeautifulSoup('<td><div class="p">PAN-12345</div></td>', "lxml")
    assert split_bug_id_cell(soup.find("td")) == ["PAN-12345"]


def test_split_bug_id_cell_keeps_trailing_fix_info_intact():
    """A cell whose parts are not ALL bug ids must not be split — the
    'EPM-4616Resolved in ...' shape still goes through
    extract_bug_id_and_fix_info as one string."""
    soup = BeautifulSoup(
        '<td><div class="p">EPM-4616</div><div class="p">Resolved in 25.3</div></td>', "lxml"
    )
    assert split_bug_id_cell(soup.find("td")) == ["EPM-4616Resolved in 25.3"]
