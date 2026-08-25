"""What the screens actually put on the page (citation plan phase 5).

The judgement lives in `gui.citation_display`, which is tested directly; this module
exists because a correct decision that never reaches the DOM is not a feature, and until
now nothing in this project rendered a NiceGUI page at all. It builds the element tree
outside any client — `render()` only needs a slot to build into — and reads the labels
back, which is enough to catch a row that stops being drawn or a finding that is computed
and then dropped.

Deliberately about presence and wording, not layout. Styling is not the sort of thing a
test should freeze, but "this reference is cited nowhere" appearing on screen is.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from nicegui import ui

from refcheck.extraction.citation_matching import CitationMatch, MatchStatus
from refcheck.extraction.document_artifact import DocumentArtifact, SourceAnchor
from refcheck.gui.models import ReferenceResult
from refcheck.gui.real_pipeline import (
    CITATIONS_FAILED,
    CITATIONS_NONE_DETECTED,
    CITATIONS_NOT_RUN,
    CITATIONS_OK,
)
from refcheck.webui.components import citation_context
from refcheck.webui.pages import manual_review, references
from refcheck.webui.state import AppState

_ACTIONS = SimpleNamespace(refresh_content=lambda: None)


def _reference(n: int) -> ReferenceResult:
    return ReferenceResult(
        n=n, raw=f"Author {n}. (2020). A title.", title=f"A title {n}", doi=f"10.1/{n}",
        status="verified", confidence=0.9,
    )


def _resolved(n: int) -> CitationMatch:
    return CitationMatch(
        marker_text="(Author, 2020)", tier="tier0", status=MatchStatus.RESOLVED, reference_n=n
    )


def _texts(element) -> list[str]:
    found = []
    text = getattr(element, "text", None)
    if isinstance(text, str) and text.strip():
        found.append(text.strip())
    # Badges are `ui.html`, which carries its content in innerHTML rather than in `text`.
    # Without this, a badge could stop being drawn and every assertion here would still
    # pass — and the retraction marking on a collapsed row *is* a badge.
    inner = element._props.get("innerHTML") if hasattr(element, "_props") else None
    if isinstance(inner, str) and inner.strip():
        found.append(inner.strip())
    for slot in element.slots.values():
        for child in slot.children:
            found.extend(_texts(child))
    return found


def _render(matches, run_status, *, count: int = 2, expanded: int | None = None) -> list[str]:
    state = AppState()
    state.results = [_reference(n) for n in range(1, count + 1)]
    state.citation_matches = tuple(matches)
    state.citation_run_status = run_status
    state.ref_expanded_n = expanded
    root = ui.column()
    with root:
        references.render(state, _ACTIONS)
    return _texts(root)


def test_the_screen_says_what_the_citation_search_established():
    rendered = _render([_resolved(1)], CITATIONS_OK)

    assert "1 in-text citation read — 1 reference with no citation found" in rendered


def test_an_uncited_reference_is_flagged_on_its_collapsed_row():
    """A reviewer scanning the list has to see this without expanding anything —
    reference 2 is cited nowhere in the manuscript and reference 1 is."""
    rendered = _render([_resolved(1)], CITATIONS_OK)

    assert rendered.count("no in-text citation found") == 1


def test_the_expanded_detail_carries_the_count_as_a_number():
    """A count, not a sentence: it sits directly under "Cited by", and a numeric column
    reading "Cited 2 times in this manuscript" reads as a different kind of fact."""
    rendered = _render([_resolved(1), _resolved(1)], CITATIONS_OK, expanded=1)

    assert _field(rendered, "Cited in text") == "2"


def test_the_in_text_figure_is_labelled_apart_from_openalex_citations():
    """Both are on the same panel and mean opposite directions; the plan called the
    collision out before either was rendered."""
    rendered = _render([_resolved(1)], CITATIONS_OK, expanded=1)

    assert "Cited by" in rendered
    assert "Cited in text" in rendered


@pytest.mark.parametrize(
    "run_status", [CITATIONS_NONE_DETECTED, CITATIONS_NOT_RUN, CITATIONS_FAILED]
)
def test_no_reference_is_flagged_when_the_search_cannot_support_it(run_status):
    """The whole point of the fourth state. Every reference is uncited by the arithmetic
    in all three of these, and none of them is evidence about the manuscript."""
    rendered = _render((), run_status)

    assert "no in-text citation found" not in rendered


@pytest.mark.parametrize(
    "run_status", [CITATIONS_NONE_DETECTED, CITATIONS_NOT_RUN, CITATIONS_FAILED]
)
def test_the_screen_says_why_rather_than_going_blank(run_status):
    """An empty space reads as "no citation problems" to anyone who is not thinking about
    run statuses, which is everyone using this screen."""
    rendered = _render((), run_status)

    assert any("in-text citation" in line.lower() for line in rendered)


def test_a_manuscript_that_cites_everything_reports_no_findings():
    rendered = _render([_resolved(1), _resolved(2)], CITATIONS_OK)

    assert "2 in-text citations read" in rendered
    assert "no in-text citation found" not in rendered


# --------------------------------------------------------------------------------------
# The manual review queue
# --------------------------------------------------------------------------------------


def _render_review(matches, run_status) -> list[str]:
    state = AppState()
    state.results = [
        ReferenceResult(
            n=n, raw=f"Author {n}. (2020). A title.", title="—", doi="no match",
            status="review", confidence=0.5,
        )
        for n in (1, 2)
    ]
    state.citation_matches = tuple(matches)
    state.citation_run_status = run_status
    root = ui.column()
    with root:
        manual_review.render(state, _ACTIONS)
    return _texts(root)


def test_the_review_queue_says_how_the_manuscript_uses_a_doubtful_reference():
    """The queue's whole job is deciding about references no lookup could confirm, and
    "the manuscript never cites it" is evidence for that decision that appears nowhere
    else in the queue."""
    rendered = _render_review([_resolved(1)], CITATIONS_OK)

    assert "Cited once in this manuscript" in rendered


def test_the_review_queue_makes_no_citation_claim_when_the_search_did_not_run():
    rendered = _render_review((), CITATIONS_NOT_RUN)

    assert "No in-text citation found for this reference" not in rendered
    assert "The in-text citation search did not run" in rendered


# --------------------------------------------------------------------------------------
# The context viewer — the one place manuscript text renders
# --------------------------------------------------------------------------------------

_BODY_LINES = [
    "An opening sentence that runs on for a while so the snippet has something to be cut "
    "out of, and then the claim itself. The effect replicates (Author, 2020) in every "
    "sample we looked at, which is the sentence a reviewer wants to read.",
    "",
    "A second paragraph that has nothing to do with any of this and must never appear.",
]


def _artifact() -> DocumentArtifact:
    return DocumentArtifact.from_lines(
        _BODY_LINES, raw_text="\n".join(_BODY_LINES), parser="test"
    )


def _anchor_start() -> int:
    return _artifact().body_text.index("(Author, 2020)")


def _passage(rendered: list[str]) -> str:
    """The rendered passage, which is HTML because the citation marker is highlighted
    inside it."""
    return next(line for line in rendered if "The effect replicates" in line)


def _with_context(show: bool = True, *, expanded=None, expanded_row: int | None = 1) -> tuple[AppState, list[str]]:
    artifact = _artifact()
    start = artifact.body_text.index("(Author, 2020)")
    anchor = SourceAnchor(
        start=start,
        end=start + len("(Author, 2020)"),
        paragraph_index=0,
        source_line=0,
    )
    state = AppState()
    state.results = [_reference(1)]
    state.citation_matches = (
        CitationMatch(
            marker_text="(Author, 2020)", tier="tier0", status=MatchStatus.RESOLVED,
            reference_n=1, anchor=anchor,
        ),
    )
    state.citation_run_status = CITATIONS_OK
    state.document_artifact = artifact
    state.expanded_contexts = set(expanded or ())
    state.ref_expanded_n = expanded_row
    root = ui.column()
    with root:
        references.render(state, _ACTIONS)
    return state, _texts(root)


def test_a_passage_only_renders_for_the_reference_whose_row_is_open():
    """The gate that used to hide these was removed on request 2026-08-11, so the row's
    own expansion is what limits how much manuscript text is on screen at once."""
    _, rendered = _with_context(show=True, expanded_row=None)

    assert not any("The effect replicates" in line for line in rendered)


def test_the_collapsed_passage_is_a_whole_sentence():
    """Not a character window. The reviewer is being asked whether the citation belongs
    where it sits, which cannot be judged from a fragment starting mid-word."""
    _, rendered = _with_context(show=True)
    passage = _passage(rendered)

    assert passage.startswith("… The effect replicates")
    # No trailing ellipsis: this sentence ends the paragraph, so nothing was cut after it,
    # and the leading one is there because the sentence before it was.
    assert passage.rstrip().endswith("a reviewer wants to read.")
    assert "An opening sentence" not in passage
    assert "second paragraph" not in passage


def test_the_citation_marker_is_marked_inside_the_passage():
    """The reviewer should not have to find the citation again by eye in a hundred
    characters of prose. Cut by the anchor's own offsets rather than by searching for the
    marker text, which would find the wrong occurrence when a sentence cites twice."""
    _, rendered = _with_context(show=True)
    passage = _passage(rendered)

    assert "<span" in passage
    assert passage.index("<span") < passage.index("(Author, 2020)")


def test_the_manuscripts_own_text_is_escaped_before_it_reaches_the_html():
    """The passage is untrusted input going into an HTML sink."""
    lines = ["A claim <script>alert(1)</script> about (Author, 2020) here."]
    artifact = DocumentArtifact.from_lines(lines, raw_text=lines[0], parser="test")
    start = artifact.body_text.index("(Author, 2020)")
    anchor = SourceAnchor(start=start, end=start + 14, paragraph_index=0, source_line=0)
    state = AppState()
    state.results = [_reference(1)]
    state.citation_matches = (
        CitationMatch(
            marker_text="(Author, 2020)", tier="tier0", status=MatchStatus.RESOLVED,
            reference_n=1, anchor=anchor,
        ),
    )
    state.citation_run_status = CITATIONS_OK
    state.document_artifact = artifact
    state.ref_expanded_n = 1
    root = ui.column()
    with root:
        references.render(state, _ACTIONS)
    passage = next(line for line in _texts(root) if "A claim" in line)

    assert "<script>" not in passage
    assert "&lt;script&gt;" in passage


def test_expanding_gives_the_paragraph_and_not_its_neighbour():
    """Both depths clip to the anchor's own paragraph, so a reviewer who asks for more
    context gets the passage's own paragraph and never the next one."""
    _, rendered = _with_context(show=True, expanded={(1, _anchor_start())})
    passage = _passage(rendered)

    assert passage.startswith("An opening sentence")
    assert "second paragraph" not in passage
    assert not passage.startswith("… ")


def test_only_the_first_few_passages_are_drawn():
    """A reference cited a dozen times would otherwise turn one table row into a page of
    prose, and the twelfth passage is not what anyone opened the row for."""
    artifact = _artifact()
    starts = [
        artifact.body_text.index("An opening"),
        artifact.body_text.index("the claim itself"),
        artifact.body_text.index("(Author, 2020)"),
        artifact.body_text.index("which is the sentence"),
    ]
    state = AppState()
    state.results = [_reference(1)]
    state.citation_matches = tuple(
        CitationMatch(
            marker_text="(Author, 2020)", tier="tier0", status=MatchStatus.RESOLVED,
            reference_n=1,
            anchor=SourceAnchor(start=s, end=s + 5, paragraph_index=0, source_line=0),
        )
        for s in starts
    )
    state.citation_run_status = CITATIONS_OK
    state.document_artifact = artifact
    state.ref_expanded_n = 1
    root = ui.column()
    with root:
        references.render(state, _ACTIONS)
    rendered = _texts(root)

    assert citation_context.VISIBLE_PLACES == 3
    assert "Show 1 more" in rendered

    state.expanded_place_lists = {1}
    root = ui.column()
    with root:
        references.render(state, _ACTIONS)

    assert "Show 1 more" not in _texts(root)


def test_the_export_keeps_its_own_gate_even_though_the_screen_lost_one():
    """Removing the on-screen gate did not remove the other one. A file outlives the
    session it came from, which is the distinction that survived the change."""
    from refcheck.gui.report_builder import DEFAULT_EXPORT_INCLUDED

    assert DEFAULT_EXPORT_INCLUDED["citation_passages"] is False


# --------------------------------------------------------------------------------------
# The reference detail card
# --------------------------------------------------------------------------------------


def _card(**overrides) -> list[str]:
    fields = dict(
        n=1, raw="Borsboom, D. et al. (2021). Network analysis.", title="Network analysis",
        doi="10.1038/s43586-021-00055-w", status="verified", confidence=0.98,
        source="Crossref (direct DOI)", queried="14:14",
    )
    fields.update(overrides)
    state = AppState()
    state.results = [ReferenceResult(**fields)]
    state.citation_run_status = CITATIONS_OK
    state.ref_expanded_n = 1
    root = ui.column()
    with root:
        references.render(state, _ACTIONS)
    return _texts(root)


def _field(rendered: list[str], label: str) -> str:
    """The value drawn next to a label in the detail grid, which renders as label then
    value in document order."""
    return rendered[rendered.index(label) + 1]


def test_both_sources_citation_counts_are_shown_and_attributed():
    """They disagree substantially — measured, 8,121 (Crossref) against 10,653 (OpenAlex)
    for the same DOI — because each counts only the citing works it indexes. Showing one
    number would make the reader's answer depend on which source won the match, with
    nothing on screen to say so."""
    rendered = _card(citations=10653, citations_crossref=8121, citations_openalex=10653)

    assert _field(rendered, "Cited by") == "8,121 (Crossref) / 10,653 (OpenAlex)"


def test_one_source_answering_shows_one_attributed_figure():
    rendered = _card(citations=4200, citations_crossref=4200)

    assert _field(rendered, "Cited by") == "4,200 (Crossref)"


def test_a_cited_work_reports_its_citation_count():
    assert _field(_card(citations=4200, citations_openalex=4200), "Cited by") == "4,200 (OpenAlex)"


def test_a_count_nobody_reported_is_not_printed_as_zero():
    """What the screenshot caught: a heavily-cited paper displayed as "Cited by 0", because
    no lookup ever captured a count and the field defaulted to zero. A dash says "we have
    no figure"; a zero says "nobody cites this", and only one of those was ever true."""
    assert _field(_card(citations=None), "Cited by") == "—"


def test_a_genuine_zero_is_still_shown_as_zero():
    """The other half: a real, reported zero is a fact about the work and must survive."""
    assert _field(_card(citations=0, citations_openalex=0), "Cited by") == "0 (OpenAlex)"


def test_the_card_shows_the_year_and_outlet_it_matched():
    """Both were carried through the whole pipeline and never displayed, leaving the card
    unable to answer whether this is the right work — the same title exists as a preprint,
    a chapter and an article in different years."""
    rendered = _card(year=2021, outlet="Nature Reviews Methods Primers")

    assert "2021 · Nature Reviews Methods Primers" in rendered


def _retraction_lines(rendered: list[str]) -> list[str]:
    """Everything the *reference* says about retraction. The metric card above the table
    is always headed "Retraction warnings" and is a count, not a claim about any one
    reference, so it is excluded here rather than allowed to satisfy these assertions."""
    return [
        line
        for line in rendered
        if "retract" in line.lower() and "Retraction warnings" not in line
    ]


def test_nothing_is_said_about_retraction_when_none_was_reported():
    """It used to read "Retraction: none" on every reference — an all-clear issued on the
    strength of a default value. Silence here means "no retraction was reported", and the
    card must not upgrade that to "this work is fine"."""
    assert _retraction_lines(_card()) == []


def test_an_unchecked_reference_is_never_shown_as_clean():
    """The tri-state's whole purpose: None is "nobody answered", not "clear"."""
    assert _retraction_lines(_card(retracted=None, status="unchecked")) == []


def test_a_retraction_is_announced_before_anything_else_about_the_work():
    """A banner, not a field. A grid row is read at the same speed as "Cited by", and this
    is the answer to whether the work should be cited at all."""
    rendered = _card(retracted=True)

    assert "⚠ RETRACTED" in rendered
    assert "This work has been retracted and should not be cited as evidence." in rendered
    # Above the matched work's title, which is the first thing the card otherwise shows.
    assert rendered.index("⚠ RETRACTED") < rendered.index("Network analysis")


def test_the_retraction_notice_is_linked_so_the_claim_can_be_checked():
    """A retraction is an accusation about someone's published work. The reviewer has to
    be able to read the notice rather than take this screen's word for it."""
    rendered = _card(retracted=True, retraction_doi="10.1016/s0140-6736(10)60175-4")

    assert "read the retraction notice" in rendered


def test_a_retraction_without_a_notice_still_names_its_source():
    """OpenAlex reports the fact and not the notice, so the claim stays traceable even
    when there is no document to link to."""
    rendered = _card(retracted=True, retraction_doi="", source="OpenAlex")

    assert "reported by OpenAlex" in rendered


def test_a_retracted_reference_is_marked_without_expanding_anything():
    """The status badge cannot carry this — a retracted work is usually *verified*, which
    is the badge it wears — so the collapsed row has to say it itself."""
    state = AppState()
    state.results = [
        ReferenceResult(
            n=1, raw="A retracted paper.", title="T", doi="10.1/x", status="verified",
            confidence=0.99, retracted=True,
        )
    ]
    state.citation_run_status = CITATIONS_OK
    root = ui.column()
    with root:
        references.render(state, _ACTIONS)
    rendered = _texts(root)

    assert any("RETRACTED" in line for line in rendered)
    assert "▸ 01" in rendered  # still collapsed


def test_the_retraction_card_counts_only_confirmed_retractions():
    from refcheck.gui.metric_cards import compute_metrics

    results = [
        ReferenceResult(n=1, raw="a", title="t", doi="d", status="verified", confidence=1.0, retracted=True),
        ReferenceResult(n=2, raw="b", title="t", doi="d", status="verified", confidence=1.0, retracted=False),
        ReferenceResult(n=3, raw="c", title="t", doi="d", status="unchecked", confidence=0.0, retracted=None),
    ]

    assert compute_metrics(results).n_retracted == 1


def test_the_retraction_card_filters_the_list_to_the_retracted_ones():
    """A count a reviewer cannot act on is the least useful way to report a retraction."""
    state = AppState()
    state.results = [
        ReferenceResult(n=1, raw="clean paper", title="t", doi="10.1/a", status="verified", confidence=1.0),
        ReferenceResult(
            n=2, raw="retracted paper", title="t", doi="10.1/b", status="verified",
            confidence=1.0, retracted=True,
        ),
    ]
    state.citation_run_status = CITATIONS_OK
    state.ref_tab = "retracted"
    root = ui.column()
    with root:
        references.render(state, _ACTIONS)
    rendered = _texts(root)

    assert "retracted paper" in rendered
    assert "clean paper" not in rendered


def test_the_lookup_source_and_time_share_one_row():
    assert "Crossref (direct DOI) · 14:14" in _card()


# --------------------------------------------------------------------------------------
# Candidate cards in the review queue
# --------------------------------------------------------------------------------------


def _with_candidate(**overrides) -> list[str]:
    from refcheck.gui.models import Candidate

    fields = dict(
        title="Plato's Heaven: A User's Guide", doi="10.5040/9781350878907",
        similarity=0.75, year=2013, source="Crossref", outlet="Bloomsbury",
    )
    fields.update(overrides)
    state = AppState()
    state.results = [
        ReferenceResult(
            n=1, raw="Author. (2013). Plato's Heaven.", title="—", doi="no match",
            status="review", confidence=0.75, candidates=(Candidate(**fields),),
        )
    ]
    state.citation_run_status = CITATIONS_OK
    state.review_expanded_n = 1
    root = ui.column()
    with root:
        manual_review.render(state, _ACTIONS)
    return _texts(root)


def test_a_candidate_says_where_and_when_it_was_published():
    """Year and venue are what separate a preprint, a chapter and an article sharing a
    title — which is exactly the identification this screen is asking the reviewer for."""
    rendered = _with_candidate()

    assert any("2013 · Bloomsbury" in line for line in rendered)


def test_a_candidate_carries_its_citation_counts():
    rendered = _with_candidate(citations_crossref=12, citations_openalex=15)

    assert any("cited by 12 (Crossref) / 15 (OpenAlex)" in line for line in rendered)


def test_a_candidate_shows_its_subject_terms():
    rendered = _with_candidate(topics=("Ancient philosophy",), keywords=("Metaphysics",))

    assert "Ancient philosophy" in rendered
    assert "Metaphysics" in rendered


def test_a_retracted_candidate_warns_before_it_can_be_confirmed():
    """The one that cannot be left out: confirming a candidate writes it into the
    reference list, so a retracted work must not be selectable in silence."""
    rendered = _with_candidate(retracted=True)

    warning = next(line for line in rendered if "RETRACTED" in line)
    assert "do not confirm" in warning
    # Above the title, like the reference card's banner.
    assert rendered.index(warning) < rendered.index("Plato's Heaven: A User's Guide")


def test_a_candidate_nobody_flagged_carries_no_warning():
    rendered = _with_candidate(retracted=None)

    assert not [line for line in rendered if "RETRACTED" in line]


def test_a_candidate_still_shows_its_similarity_score():
    """The reason it is a candidate rather than a match, and it stays on the card."""
    rendered = _with_candidate()

    assert any("Title similarity to this citation: 0.75" in line for line in rendered)


def test_a_marker_split_across_a_block_boundary_is_shown_whole_at_both_depths():
    """The context viewer's half of the straddling-span fix.

    `_passage_slice` read the anchor's paragraph directly rather than going through the
    artifact, so it kept cutting a straddling marker in half after `sentence_bounds` and
    `paragraph_text` stopped — and once the collapsed depth covered both paragraphs and the
    expanded one did not, clicking "expand" made the passage *shrink*.

    The marker below is a grouped parenthetical split across a block boundary, which is
    what PDF extraction produces when a citation group falls across a column or page break.
    """
    from refcheck.extraction.document_artifact import DocumentArtifact
    from refcheck.extraction.intext_signals import detect_citations
    from refcheck.webui.components.citation_context import _passage_html, _passage_slice

    lines = ["As several have shown (Doe, 2020;", "", "Roe, 2019) the effect is robust."]
    artifact = DocumentArtifact.from_lines(lines, raw_text="\n".join(lines), parser="test")
    citation = next(c for c in detect_citations(artifact.body_text) if "Roe" in c.marker_text)
    anchor = artifact.anchor_for(citation.start, citation.end)
    assert anchor is not None

    for expanded in (False, True):
        start, end = _passage_slice(artifact, anchor, expanded)
        # The passage must contain the marker it exists to highlight.
        assert start <= anchor.start and end >= anchor.end
        assert "Roe, 2019)" in _passage_html(artifact, anchor, expanded)

    # Expanding may never show less than collapsing did.
    collapsed = _passage_slice(artifact, anchor, False)
    expanded_slice = _passage_slice(artifact, anchor, True)
    assert expanded_slice[0] <= collapsed[0] and expanded_slice[1] >= collapsed[1]


def test_the_depth_label_says_how_much_the_expansion_actually_shows():
    """PR #60's review. The label was fixed text — "full paragraph", "click for the
    paragraph" — while the expansion it describes now covers every paragraph a straddling
    marker runs into. In exactly the case the straddling fix exists for, the UI understated
    what was on screen and promised the wrong thing on click.

    Derived from the bounds rather than blurred to "context", so the ordinary case keeps the
    specific word: a reader is better told "paragraph" when a paragraph is what they get.
    """
    from refcheck.extraction.document_artifact import DocumentArtifact
    from refcheck.extraction.intext_signals import detect_citations
    from refcheck.webui.components.citation_context import _depth_label

    def label(lines, expanded):
        artifact = DocumentArtifact.from_lines(lines, raw_text="\n".join(lines), parser="test")
        citation = detect_citations(artifact.body_text)[0]
        anchor = artifact.anchor_for(citation.start, citation.end)
        return _depth_label(artifact, anchor, expanded)

    straddling = ["As several have shown (Doe, 2020;", "", "Roe, 2019) the effect is robust."]
    assert label(straddling, True) == "all 2 paragraphs · click to collapse"
    assert label(straddling, False) == "sentence · click for all 2 paragraphs"

    # The common case is untouched — the fix must not cost the specific word everywhere.
    ordinary = ["Previous.", "", "A marker (Author, 2020) here.", "", "Next."]
    assert label(ordinary, True) == "full paragraph · click to collapse"
    assert label(ordinary, False) == "sentence · click for the paragraph"
