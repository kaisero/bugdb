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


def test_split_bug_id_cell_splits_ids_joined_by_and():
    """Two ids joined by 'and' inside one element (AI Access Security
    known-issues page) must be recovered as two separate ids."""
    soup = BeautifulSoup('<td><div class="p">LST-15102 and LST-15123</div></td>', "lxml")
    assert split_bug_id_cell(soup.find("td")) == ["LST-15102", "LST-15123"]


def test_split_bug_id_cell_splits_ids_joined_by_commas_and_and():
    """Three ids joined by an Oxford-comma list must be recovered as three
    separate ids (panos known-issues page)."""
    soup = BeautifulSoup(
        '<td><div class="p">PAN-150170, PAN-150013, and PAN-149822</div></td>', "lxml"
    )
    assert split_bug_id_cell(soup.find("td")) == [
        "PAN-150170",
        "PAN-150013",
        "PAN-149822",
    ]


def test_split_bug_id_cell_keeps_trailing_fix_info_intact_without_sibling_divs():
    """The 'EPM-4616Resolved in 25.3' shape must stay unsplit even when it
    reaches the splitter as a single raw value with no comma/and
    separators to trip on."""
    soup = BeautifulSoup('<td><div class="p">EPM-4616Resolved in 25.3</div></td>', "lxml")
    assert split_bug_id_cell(soup.find("td")) == ["EPM-4616Resolved in 25.3"]


def test_split_bug_id_cell_keeps_id_and_prose_with_comma_intact():
    """A single id followed by a comma-separated prose fragment must not be
    split — only every-part-is-a-bug-id cells are split."""
    soup = BeautifulSoup('<td><div class="p">PAN-99999, see notes below</div></td>', "lxml")
    assert split_bug_id_cell(soup.find("td")) == ["PAN-99999, see notes below"]


def test_split_bug_id_cell_composes_sibling_divs_with_and_joined_pair():
    """The two shapes must compose: sibling div.p elements where one of
    them itself holds an 'and'-joined pair of ids."""
    soup = BeautifulSoup(
        '<td><div class="p">LST-15102 and LST-15123</div><div class="p">LST-15200</div></td>',
        "lxml",
    )
    assert split_bug_id_cell(soup.find("td")) == [
        "LST-15102",
        "LST-15123",
        "LST-15200",
    ]


def test_split_bug_id_cell_splits_ids_fused_by_and_with_no_whitespace():
    """The real-world shape (AI Access Security known-issues page): inline
    elements around "and" collapse under get_text(strip=True), leaving no
    whitespace at all — "LST-15102andLST-15123", not "... and ...". A
    separator split can't see this; extract-and-verify-residue must."""
    soup = BeautifulSoup('<td><div class="p">LST-15102andLST-15123</div></td>', "lxml")
    assert split_bug_id_cell(soup.find("td")) == ["LST-15102", "LST-15123"]


def test_split_bug_id_cell_splits_ids_fused_with_no_separator_at_all():
    """The real-world shape (panos known-issues page): two ids with no
    separator whatsoever once inline elements collapse —
    "PAN-212726PAN-211519"."""
    soup = BeautifulSoup('<td><div class="p">PAN-212726PAN-211519</div></td>', "lxml")
    assert split_bug_id_cell(soup.find("td")) == ["PAN-212726", "PAN-211519"]


def test_split_bug_id_cell_keeps_pan_os_version_list_intact():
    """A comma/and-joined list of PAN-OS *version* strings (real fix_info
    data, not bug ids) must not be split — "PAN-OS" fails the bug-id
    pattern (no digits after the hyphen), so this yields zero matches and
    is the nastiest near-miss for the residue rule."""
    soup = BeautifulSoup(
        '<td><div class="p">PAN-OS 10.2.7, 10.2.7-h1, and 10.2.8</div></td>', "lxml"
    )
    assert split_bug_id_cell(soup.find("td")) == ["PAN-OS 10.2.7, 10.2.7-h1, and 10.2.8"]


def test_split_bug_id_cell_keeps_pan_os_version_and_fix_text_intact():
    """Same near-miss as above, in the "<version>Resolved in ..." shape
    that get_text(strip=True) produces when no separator existed at all."""
    soup = BeautifulSoup(
        '<td><div class="p">PAN-OS 11.2.4-h4 onlyThis issue is...</div></td>', "lxml"
    )
    assert split_bug_id_cell(soup.find("td")) == ["PAN-OS 11.2.4-h4 onlyThis issue is..."]


def test_split_bug_id_cell_keeps_two_adjacent_ids_intact_when_one_is_not_a_real_id():
    """The reviewer's construction: two adjacent <span class="ph
    uicontrol"> elements fuse to "PAN-262287FIPS140-2". The old looser
    pattern ([A-Z][A-Z0-9]*-\\d+) matches both "PAN-262287" and
    "FIPS140-2" (a digit in the prefix, one digit after the hyphen),
    leaving empty residue and fabricating a bogus id. The tightened
    pattern ([A-Z]+-\\d{3,}) rejects "FIPS140-2" on both counts, so this
    must stay unsplit."""
    soup = BeautifulSoup(
        '<td class="entry">'
        '<span class="ph uicontrol">PAN-262287</span>'
        '<span class="ph uicontrol">FIPS140-2</span>'
        "</td>",
        "lxml",
    )
    assert split_bug_id_cell(soup.find("td")) == ["PAN-262287FIPS140-2"]


def test_split_bug_id_cell_keeps_real_id_fused_to_standards_token_intact():
    """A real id fused to a standards/version-style token of similar
    shape (an early, short RFC reference — RFC 91 is a real, short RFC
    number) must not be mistaken for a second bug id. Unlike
    "FIPS140-2" (digit in the prefix), "RFC-91" has a letters-only
    prefix, so this pins the digit-count floor (\\d{3,}) in isolation:
    a longer numeric reference like "RFC-2119" is, by the corpus
    evidence the floor is based on, genuinely indistinguishable in
    shape from a real bug id and is out of scope for shape-only
    filtering."""
    soup = BeautifulSoup(
        '<td class="entry">'
        '<span class="ph uicontrol">PAN-123456</span>'
        '<span class="ph uicontrol">RFC-91</span>'
        "</td>",
        "lxml",
    )
    assert split_bug_id_cell(soup.find("td")) == ["PAN-123456RFC-91"]


def test_split_bug_id_cell_keeps_real_id_fused_to_short_digit_token_intact():
    """An id-shaped token with only 1-2 digits after the hyphen, fused to
    a real bug id, must not be split out as a second id — real ids never
    have fewer than 3 digits after the hyphen (measured across all
    11,439 distinct ids in assets/bugdb.json)."""
    soup = BeautifulSoup(
        '<td class="entry">'
        '<span class="ph uicontrol">PAN-262287</span>'
        '<span class="ph uicontrol">AB-7</span>'
        "</td>",
        "lxml",
    )
    assert split_bug_id_cell(soup.find("td")) == ["PAN-262287AB-7"]


def test_split_bug_id_cell_recovers_id_living_outside_div_p():
    """The panos known-issues page puts one id in a <span class="ph
    uicontrol"> and the other in a sibling <div class="p"> — a third
    distinct shape beyond the two already covered. find_all("div",
    class_="p") only ever sees the div.p side, so both ids must still be
    recovered (and neither must leak into the other's fix_info) via the
    whole-cell-text fallback."""
    soup = BeautifulSoup(
        '<td class="entry">'
        '<span class="ph uicontrol">PAN-212726</span>'
        '<div class="p">PAN-211519</div>'
        "</td>",
        "lxml",
    )
    assert split_bug_id_cell(soup.find("td")) == ["PAN-212726", "PAN-211519"]
