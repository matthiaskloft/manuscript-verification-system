"""What the screens and the report are allowed to say about the list's completeness.

The distinction every test here is defending: an unchecked reference list and a whole one
must never read the same. That is a wording problem as much as a data problem — the audit
already keeps `read` and `complete` apart, and this is where that separation either
survives contact with a sentence or does not.
"""

from __future__ import annotations

from openrefcheck.extraction.reference_list_audit import NOT_AUDITED, ReferenceListAudit
from openrefcheck.gui.reference_list_display import reference_list_note


def test_an_unchecked_list_produces_no_note_at_all():
    """Not a reassurance and not a warning. A DOCX, or a PDF whose bibliography heading
    was never found, would otherwise carry a caveat on every check — and a caveat a
    reviewer sees every time is one they stop reading before it means something."""
    note = reference_list_note(NOT_AUDITED, extracted_count=30)

    assert not note
    assert note.headline == ""
    assert not note.complete


def test_a_whole_list_says_so_with_its_count():
    note = reference_list_note(ReferenceListAudit(read=True, numbered=True, printed_count=30), 30)

    assert note.complete
    assert note.headline == "All 30 references match the list this document prints."
    assert note.detail == ""


def test_a_short_numbered_list_states_both_totals_and_names_what_is_missing():
    note = reference_list_note(
        ReferenceListAudit(read=True, numbered=True, printed_count=30, missing=(4, 17)), 28
    )

    assert not note.complete
    assert "numbers 30 entries" in note.headline and "28 were extracted" in note.headline
    assert "4 and 17" in note.detail


def test_an_unnumbered_list_gets_no_total_it_did_not_read():
    """The Tier 0 splitter's count is wrong by one on this project's own Chicago fixture,
    so the headline for an unnumbered list carries no number. The finding still lands —
    it just rests on the alignment rather than on a total."""
    note = reference_list_note(ReferenceListAudit(read=True, merged=(25,)), 29)

    assert not note.complete
    assert "29" not in note.headline and "30" not in note.headline
    assert "reference 25 covers more than one printed entry" in note.detail


def test_a_fragment_is_described_as_a_fragment_rather_than_as_a_reference():
    note = reference_list_note(ReferenceListAudit(read=True, unmatched=(28,)), 31)

    assert "reference 28 matches no printed entry" in note.detail


def test_several_findings_are_all_reported_in_one_note():
    note = reference_list_note(
        ReferenceListAudit(read=True, numbered=True, printed_count=30, merged=(4,), unmatched=(9,), missing=(12,)),
        29,
    )

    assert "did not turn up" in note.detail
    assert "reference 4 covers" in note.detail
    assert "reference 9 matches" in note.detail


def test_a_long_run_of_numbers_is_truncated_and_says_how_many_it_left_out():
    note = reference_list_note(
        ReferenceListAudit(read=True, numbered=True, printed_count=30, missing=tuple(range(1, 11))), 20
    )

    assert "1, 2, 3, 4, 5, 6 and 4 more" in note.detail
    # The count stays exact whatever the listing does with it.
    assert "10 printed entries" in note.detail


def test_one_missing_entry_reads_as_one_rather_than_as_a_plural():
    note = reference_list_note(
        ReferenceListAudit(read=True, numbered=True, printed_count=30, missing=(7,)), 29
    )

    assert "1 printed entry did not turn up" in note.detail
