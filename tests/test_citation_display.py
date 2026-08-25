"""What a screen is allowed to say about in-text citations (citation plan phase 5).

The pages themselves have no test harness in this project, which is the reason this layer
is a module rather than logic inside a `render()`. Everything asserted here is a claim a
reviewer will read and act on.
"""

from __future__ import annotations

import pytest

from refcheck.extraction.citation_matching import CitationMatch, MatchStatus
from refcheck.extraction.document_artifact import SourceAnchor
from refcheck.gui import citation_display as display
from refcheck.gui.real_pipeline import (
    CITATIONS_FAILED,
    CITATIONS_NONE_DETECTED,
    CITATIONS_NONE_MATCHED,
    CITATIONS_NOT_RUN,
    CITATIONS_OK,
)


def _resolved(n: int, marker: str = "(Doe, 2020)") -> CitationMatch:
    return CitationMatch(marker_text=marker, tier="tier0", status=MatchStatus.RESOLVED, reference_n=n)


def _ambiguous(*candidates: int) -> CitationMatch:
    return CitationMatch(
        marker_text="(Smith, 2020)",
        tier="tier0",
        status=MatchStatus.AMBIGUOUS,
        candidates=tuple(candidates),
    )


def _orphaned(marker: str = "[9]") -> CitationMatch:
    return CitationMatch(marker_text=marker, tier="tier0", status=MatchStatus.ORPHANED)


def _unresolved(marker: str = "[15, p. 87") -> CitationMatch:
    return CitationMatch(marker_text=marker, tier="tier1", status=MatchStatus.UNRESOLVED)


# --------------------------------------------------------------------------------------
# The per-reference figure
# --------------------------------------------------------------------------------------


def test_a_reference_cited_three_times_says_so():
    records = display.per_reference([1, 2], [_resolved(1), _resolved(1), _resolved(1)], CITATIONS_OK)

    assert records[1].times_cited == 3
    assert records[1].label == "Cited 3 times in this manuscript"
    assert not records[1].uncited


def test_a_reference_cited_once_is_not_cited_1_times():
    """Wording, not arithmetic, and it is on screen next to every singly-cited entry."""
    records = display.per_reference([1], [_resolved(1)], CITATIONS_OK)

    assert records[1].label == "Cited once in this manuscript"


def test_a_reference_nothing_cites_is_flagged():
    records = display.per_reference([1, 2], [_resolved(1)], CITATIONS_OK)

    assert records[2].uncited
    assert records[2].times_cited == 0
    assert records[2].label == "No in-text citation found for this reference"


def test_every_reference_number_gets_a_record():
    """A row is rendered per reference whatever the matches say, so a missing key would
    be a crash or a silently different row on exactly the documents that matter."""
    records = display.per_reference([1, 2, 3, 4], [_resolved(2)], CITATIONS_OK)

    assert sorted(records) == [1, 2, 3, 4]


# --------------------------------------------------------------------------------------
# The states where no per-reference claim may be made
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "run_status",
    [CITATIONS_NONE_DETECTED, CITATIONS_NONE_MATCHED, CITATIONS_NOT_RUN, CITATIONS_FAILED],
)
def test_no_reference_is_called_uncited_when_the_search_cannot_support_it(run_status):
    """The fourth-state gap this phase opened with. A manuscript whose markers were never
    detected has every reference "uncited" by the arithmetic, and telling a reviewer that
    is a false accusation against the whole bibliography at once."""
    records = display.per_reference([1, 2, 3], (), run_status)

    assert [r.uncited for r in records.values()] == [False, False, False]


def test_a_search_that_found_nothing_reads_differently_from_one_that_never_ran():
    """Both have no matches. Only the status says which, and a reviewer acts differently
    on "this manuscript cites nothing" than on "we did not look"."""
    detected_nothing = display.per_reference([1], (), CITATIONS_NONE_DETECTED)[1]
    never_ran = display.per_reference([1], (), CITATIONS_NOT_RUN)[1]
    failed = display.per_reference([1], (), CITATIONS_FAILED)[1]

    assert detected_nothing.label != never_ran.label != failed.label
    assert detected_nothing.label != failed.label
    assert all(record.label for record in (detected_nothing, never_ran, failed))


def test_markers_read_but_none_matched_says_so_rather_than_saying_nothing_cites_this():
    """The wording carries the difference the state exists for.

    A reviewer reading "no in-text citation found for this reference" against a manuscript
    that plainly cites things goes looking at the writing. The failure is on this side —
    the markers were read and the reference list was what could not be matched against —
    and the label has to point there, or it sends the reviewer to correct something that
    is not wrong.
    """
    none_matched = display.per_reference([1], (), CITATIONS_NONE_MATCHED)[1]
    detected_nothing = display.per_reference([1], (), CITATIONS_NONE_DETECTED)[1]

    assert none_matched.label != detected_nothing.label
    assert "matched" in none_matched.label
    assert not none_matched.uncited


def test_an_unknown_run_status_is_read_as_did_not_run():
    """A status this module has not been taught is not evidence of anything, and the
    fallback must be the one that claims least — never a blank, and never "uncited"."""
    record = display.per_reference([1], (), "something-phase-6-added")[1]

    assert not record.uncited
    assert record.label == "The in-text citation search did not run"


# --------------------------------------------------------------------------------------
# Ambiguity is not a finding
# --------------------------------------------------------------------------------------


def test_a_reference_an_ambiguous_marker_might_cite_is_not_called_uncited():
    """The one status that exists to say "don't know" must not become the evidence for a
    finding. Kept in step with citation_matching's own rule rather than restated here."""
    records = display.per_reference([1, 2], [_ambiguous(1, 2)], CITATIONS_OK)

    assert not records[1].uncited and not records[2].uncited
    assert records[1].times_cited == 0
    assert records[1].label == "One citation may name this reference, but is ambiguous"


def test_two_ambiguous_markers_are_counted_as_two():
    records = display.per_reference([1, 2], [_ambiguous(1, 2), _ambiguous(1, 2)], CITATIONS_OK)

    assert records[1].possible == 2
    assert records[1].label == "2 citations may name this reference, but are ambiguous"


def test_the_unused_flag_agrees_with_citation_matching():
    """This module reads the rule from citation_matching rather than reimplementing it,
    and this is what pins that: a mapping of its own would be free to drift."""
    from refcheck.extraction.citation_matching import unused_reference_numbers

    numbers = [1, 2, 3, 4]
    matches = [_resolved(1), _ambiguous(2, 3), _orphaned()]
    records = display.per_reference(numbers, matches, CITATIONS_OK)

    assert tuple(n for n in numbers if records[n].uncited) == unused_reference_numbers(numbers, matches)


# --------------------------------------------------------------------------------------
# The document-level line
# --------------------------------------------------------------------------------------


def test_the_headline_leads_with_the_findings():
    summary = display.document_summary(
        [1, 2, 3], [_resolved(1), _orphaned(), _orphaned("[12]")], CITATIONS_OK
    )

    assert summary.orphaned == 2
    assert summary.uncited_references == (2, 3)
    assert summary.headline == (
        "3 in-text citations read — 2 naming a reference this list does not carry, "
        "2 references with no citation found"
    )


def test_a_clean_manuscript_gets_no_findings_in_its_headline():
    summary = display.document_summary([1], [_resolved(1)], CITATIONS_OK)

    assert summary.headline == "1 in-text citation read"
    assert summary.orphaned == 0
    assert summary.uncited_references == ()


def test_unresolved_markers_are_counted_but_are_not_a_finding():
    """"Cannot tell" is the honest answer for a marker GROBID truncated, and the live
    measurement leaves five of them on the synthetic corpus. It is not a defect in the
    manuscript and does not belong in the same sentence as one."""
    summary = display.document_summary([1], [_resolved(1), _unresolved()], CITATIONS_OK)

    assert summary.unresolved == 1
    assert "unresolved" not in summary.headline
    assert summary.headline == "2 in-text citations read"


@pytest.mark.parametrize(
    "run_status", [CITATIONS_NONE_DETECTED, CITATIONS_NOT_RUN, CITATIONS_FAILED]
)
def test_the_summary_claims_nothing_when_the_search_cannot_support_it(run_status):
    summary = display.document_summary([1, 2], (), run_status)

    assert summary.uncited_references == ()
    assert not summary.searched
    assert summary.headline


# --------------------------------------------------------------------------------------
# Where a reference is cited from
# --------------------------------------------------------------------------------------


def _anchored(n: int | None, *, status=MatchStatus.RESOLVED, candidates=(), start=10):
    return CitationMatch(
        marker_text="(Doe, 2020)",
        tier="tier0",
        status=status,
        reference_n=n,
        candidates=candidates,
        anchor=SourceAnchor(start=start, end=start + 11, paragraph_index=0, source_line=0),
    )


def test_a_resolved_match_with_no_anchor_offers_no_passage():
    """Locating and resolving are separate questions. A match that resolved without a
    position is still counted in "cited N times" and has no sentence to show, which is why
    the two numbers can differ without either being wrong."""
    places = display.places_for(1, [_resolved(1), _anchored(1)])

    assert len(places) == 1
    assert display.per_reference([1], [_resolved(1), _anchored(1)], CITATIONS_OK)[1].times_cited == 2


def test_an_ambiguous_markers_passage_is_offered_but_labelled():
    """The reviewer deciding an ambiguous marker is exactly who needs to read around it,
    and presenting it as a confirmed citation is the guess this project does not make."""
    match = _anchored(None, status=MatchStatus.AMBIGUOUS, candidates=(1, 2))
    places = display.places_for(1, [match])

    assert [p.certain for p in places] == [False]
    assert places[0].note == "may name this reference"


def test_confirmed_places_come_before_possible_ones():
    matches = [_anchored(None, status=MatchStatus.AMBIGUOUS, candidates=(1,), start=5), _anchored(1)]
    places = display.places_for(1, matches)

    assert [p.certain for p in places] == [True, False]


def test_another_references_citations_are_not_offered():
    places = display.places_for(2, [_anchored(1)])

    assert places == ()


def test_searched_is_what_a_screen_gates_on():
    assert display.document_summary([1], [_resolved(1)], CITATIONS_OK).searched
    assert not display.document_summary([1], (), CITATIONS_NONE_DETECTED).searched


# --------------------------------------------------------------------------------------
# The compact figure
# --------------------------------------------------------------------------------------


def test_the_figure_is_a_count():
    records = display.per_reference([1], [_resolved(1), _resolved(1)], CITATIONS_OK)

    assert records[1].figure == "2"


def test_a_reference_nothing_cites_shows_a_zero():
    records = display.per_reference([1, 2], [_resolved(1)], CITATIONS_OK)

    assert records[2].figure == "0"


def test_ambiguity_is_visible_in_the_figure_without_being_counted_as_a_citation():
    records = display.per_reference([1], [_ambiguous(1, 2)], CITATIONS_OK)

    assert records[1].figure == "0 (+1 ambiguous)"
    assert records[1].times_cited == 0


@pytest.mark.parametrize(
    "run_status", [CITATIONS_NONE_DETECTED, CITATIONS_NOT_RUN, CITATIONS_FAILED]
)
def test_an_unsearchable_run_shows_a_dash_not_a_zero(run_status):
    """A zero in that cell is a finding. "We could not answer" is not one, and the two
    must not share a rendering."""
    records = display.per_reference([1], (), run_status)

    assert records[1].figure == "—"
    assert not records[1].searched
