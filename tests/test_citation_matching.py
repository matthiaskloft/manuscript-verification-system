"""Behaviour of the matching engine (docs/plans/plan-in-text-citation-parsing.md, Phase 4).

Two things are being pinned here, and they pull in opposite directions. One is that a
marker naming a reference this document carries resolves to it, through whatever the
style did to the name on the way. The other is that a marker naming something else stays
unmatched — and stays unmatched in the *right way*, since "no such reference" (a finding)
and "cannot tell" (not a finding) are different answers the plan requires never to be
conflated.

Every fixture bibliography here uses entry text in a real style's shape rather than a
placeholder, because the whole author-date path is an argument about where a style puts
the surname, the initials and the date.
"""

from __future__ import annotations

import pytest

from openrefcheck.extraction.citation_matching import (
    SURNAME_MATCH_THRESHOLD,
    CitationMatch,
    MatchStatus,
    _MISSING_YEAR_PENALTY,
    _name_similarity,
    citation_counts,
    match_citations,
    unused_reference_numbers,
)
from openrefcheck.extraction.document_artifact import DocumentArtifact
from openrefcheck.extraction.engine_status import ENGINE_ANCHOR, ENGINE_GROBID
from openrefcheck.extraction.grobid import CitationContext
from openrefcheck.extraction.intext_signals import MarkerFamily, parse_marker
from openrefcheck.extraction.style_profile import compute_style_profile
from openrefcheck.extraction.tier0 import RawReferenceEntry


def _artifact(*paragraphs: str) -> DocumentArtifact:
    lines: list[str] = []
    for paragraph in paragraphs:
        if lines:
            lines.append("")
        lines.append(paragraph)
    return DocumentArtifact.from_lines(lines, raw_text="\n".join(lines), parser="test")


def _refs(*raws: str) -> list[RawReferenceEntry]:
    return [RawReferenceEntry(index, raw) for index, raw in enumerate(raws, start=1)]


def _match(text: str, *raws: str, **kwargs) -> tuple[CitationMatch, ...]:
    return match_citations(_artifact(text), _refs(*raws), **kwargs)


def _one(text: str, *raws: str, **kwargs) -> CitationMatch:
    matches = _match(text, *raws, **kwargs)
    assert len(matches) == 1, [m.marker_text for m in matches]
    return matches[0]


# --------------------------------------------------------------------------------------
# Author-date: resolving a name and a year
# --------------------------------------------------------------------------------------


def test_a_marker_resolves_to_the_entry_it_names():
    match = _one(
        "The effect replicates (Doe, 2020).",
        "Doe, J. (2020). A first study. Journal of Tests, 1(2), 3-14.",
        "Roe, A. (2019). A second study. Journal of Tests, 1(1), 1-2.",
    )

    assert (match.status, match.reference_n) == (MatchStatus.RESOLVED, 1)
    assert match.tier == ENGINE_ANCHOR
    assert match.family is MarkerFamily.AUTHOR_DATE


def test_a_narrative_marker_resolves_the_same_way_and_says_it_is_narrative():
    match = _one("Doe (2020) reported the effect.", "Doe, J. (2020). A first study.")

    assert (match.status, match.reference_n, match.narrative) == (MatchStatus.RESOLVED, 1, True)


def test_the_year_is_what_separates_two_works_by_the_same_author():
    matches = _match(
        "Both (Doe, 2020) and (Doe, 2015) apply.",
        "Doe, J. (2015). An early study.",
        "Doe, J. (2020). A later study.",
    )

    assert [(m.status, m.reference_n) for m in matches] == [
        (MatchStatus.RESOLVED, 2),
        (MatchStatus.RESOLVED, 1),
    ]


def test_a_year_the_bibliography_disagrees_with_is_not_a_match():
    """The strongest signal author-date matching has, and the one a surname-only matcher
    would throw away: the same author with the wrong year is a different work."""
    match = _one("As shown (Doe, 1999).", "Doe, J. (2020). A first study.")

    assert match.status is MatchStatus.ORPHANED
    assert match.reference_n is None


def test_a_letter_suffix_present_on_one_side_only_is_not_a_disagreement():
    """A marker prints "2020a" whenever the document cites two works from that year;
    whether the suffix survives into the extracted entry depends on the style."""
    match = _one("As shown (Doe, 2020a).", "Doe, J. (2020). A first study.")

    assert (match.status, match.reference_n) == (MatchStatus.RESOLVED, 1)


def test_two_different_letter_suffixes_are_a_disagreement():
    """The distinction the suffixes exist to make, so it has to be honoured in both
    directions — otherwise the disambiguation a style went to the trouble of printing
    resolves to whichever entry happens to be scored first."""
    matches = _match(
        "Compare (Doe, 2020a) with (Doe, 2020b).",
        "Doe, J. (2020a). An early one.",
        "Doe, J. (2020b). A later one.",
    )

    assert [(m.status, m.reference_n) for m in matches] == [
        (MatchStatus.RESOLVED, 1),
        (MatchStatus.RESOLVED, 2),
    ]


def test_an_entry_with_no_readable_date_still_matches_an_exact_name():
    """A missing date is this project's parsing failure far more often than the
    manuscript's, and treating it as a disagreement reports the reference as uncited."""
    match = _one("As shown (Doe, 2020).", "Doe, J. An entry whose date extraction lost.")

    assert (match.status, match.reference_n) == (MatchStatus.RESOLVED, 1)
    assert match.confidence < 1.0


def test_a_no_date_marker_matches_a_no_date_entry():
    match = _one("As shown (Doe, n.d.).", "Doe, J. (n.d.). An undated work.")

    assert (match.status, match.reference_n) == (MatchStatus.RESOLVED, 1)


def test_a_no_date_marker_does_not_match_a_dated_entry_by_the_same_author():
    match = _one("As shown (Doe, n.d.).", "Doe, J. (2020). A dated work.")

    assert match.status is MatchStatus.ORPHANED


# --------------------------------------------------------------------------------------
# Author-date: what a style does to a name on the way into the text
# --------------------------------------------------------------------------------------


def test_a_particle_dropped_from_the_in_text_form_still_matches():
    """Chicago renders "de Beauvoir" as "Beauvoir (2011)". Measured on the corpus in
    tests/test_intext_citation_recall.py, which also pins the opposite direction."""
    match = _one("Beauvoir (2011) argued otherwise.", "de Beauvoir, S. (2011). The second sex.")

    assert (match.status, match.reference_n) == (MatchStatus.RESOLVED, 1)


def test_a_particle_kept_in_the_in_text_form_still_matches():
    match = _one(
        "wie von der Veen (2019) gezeigt.", "von der Veen, D. (2019). Eine Untersuchung."
    )

    assert (match.status, match.reference_n) == (MatchStatus.RESOLVED, 1)


def test_a_diacritic_lost_in_extraction_still_matches():
    """pymupdf displaces or drops combining marks often enough that requiring the mark
    would cost real citations — so both sides are folded, neither privileged."""
    match = _one("As shown (Muller, 2019).", "Müller, K. (2019). Eine Studie.")

    assert (match.status, match.reference_n) == (MatchStatus.RESOLVED, 1)


def test_an_et_al_marker_resolves_on_its_first_author():
    match = _one(
        "As shown (Doe et al., 2020).",
        "Doe, J., Roe, A., & Fry, B. (2020). A collaborative study.",
    )

    assert (match.status, match.reference_n) == (MatchStatus.RESOLVED, 1)


def test_a_german_et_al_marker_resolves_the_same_way():
    match = _one(
        "wie gezeigt (Müller u. a., 2019).", "Müller, K., Schmidt, L., & Weber, T. (2019). Studie."
    )

    assert (match.status, match.reference_n) == (MatchStatus.RESOLVED, 1)


def test_a_marker_naming_an_author_the_bibliography_does_not_carry_is_orphaned():
    """The finding this feature exists to produce, and the one status that is one."""
    match = _one("As shown (Nobody, 1999).", "Doe, J. (2020). A first study.")

    assert match.status is MatchStatus.ORPHANED
    assert match.reference_n is None and match.candidates == ()


def test_a_reprint_cited_by_its_reprint_year_resolves_from_the_printed_entry():
    """The manuscript cites the entry's own date; GROBID's parse kept the original's.

    The APA fixture prints "Weber, M. (1930). The protestant ethic and the spirit of
    capitalism [Original work published 1905]." and the manuscript cites (Weber, 1930).
    Read whole, that entry carries both years. GROBID's structured parse keeps 1905 alone,
    and the year veto then dropped the pairing — so a manuscript that cited its own
    bibliography correctly was told it cited nothing. Found by the live Tier-1
    measurement, where four of five false orphans were this.

    The veto is not wrong; its premise was. It assumes the entry text holds every year the
    entry printed, which is true of what a document prints and false of a reconstruction —
    so matching now reads `source_text` where there is one.
    """
    entry = RawReferenceEntry(
        index=1,
        raw_text="Weber (1905) The protestant ethic and the spirit of capitalism",
        source_text=(
            "Weber, M. (1930). The protestant ethic and the spirit of capitalism "
            "[Original work published 1905]. Allen & Unwin."
        ),
    )
    matches = match_citations(
        _artifact("As Weber argued (Weber, 1930), the ethic persists."), [entry]
    )

    assert [(m.status, m.reference_n) for m in matches] == [(MatchStatus.RESOLVED, 1)]


def test_the_reconstruction_is_still_used_when_no_printed_entry_was_kept():
    """`source_text` is absent whenever GROBID was not asked for raw citations, or did not
    supply one for an entry — matching falls back to the reconstruction rather than
    treating a missing string as an entry with no evidence in it."""
    entry = RawReferenceEntry(
        index=1, raw_text="Weber (1905) The protestant ethic and the spirit of capitalism"
    )
    matches = match_citations(_artifact("As shown (Weber, 1905)."), [entry])

    assert [(m.status, m.reference_n) for m in matches] == [(MatchStatus.RESOLVED, 1)]


def test_an_author_the_structured_parse_lost_is_read_from_the_printed_entry():
    """The fifth false orphan the measurement found: GROBID reconstructed a Chicago entry
    as a bare "(1961)", having failed to read its author, so the entry matched nothing any
    marker could say. The printed string still names Augustine."""
    entry = RawReferenceEntry(
        index=1,
        raw_text="(1961)",
        source_text="Augustine. 1961. Confessions. Translated by R. S. Pine-Coffin. Penguin.",
    )
    matches = match_citations(_artifact("As Augustine wrote (Augustine 1961, p. 87)."), [entry])

    assert [(m.status, m.reference_n) for m in matches] == [(MatchStatus.RESOLVED, 1)]


def test_a_surname_that_merely_rhymes_is_not_a_match():
    """Short names are where a similarity threshold earns its keep: two three-letter
    surnames sharing two letters are a large fraction of each other."""
    match = _one("As shown (Wu, 2020).", "Xu, Q. (2020). A study.")

    assert match.status is MatchStatus.ORPHANED


# --------------------------------------------------------------------------------------
# Ambiguity — the state that must never be resolved by guessing
# --------------------------------------------------------------------------------------


def test_two_entries_a_marker_fits_equally_leave_it_ambiguous():
    match = _one(
        "As shown (Doe, 2020).",
        "Doe, J. (2020). A first study.",
        "Doe, R. (2020). A different study by a different Doe.",
    )

    assert match.status is MatchStatus.AMBIGUOUS
    assert match.reference_n is None
    assert match.candidates == (1, 2)


def test_a_second_name_in_the_marker_breaks_the_tie():
    """"(Doe & Roe, 2020)" and "(Doe, 2020)" score identically on the first surname, which
    is the one an author-date marker always prints — so the rest of the run has to be
    consulted for a document that carries both works."""
    match = _one(
        "As shown (Doe & Roe, 2020).",
        "Doe, J. (2020). A solo study.",
        "Doe, J., & Roe, A. (2020). A collaborative study.",
    )

    assert (match.status, match.reference_n) == (MatchStatus.RESOLVED, 2)


def test_an_ambiguous_marker_is_not_counted_as_a_citation_of_either_candidate():
    matches = _match(
        "As shown (Doe, 2020).",
        "Doe, J. (2020). A first study.",
        "Doe, R. (2020). A second study.",
    )

    assert citation_counts(matches) == {}


def test_an_ambiguous_marker_still_keeps_both_candidates_off_the_unused_list():
    """An entry a marker might be citing is not an entry nothing cites. The flag says a
    reviewer should look at a reference with no citations, and "don't know" is not that."""
    references = _refs("Doe, J. (2020). A first study.", "Doe, R. (2020). A second study.")
    matches = match_citations(_artifact("As shown (Doe, 2020)."), references)

    assert matches[0].status is MatchStatus.AMBIGUOUS
    assert unused_reference_numbers([r.index for r in references], matches) == ()


# --------------------------------------------------------------------------------------
# Numbered markers
# --------------------------------------------------------------------------------------


def test_a_numbered_marker_resolves_to_the_entry_at_its_number():
    matches = _match(
        "Prior work [1] and later work [2].",
        "[1] C. E. Shannon, \"A mathematical theory of communication,\" 1948.",
        "[2] R. Doll and A. B. Hill, \"Smoking and carcinoma of the lung,\" 1954.",
    )

    assert [(m.status, m.reference_n, m.confidence) for m in matches] == [
        (MatchStatus.RESOLVED, 1, 1.0),
        (MatchStatus.RESOLVED, 2, 1.0),
    ]
    assert {m.family for m in matches} == {MarkerFamily.NUMBERED}


def test_a_grouped_numbered_marker_is_one_record_per_reference():
    matches = _match(
        "Prior work [1, 3] shows this.",
        "[1] First entry, 1948.",
        "[2] Second entry, 1950.",
        "[3] Third entry, 1954.",
    )

    assert [m.reference_n for m in matches] == [1, 3]
    assert {(m.anchor.start, m.anchor.end) for m in matches} == {(11, 17)}


def test_a_number_the_bibliography_does_not_reach_is_orphaned():
    match = _one("Prior work [9] shows this.", "[1] First entry, 1948.")

    assert match.status is MatchStatus.ORPHANED


def test_a_printed_number_beats_position_when_extraction_dropped_an_entry():
    """The assumption "marker n is the nth entry we extracted" is only safe if extraction
    lost nothing, which is exactly what a hard-to-parse reference list violates. A
    bibliography that numbers itself is telling us what its markers mean."""
    matches = _match(
        "Prior work [1] and [3].",
        "[1] First entry, 1948.",
        "[3] Third entry, 1954.",
    )

    assert [(m.status, m.reference_n) for m in matches] == [
        (MatchStatus.RESOLVED, 1),
        (MatchStatus.RESOLVED, 2),
    ]


def test_a_gap_in_the_printed_numbers_is_not_evidence_against_the_manuscript():
    """A number missing from the printed run is this project's loss, not the author's.

    The all-or-nothing rule protecting this map only catches an entry whose own marker
    could not be read — the loop abandons the map on it. An entry extraction never
    produced is not there to fail on: printed "[1]" "[2]" "[3]" "[4]" arriving as three
    entries reading "[1]" "[2]" "[4]" is a map every entry of which was read perfectly,
    and "[3]" resolves against nothing in it.

    Calling that orphaned tells the reviewer their manuscript cites a reference it does
    not list, about a reference sitting in the list on the page. The numbers are their own
    evidence: 1, 2, 4 is not a complete reading of anything.
    """
    matches = _match(
        "Prior work [1] and [3] and [4].",
        "[1] First entry, 1948.",
        "[2] Second entry, 1950.",
        "[4] Fourth entry, 1954.",
    )

    assert [(m.status, m.reference_n) for m in matches] == [
        (MatchStatus.RESOLVED, 1),
        (MatchStatus.UNRESOLVED, None),
        (MatchStatus.RESOLVED, 3),
    ]


def test_a_printed_run_that_does_not_start_at_one_is_read_as_incomplete():
    """The same evidence at the other end. A bibliography whose first entry was swallowed
    by its own heading extracts as "[2]" "[3]" — contiguous, and still short a reference.

    What this costs is stated rather than hidden: a list genuinely numbered from somewhere
    else, a per-chapter bibliography, now answers UNRESOLVED where it could have answered
    ORPHANED. That is a finding withheld rather than a finding invented, which is the
    direction this module errs in everywhere else.
    """
    match = _one("Prior work [1].", "[2] Second entry, 1950.", "[3] Third entry, 1954.")

    assert match.status is MatchStatus.UNRESOLVED


def test_a_whole_printed_run_still_calls_a_number_past_its_end_orphaned():
    """The fix above must not swallow the finding it is guarding. 1..3 read completely is
    a list that can say what it does not contain, and "[9]" against it is the authoring
    error ORPHANED is for."""
    match = _one(
        "Prior work [9].",
        "[1] First entry, 1948.",
        "[2] Second entry, 1950.",
        "[3] Third entry, 1954.",
    )

    assert match.status is MatchStatus.ORPHANED


def test_position_is_used_when_the_entries_print_no_numbers_of_their_own():
    """GROBID's reconstructed raw text carries no printed marker at all, so position is
    the only answer available for a Tier 1 reference list."""
    matches = _match(
        "Prior work [2].",
        "Shannon (1948) A mathematical theory of communication",
        "Doll, Hill (1954) Smoking and carcinoma of the lung",
    )

    assert [(m.status, m.reference_n) for m in matches] == [(MatchStatus.RESOLVED, 2)]


def test_a_number_past_a_positional_list_is_not_an_orphan():
    """The finding "this cites nothing" needs the list to be able to say so, and a list
    numbered only by position cannot. [3] against two GROBID-reconstructed entries is
    equally consistent with a citation to nothing and with a third entry GROBID dropped;
    reporting the manuscript on that evidence is the accusation the plan forbids."""
    match = _one(
        "Prior work [3].",
        "Shannon (1948) A mathematical theory of communication",
        "Doll, Hill (1954) Smoking and carcinoma of the lung",
    )

    assert match.status is MatchStatus.UNRESOLVED
    assert match.reference_n is None


def test_a_positional_number_does_not_claim_certainty():
    """Same marker, same answer, two different grounds for it: the printed list is stating
    its own numbering, the reconstructed one is being counted through. Only the first is
    worth a 1.0, and a reader sorting by confidence has to be able to tell them apart."""
    printed = _one("Prior work [2].", "[1] First entry, 1948.", "[2] Second entry, 1950.")
    positional = _one(
        "Prior work [2].",
        "Shannon (1948) A mathematical theory of communication",
        "Doll, Hill (1954) Smoking and carcinoma of the lung",
    )

    assert (printed.status, printed.confidence) == (MatchStatus.RESOLVED, 1.0)
    assert (positional.status, positional.reference_n) == (MatchStatus.RESOLVED, 2)
    assert positional.confidence < SURNAME_MATCH_THRESHOLD


def test_a_dropped_grobid_entry_does_not_produce_a_confident_wrong_match():
    """The whole hazard in one document. GROBID read the bibliography but found no citation
    contexts, so matching falls to Tier 0 against entries whose reconstructed text carries
    no printed number — and GROBID lost the third of the five printed entries, so every
    number from three up now points one entry short of where the manuscript meant."""
    matches = _match(
        "Control flow [3], and axiomatics [5].",
        "Shannon (1948) A mathematical theory of communication",
        "Turing (1950) Computing machinery and intelligence",
        # printed [3], Hoare 1969, is the entry GROBID failed to parse
        "Dijkstra (1968) Go to statement considered harmful",
        "Knuth (1974) Structured programming with go to statements",
        grobid_citations=(),
    )

    shifted, past_the_end = matches
    # Still resolved — position is exact whenever the list is whole, and refusing every
    # numbered marker would abandon the path GROBID makes most common. What it may not do
    # is claim certainty about an entry it reached by counting.
    assert shifted.confidence < 1.0
    assert past_the_end.status is MatchStatus.UNRESOLVED


def test_repeated_printed_numbers_fall_back_to_position():
    """Two entries claiming the same number is a broken extraction, not a bibliography to
    trust; position is the weaker answer but it is at least consistent."""
    matches = _match(
        "Prior work [2].",
        "[1] First entry, 1948.",
        "[1] Second entry, 1950.",
    )

    assert [(m.status, m.reference_n) for m in matches] == [(MatchStatus.RESOLVED, 2)]


# --------------------------------------------------------------------------------------
# Positions
# --------------------------------------------------------------------------------------


def test_a_tier_0_match_anchors_at_the_marker_it_was_detected_at():
    text = "The effect replicates (Doe, 2020) in later work."
    match = _one(text, "Doe, J. (2020). A first study.")

    assert text[match.anchor.start : match.anchor.end] == "(Doe, 2020)"


def test_a_marker_in_the_second_paragraph_anchors_to_the_second_paragraph():
    artifact = _artifact("An opening paragraph with no citation in it.", "Later work (Doe, 2020) agrees.")
    matches = match_citations(artifact, _refs("Doe, J. (2020). A first study."))

    assert matches[0].anchor.paragraph_index == 1
    assert artifact.paragraph_text(matches[0].anchor).startswith("Later work")


# --------------------------------------------------------------------------------------
# Tier 1: GROBID's own link, and what happens when it has none
# --------------------------------------------------------------------------------------


def _context(reference_index, marker_text="[1]", target="b0"):
    return CitationContext(
        reference_index=reference_index,
        target=target,
        marker_text=marker_text,
        paragraph_text="a TEI paragraph",
        start=0,
        end=len(marker_text),
    )


def test_a_linked_grobid_marker_resolves_to_the_entry_grobid_linked_it_to():
    matches = match_citations(
        _artifact("Prior work [2] shows this."),
        _refs("[1] First entry, 1948.", "[2] Second entry, 1954."),
        grobid_citations=[_context(2, "[2]", "b1")],
    )

    assert [(m.status, m.reference_n, m.tier, m.confidence) for m in matches] == [
        (MatchStatus.RESOLVED, 2, ENGINE_GROBID, 1.0)
    ]


def test_an_unlinked_grobid_marker_is_read_with_the_tier_0_parser():
    """A marker GROBID could not link is far more often one it failed to link than one the
    bibliography has no entry for — so its text gets the same reading the regex tier would
    have given it, rather than being reported as an authoring error on GROBID's silence."""
    matches = match_citations(
        _artifact("Prior work [2] shows this."),
        _refs("[1] First entry, 1948.", "[2] Second entry, 1954."),
        grobid_citations=[_context(None, "[2]", None)],
    )

    assert [(m.status, m.reference_n, m.tier) for m in matches] == [
        (MatchStatus.RESOLVED, 2, ENGINE_GROBID)
    ]


def test_an_unlinked_grobid_marker_naming_a_missing_entry_is_orphaned():
    matches = match_citations(
        _artifact("Prior work [9] shows this."),
        _refs("[1] First entry, 1948."),
        grobid_citations=[_context(None, "[9]", None)],
    )

    assert matches[0].status is MatchStatus.ORPHANED


def test_an_unlinked_grobid_marker_nobody_can_read_stays_unresolved():
    """Not orphaned: an unreadable marker is evidence of nothing, and the plan's "never a
    guess" requirement cuts both ways — a finding needs evidence too."""
    matches = match_citations(
        _artifact("Prior work shows this."),
        _refs("[1] First entry, 1948."),
        grobid_citations=[_context(None, "¹²", None)],
    )

    assert matches[0].status is MatchStatus.UNRESOLVED
    assert matches[0].reference_n is None


def test_an_unlinked_grobid_marker_keeps_its_reference_off_the_unused_list():
    """The failure this fallback exists to prevent: a reference cited only through markers
    GROBID did not link would otherwise be reported as never cited."""
    references = _refs("[1] First entry, 1948.", "[2] Second entry, 1954.")
    matches = match_citations(
        _artifact("Prior work [2] shows this."),
        references,
        grobid_citations=[_context(None, "[2]", None)],
    )

    assert unused_reference_numbers([r.index for r in references], matches) == (1,)


def test_a_grobid_marker_is_located_by_its_text_in_the_manuscript():
    """TEI offsets index GROBID's own rendering, which shares no coordinates with the
    artifact — the marker's characters are the only thing the two have in common."""
    text = "Prior work [2] shows this."
    matches = match_citations(
        _artifact(text), _refs("[1] One, 1948.", "[2] Two, 1954."), grobid_citations=[_context(2, "[2]", "b1")]
    )

    assert text[matches[0].anchor.start : matches[0].anchor.end] == "[2]"


def test_a_repeated_grobid_marker_lands_on_a_different_occurrence_each_time():
    """Both sequences are in document order, so the search resumes where the last marker
    ended — otherwise eight citations of reference 3 are eight copies of the first one's
    position, and a reviewer sent to the same sentence eight times."""
    text = "First [1] here, then [1] there, and [1] finally."
    matches = match_citations(
        _artifact(text), _refs("[1] One, 1948."), grobid_citations=[_context(1, "[1]", "b0")] * 3
    )

    assert [m.anchor.start for m in matches] == [text.index("[1]"), 21, 36]
    assert all(text[m.anchor.start : m.anchor.end] == "[1]" for m in matches)


def test_a_grobid_marker_that_is_not_in_the_body_text_is_unlocated_but_still_resolved():
    """Locating and resolving are separate questions; failing the first must not suppress
    the answer to the second."""
    matches = match_citations(
        _artifact("A paragraph whose marker did not survive extraction."),
        _refs("[1] One, 1948."),
        grobid_citations=[_context(1, "[1]", "b0")],
    )

    assert matches[0].anchor is None
    assert (matches[0].status, matches[0].reference_n) == (MatchStatus.RESOLVED, 1)


def test_the_separator_a_grouped_marker_carries_is_not_searched_for():
    """GROBID splits "[1, 2]" into two elements and the second one's text keeps the
    separator (", [2]"), which the manuscript does not print as part of the marker."""
    text = "Prior work [1, 2] shows this."
    matches = match_citations(
        _artifact(text),
        _refs("[1] One, 1948.", "[2] Two, 1954."),
        grobid_citations=[_context(1, "[1", "b0"), _context(2, ", 2]", "b1")],
    )

    assert [text[m.anchor.start : m.anchor.end] for m in matches] == ["[1", "2]"]


def test_a_whitespace_only_grobid_marker_is_unlocated_rather_than_matching_everywhere():
    matches = match_citations(
        _artifact("Prior work shows this."),
        _refs("[1] One, 1948."),
        grobid_citations=[_context(1, "  ", "b0")],
    )

    assert matches[0].anchor is None


def test_a_marker_grobid_did_not_link_is_still_read_by_tier_0():
    """The reason tier selection stopped being a switch on "did GROBID return anything".

    One linked context used to mean Tier 0 never ran, so every other marker in the
    document was looked for by nobody — and a reference cited only by those markers was
    reported as cited by nothing, which is a finding about the manuscript manufactured
    out of a gap in this project's own reading.
    """
    matches = match_citations(
        _artifact("Prior work (Doe, 2020) and [1] both apply."),
        _refs("Doe, J. (2020). A study."),
        grobid_citations=[_context(1, "[1]", "b0")],
    )

    # In document order, and each labelled with the tier that actually found it.
    assert [(m.tier, m.marker_text) for m in matches] == [
        (ENGINE_ANCHOR, "(Doe, 2020)"),
        (ENGINE_GROBID, "[1]"),
    ]
    assert unused_reference_numbers([1], matches) == ()


def test_the_tiers_do_not_both_answer_for_one_marker():
    """Not mixing the tiers is still right — the argument was only ever about
    double-counting, and overlap is what separates them now that Tier 1 locates its own
    markers. The marker below is one both tiers can read, and it must produce one match."""
    matches = match_citations(
        _artifact("As shown (Doe, 2020)."),
        _refs("Doe, J. (2020). A study."),
        grobid_citations=[_context(1, "(Doe, 2020)", "b0")],
    )

    assert [m.tier for m in matches] == [ENGINE_GROBID]
    assert citation_counts(matches) == {1: 1}


def test_a_grouped_marker_grobid_only_half_linked_keeps_its_other_half():
    """PR #59's review. A grouped marker's Tier 0 members share the *group's* span —
    `detect_citations` reports "[1, 2]" as two detections over the same six characters —
    so excluding a supplement by region let GROBID's link for "[1" bury the manuscript's
    citation of reference 2, which came back as a reference cited by nothing.

    That is the same false finding this whole change exists to prevent, one marker further
    in: the exclusion has to be about which *reference* was already answered for, not which
    stretch of text was.
    """
    matches = match_citations(
        _artifact("Prior work [1, 2] shows this."),
        _refs("[1] One, A. 1990. First.", "[2] Two, B. 1991. Second."),
        grobid_citations=[_context(1, "[1", "b0")],
    )

    assert unused_reference_numbers([1, 2], matches) == ()
    assert [(m.tier, m.reference_n) for m in matches] == [
        (ENGINE_GROBID, 1),
        (ENGINE_ANCHOR, 2),
    ]


def test_a_group_grobid_linked_whole_is_not_read_a_second_time():
    """The other side of the same rule: when Tier 1 answers for every member of a group,
    the supplement adds none of them back. Otherwise the fix above would trade a missing
    citation for a doubled one, which is the worse of the two."""
    matches = match_citations(
        _artifact("Prior work [1, 2] shows this."),
        _refs("[1] One, A. 1990. First.", "[2] Two, B. 1991. Second."),
        grobid_citations=[_context(1, "[1", "b0"), _context(2, "2]", "b1")],
    )

    assert [m.tier for m in matches] == [ENGINE_GROBID, ENGINE_GROBID]
    assert citation_counts(matches) == {1: 1, 2: 1}


def test_a_marker_grobid_truncated_is_counted_once_not_twice():
    """The unreadable half of a grouped marker is a fragment of GROBID's, not a citation.

    GROBID splits "[8, 9]" into a linked "[8," and an unlinked "9]", and `parse_marker`
    cannot read the second — it is half a bracket. That earned an UNRESOLVED record beside
    the Tier 0 reading of the very same characters, so two citations were reported as three
    read and the surplus sat in the unresolved count, where it reads as this project
    declining on something it answered in the line above. `_already_answered`'s own
    docstring is the rule being applied here: a duplicate is a wrong number where a drop is
    only a silent one.
    """
    matches = match_citations(
        _artifact("The two results agree [8, 9] on this point."),
        _refs("[8] Shannon, C. 1948. A theory.", "[9] Turing, A. 1950. Machinery."),
        grobid_citations=[_context(1, "[8,", "b0"), _context(None, "9]", None)],
    )

    assert [(m.tier, m.status, m.reference_n) for m in matches] == [
        (ENGINE_GROBID, MatchStatus.RESOLVED, 1),
        (ENGINE_ANCHOR, MatchStatus.RESOLVED, 2),
    ]


def test_an_unreadable_context_nothing_else_reached_keeps_its_record():
    """The boundary. Dropping is licensed by Tier 0 having read those characters, not by
    the context being unreadable — where nothing covers it, the UNRESOLVED record is the
    only trace that GROBID saw a marker at all, and there the decline is true.

    "¹²" is superscript this project's detector does not read either, and it sits in the
    body, so the context locates and the Tier 0 pass runs. The document carries a separate
    marker Tier 0 *does* read, which is what makes this a test of the coverage condition
    rather than of the empty-supplement case: without the second marker nothing is dropped
    for want of anything to drop against, and removing the condition would leave this green.
    """
    matches = match_citations(
        _artifact("Prior work ¹² shows this, and later work [2] agrees."),
        _refs("[1] First entry, 1948.", "[2] Second entry, 1954."),
        grobid_citations=[_context(None, "¹²", None)],
    )

    assert [(m.tier, m.status, m.reference_n) for m in matches] == [
        (ENGINE_GROBID, MatchStatus.UNRESOLVED, None),
        (ENGINE_ANCHOR, MatchStatus.RESOLVED, 2),
    ]


def test_an_unlocated_grobid_marker_holds_the_tier_0_pass_back():
    """A context that placed nowhere has claimed no span, so nothing can tell whether a
    Tier 0 detection is that same marker read a second time. Counting one citation twice
    is a wrong number, where skipping the pass is only a missing one — so the supplement
    is dropped and this returns what it always returned.

    The marker text below is what GROBID hands over for a truncated one: it never occurs
    in the body, so `_locate_marker` cannot place it, while Tier 0 reads the full marker.
    """
    matches = match_citations(
        _artifact("As shown (Doe, 2020, p. 87) and elsewhere (Roe, 2019)."),
        _refs("Doe, J. (2020). A study.", "Roe, A. (2019). Another."),
        grobid_citations=[_context(1, "(Doe, 2020, p. 8", "b0")],
    )

    assert [m.tier for m in matches] == [ENGINE_GROBID]
    assert citation_counts(matches) == {1: 1}


# --------------------------------------------------------------------------------------
# Aggregates
# --------------------------------------------------------------------------------------


def test_an_uncited_reference_is_reported_and_a_cited_one_is_not():
    references = _refs("Doe, J. (2020). A cited study.", "Roe, A. (2019). An uncited study.")
    matches = match_citations(_artifact("As shown (Doe, 2020)."), references)

    assert unused_reference_numbers([r.index for r in references], matches) == (2,)


def test_citations_are_counted_per_reference():
    references = _refs("Doe, J. (2020). A study.", "Roe, A. (2019). Another.")
    matches = match_citations(
        _artifact("First (Doe, 2020), then (Roe, 2019), then Doe (2020) again."), references
    )

    assert citation_counts(matches) == {1: 2, 2: 1}


def test_a_document_with_no_markers_produces_no_matches_and_every_reference_unused():
    references = _refs("Doe, J. (2020). A study.")
    matches = match_citations(_artifact("A paragraph that cites nothing at all."), references)

    assert matches == ()
    assert unused_reference_numbers([r.index for r in references], matches) == (1,)


def test_a_reference_list_with_nothing_in_it_orphans_nothing():
    """Reversed on 2026-08-14: this asserted ORPHANED, and ORPHANED was wrong.

    That status is reached by scoring every entry and finding none good enough, which over
    an empty list is vacuously true — so a document whose bibliography extraction came back
    with nothing had every author-date marker reported as citing a reference it does not
    carry. A page of findings, every one of them this project's own miss, and the reversal
    is a behaviour decision rather than a test fix.

    The numbered marker was already right, for a reason worth keeping visible: an empty map
    is not a *printed* one, so `_resolve_numbered` already refused to call a miss an orphan.
    The author-date path had no equivalent. Both now rest on the same rule — a list can only
    be said to lack an entry if it was read.
    """
    matches = match_citations(_artifact("As shown (Doe, 2020) and (Roe, 2019), also [3]."), [])

    assert [m.status for m in matches] == [MatchStatus.UNRESOLVED] * 3


# --------------------------------------------------------------------------------------
# Style cross-validation, and what a match may carry
# --------------------------------------------------------------------------------------


def test_the_bibliographys_style_evidence_narrows_which_markers_are_looked_for():
    """A parenthesised bare numeral is a citation in a numbered document and an equation
    number everywhere else, so it is only looked for when the bibliography itself is
    numbered — the cross-validation Phase 2 built, exercised here through the engine."""
    numbered = "\n".join(f"[{n}] Author{n} A. A study of things. Br Med J 1948;2:{n}." for n in range(1, 6))
    references = _refs(*numbered.splitlines())
    text = "The result was replicated in later work (2)."

    with_profile = match_citations(
        _artifact(text), references, profile=compute_style_profile(numbered)
    )
    without_profile = match_citations(_artifact(text), references)

    assert [m.reference_n for m in with_profile] == [2]
    assert without_profile == ()


def test_a_match_carries_no_passage_text():
    """The plan keeps raw context behind an explicit reviewer opt-in, so a match must
    quote nothing but the marker itself — a copy here would put one in every structure a
    match is stored in, and in every repr of one."""
    artifact = _artifact("A sentence of body prose that cites (Doe, 2020) in passing.")
    match = match_citations(artifact, _refs("Doe, J. (2020). A study."))[0]

    assert "body prose" not in repr(match)
    assert match.marker_text == "(Doe, 2020)"


@pytest.mark.parametrize(
    ("marker", "expected"),
    [
        ("[3]", [(3, None, None)]),
        ("[3, 4]", [(3, None, None), (4, None, None)]),
        ("(Doe, 2020)", [(None, "Doe", "2020")]),
        ("Doe (2020)", [(None, "Doe", "2020")]),
        ("[15, Sec. 3]", [(15, None, None)]),
    ],
)
def test_a_known_marker_parses_without_the_surrounding_text_the_detector_needs(marker, expected):
    """`parse_marker` exists because every exclusion in `detect_citations` reads a marker's
    surroundings, and a marker handed over on its own has none. A bare "[3]" is
    line-initial with nothing above it — the shape of a notes-list entry — so the detector
    is right to refuse it and wrong to be asked."""
    parsed = parse_marker(marker)

    assert [(c.number, c.authors, c.year) for c in parsed] == expected


def test_the_surname_threshold_is_the_measured_one():
    """Pinned so the benchmark in tests/test_citation_matching_recall.py is what changes
    it, rather than a passing suite quietly absorbing a different value."""
    assert SURNAME_MATCH_THRESHOLD == 0.90


# The pairs the threshold was actually chosen from. They are asserted individually because
# the recall corpus cannot choose it — the same 121 citations resolve at every value from
# 0.0 to 1.0, so a green suite says nothing about whether the number is right. These do.
_DIFFERENT_NAMES = [
    ("Smith", "Smyth", 0.800),  # a typed error in the manuscript
    ("Meyer", "Meier", 0.800),  # a typed error, or two different people
    ("Barth", "Barthes", 0.833),  # two different authors, both in the Chicago fixture
    ("Wu", "Xu", 0.500),
    ("Doe", "Roe", 0.667),
]
_ONE_NAME_TWICE = [
    ("Fischer", "Fisher", 0.923),  # the same name, one of them damaged
    ("Mueller", "Muller", 0.923),  # the "ue" digraph lost or added
    ("Shannon", "Shanon", 0.923),  # a letter dropped by extraction
    ("Levinas", "Lévinas", 1.000),  # diacritics are folded before comparison
    ("Baumeister", "Baumeister", 1.000),
]


@pytest.mark.parametrize("left,right,score", _DIFFERENT_NAMES + _ONE_NAME_TWICE)
def test_the_scores_the_threshold_was_chosen_from_are_what_they_were(left, right, score):
    """The measurement itself, so a change to `_name_similarity` that moved these pairs
    could not leave the threshold looking as if it still meant what it was picked to mean."""
    assert round(_name_similarity(left, right), 3) == score


@pytest.mark.parametrize("left,right,_score", _DIFFERENT_NAMES)
def test_two_different_surnames_fall_below_the_threshold(left, right, _score):
    """Why the number is 0.90 and not 0.80. Every pair here is two different names, and at
    0.80 the first three of them matched — "(Smyth, 2020)" resolved against a bibliography
    carrying only Smith rather than surfacing as an orphan, and Barth and Barthes were
    separable only by their years, which is a live collision in this project's own fixture
    rather than a hypothetical."""
    assert _name_similarity(left, right) < SURNAME_MATCH_THRESHOLD


@pytest.mark.parametrize("left,right,_score", _ONE_NAME_TWICE)
def test_one_surname_damaged_by_extraction_still_matches_itself(left, right, _score):
    """The other side, and the cost the raise had to not pay. These are one name written
    twice, and a threshold that rejected them would report the reference uncited *and* the
    citation orphaned — two false findings from one mangled name."""
    assert _name_similarity(left, right) >= SURNAME_MATCH_THRESHOLD


def test_the_threshold_sits_in_the_gap_between_the_two_groups():
    """The whole argument in one assertion: there is a gap between the worst pair of
    different names (0.833) and the best-damaged single name (0.923), and the threshold is
    inside it. A future value that left the gap would be picking one of the two errors."""
    assert max(s for *_, s in _DIFFERENT_NAMES) < SURNAME_MATCH_THRESHOLD
    assert SURNAME_MATCH_THRESHOLD <= min(s for *_, s in _ONE_NAME_TWICE)


# --------------------------------------------------------------------------------------
# What a missing year costs, from both directions
#
# `_MISSING_YEAR_PENALTY` documents two properties and had a test for one. Moving it *down*
# fails several tests, because a penalty that vetoes dateless entries changes an outcome
# other cases already look at; moving it *up* changed nothing the suite could see, and the
# 0.90 -> 0.99 case is a real behaviour change — a damaged name resolving against an entry
# with no date to corroborate it. A constant with two edges needs a test on each edge.
# --------------------------------------------------------------------------------------


def test_an_exact_name_survives_having_no_date_to_corroborate_it():
    """The floor. An entry whose date this project failed to read is a parsing failure far
    more often than a work with no date, and a penalty heavy enough to veto it would take
    every marker for that reference down with it."""
    match = _one("The effect replicates (Doe, 2020).", "Doe, J. A study with no readable date.")

    assert match.status is MatchStatus.RESOLVED
    assert match.confidence == pytest.approx(_MISSING_YEAR_PENALTY)


@pytest.mark.parametrize("marker_name,entry_name", [("Fisher", "Fischer"), ("Mueller", "Muller")])
def test_a_name_only_nearly_right_does_not_survive_it(marker_name, entry_name):
    """The ceiling, and the edge that had no test. These are the pairs
    `SURNAME_MATCH_THRESHOLD` deliberately treats as one damaged name — with a year on both
    sides they resolve, and should. With no date on the entry, the name is the only evidence
    there is, and "close enough to be the same name" is not enough to be the only evidence.

    At 0.99 the identical case resolves at confidence 0.914, which is the same wrong answer
    the threshold raise to 0.90 was taken to avoid, arrived at through the other constant.
    """
    match = _one(
        f"The effect replicates ({marker_name}, 2020).",
        f"{entry_name}, J. A study with no readable date.",
    )

    assert match.status is MatchStatus.ORPHANED


def test_the_missing_year_penalty_sits_between_the_two_edges():
    """The arithmetic behind both, so a future value is checked against the argument rather
    than against a suite that stayed green for the whole upper half of the range.

    The band is [0.90, 0.975): an exact match scores 1.0 and has to clear the threshold
    after the penalty, and the best-damaged pair scores 0.923 and must not. 0.9 sits on the
    floor exactly — which is why every downward move fails loudly and every upward one used
    to fail silently.
    """
    best_damaged = min(score for *_, score in _ONE_NAME_TWICE if score < 1.0)

    assert 1.0 * _MISSING_YEAR_PENALTY >= SURNAME_MATCH_THRESHOLD
    assert best_damaged * _MISSING_YEAR_PENALTY < SURNAME_MATCH_THRESHOLD


# --------------------------------------------------------------------------------------
# What the Phase 4 review pass found (see the plan's Notes)
# --------------------------------------------------------------------------------------


def test_a_page_range_is_not_read_as_the_entrys_year():
    """The worst shape a wrong year takes, because it fails twice from one mistake: the
    citation is reported orphaned *and* the reference is reported uncited. A journal with
    continuous pagination prints page ranges in the 1500-2099 band as a matter of course.
    """
    references = _refs("Doe, J. A study of memory. Journal of Tests, 12(3), 1990-1995.")
    matches = match_citations(_artifact("As shown (Doe, 2020)."), references)

    assert (matches[0].status, matches[0].reference_n) == (MatchStatus.RESOLVED, 1)
    assert unused_reference_numbers([1], matches) == ()


def test_a_year_read_from_an_entrys_tail_cannot_veto_a_match():
    """A numbered style prints its year past the title, where it competes with volume and
    page numbers — so a year found there is evidence when it agrees and not a rejection
    when it disagrees. A date in the slot a date goes in still rejects (below)."""
    match = _one(
        "As shown (Doe, 2020).",
        "Doe J, Roe A. Smoking and carcinoma of the lung: a preliminary report on tobacco. "
        "British Medical Journal 1954;2(4682):1451.",
    )

    assert match.status is MatchStatus.RESOLVED
    assert match.confidence < 1.0


def test_a_date_in_the_slot_a_date_goes_in_still_vetoes():
    """The other half of the same rule: loosening the veto must not disarm it. Both of
    these carry their year where the style puts the publication date."""
    assert _one("As shown (Kuhn 1970).", "Kuhn, Thomas S. 1962. The Structure.").status is MatchStatus.ORPHANED
    assert _one("As shown (Doe, 1999).", "Doe, J. (2020). A study.").status is MatchStatus.ORPHANED


def test_a_title_first_entry_does_not_inherit_its_neighbours_author():
    """The repeated-author rule reads "———", and an anonymous or title-first entry opens
    with a quotation mark. Reading the second as the first attached the entry above's
    surname to it, and "(Doe, 1788)" resolved to it at full confidence — a wrong answer
    stated confidently, which is worse than the missed match it was meant to prevent.
    """
    references = _refs(
        "Doe, J. (2020). A study.",
        '"The collected papers of an anonymous society." 1788. Antiquarian Press.',
    )
    matches = match_citations(_artifact("As shown (Doe, 1788)."), references)

    assert matches[0].status is MatchStatus.ORPHANED
    assert matches[0].reference_n is None


@pytest.mark.parametrize("opener", ['"An editorial."', "[Anonymous].", "(Author unknown).", "2020 in review."])
def test_only_a_rule_lets_an_entry_inherit_an_author(opener):
    references = _refs("Doe, J. (2020). A study.", f"{opener} 1788. A work with no author.")
    matches = match_citations(_artifact("As shown (Doe, 1788)."), references)

    assert matches[0].status is MatchStatus.ORPHANED


def test_a_rule_entry_still_inherits():
    """The case the inheritance exists for, kept alive by the tighter gate."""
    references = _refs(
        "Ricoeur, Paul. 1969. The Symbolism of Evil.",
        "———. 1970. Freud and Philosophy.",
    )
    matches = match_citations(_artifact("As shown (Ricoeur 1970)."), references)

    assert (matches[0].status, matches[0].reference_n) == (MatchStatus.RESOLVED, 2)


@pytest.mark.parametrize(
    ("marker", "entry"),
    [("Wu", "WU, Q. (2020). A study."), ("Ng", "NG, K. (2020). A study."), ("Wu", "Wu, Q. (2020). A study.")],
)
def test_a_short_all_caps_surname_is_a_name_not_an_initial(marker, entry):
    """The rule that strips "Doll R"'s run-together initials cannot tell them from a
    two-letter surname, and "WU, Q." is an ordinary house style. Deleting the name left
    the entry with no author at all: an orphaned citation and an uncited reference."""
    match = _one(f"As shown ({marker}, 2020).", entry)

    assert (match.status, match.reference_n) == (MatchStatus.RESOLVED, 1)


def test_initials_are_still_stripped_when_a_real_surname_survives():
    """The counterpart that keeps the all-caps allowance honest."""
    match = _one("As shown (Doll, 1954).", "Doll R, Hill AB. Smoking and carcinoma. Br Med J 1954;2:1451.")

    assert (match.status, match.reference_n) == (MatchStatus.RESOLVED, 1)


def test_a_bare_digit_marker_is_not_located_inside_a_number():
    """A superscript numbering style gives GROBID a marker whose whole text is "1", and
    "1" occurs inside "2019". Anchoring there sends a reviewer to the middle of a year
    several words from the marker — a wrong position, which is the one thing they cannot
    check without re-reading the page."""
    text = "The 2019 replication attempt found nothing.1 Later work agreed."
    matches = match_citations(
        _artifact(text), _refs("[1] One, 1948."), grobid_citations=[_context(1, "1", "b0")]
    )

    assert text[matches[0].anchor.start : matches[0].anchor.end] == "1"
    assert matches[0].anchor.start == text.index("nothing.1") + len("nothing.")


def test_a_marker_that_only_occurs_inside_a_word_is_unlocated():
    matches = match_citations(
        _artifact("The 2019 replication attempt found nothing."),
        _refs("[1] One, 1948."),
        grobid_citations=[_context(1, "1", "b0")],
    )

    assert matches[0].anchor is None
    assert matches[0].status is MatchStatus.RESOLVED


def test_a_partly_numbered_bibliography_falls_back_to_position():
    """Two printed numbers used to be enough to switch the positional map off for the
    whole list, so a marker whose entry lost its number was reported as an orphaned
    citation — the manuscript accused of citing a reference sitting in its own list."""
    matches = _match(
        "Work [2] and [3] and [4].",
        "[1] One, 1948.",
        "[2] Two, 1950.",
        "Third entry whose number extraction lost, 1954.",
        "[4] Four, 1960.",
    )

    assert [(m.status, m.reference_n) for m in matches] == [
        (MatchStatus.RESOLVED, 2),
        (MatchStatus.RESOLVED, 3),
        (MatchStatus.RESOLVED, 4),
    ]


def test_a_year_opening_an_entry_is_not_a_printed_reference_number():
    """A four-digit leading number is a year, not a reference number.

    Reachable when a Chicago entry loses its author to a rule extraction then drops
    entirely, leaving "1974. The Conflict of Interpretations…" — read as printed marker
    1974, a list of those replaces the positional map for the whole document. A unit-level
    guard rather than a document this project has seen, which is why the fixture is a list
    of them rather than a realistic bibliography.
    """
    matches = _match(
        "Work [2] shows this.",
        "1969. The Symbolism of Evil.",
        "1974. The Conflict of Interpretations.",
        "1978. Orientalism.",
    )

    assert [(m.status, m.reference_n) for m in matches] == [(MatchStatus.RESOLVED, 2)]


def test_a_grobid_link_to_a_reference_that_does_not_exist_is_not_believed():
    """`extraction.grobid` builds the contexts and the reference list from one response so
    they cannot disagree in the pipeline — but this function takes them separately, and
    `reference_index` would otherwise be the one number believed without evidence."""
    matches = match_citations(
        _artifact("Prior work [1] shows this."),
        _refs("[1] One, 1948."),
        grobid_citations=[_context(99, "[1]", "bZZ")],
    )

    assert (matches[0].status, matches[0].reference_n) == (MatchStatus.RESOLVED, 1)


def test_grobids_link_is_used_rather_than_the_markers_own_number():
    """The whole reason Tier 1 exists, and it was unpinned: every fixture made the
    marker's number equal the reference index, so nothing distinguished "GROBID's link was
    used" from "the marker text was re-parsed". A TEI id is not a position — that is the
    plan's own GROBID target-identity decision — so the two must be able to disagree.
    """
    matches = match_citations(
        _artifact("Prior work [7] shows this."),
        _refs("[1] One, 1948.", "[2] Two, 1950.", "[3] Three, 1954."),
        grobid_citations=[_context(2, "[7]", "b6")],
    )

    assert [(m.status, m.reference_n) for m in matches] == [(MatchStatus.RESOLVED, 2)]


def test_a_particle_only_present_on_one_side_of_a_short_name_still_matches():
    """"de Beauvoir"/"Beauvoir" passes on raw similarity alone, so it never exercised the
    particle handling. A short name does: "dewit" against "wit" scores 0.75."""
    match = _one("Wit (2020) argued otherwise.", "de Wit, A. (2020). A study.")

    assert (match.status, match.reference_n) == (MatchStatus.RESOLVED, 1)


def test_a_diacritic_on_a_short_name_still_matches():
    """"Müller"/"Muller" also passes without the fold, because dropping the marked letter
    leaves enough of the word. A two-letter name leaves nothing."""
    match = _one("As shown (Oz, 2020).", "Öz, K. (2020). A study.")

    assert (match.status, match.reference_n) == (MatchStatus.RESOLVED, 1)


def test_a_long_author_list_does_not_push_the_date_out_of_reach():
    """The entry head has to reach the date past a full author list — otherwise two works
    by the same team stop being separable by year and both become candidates."""
    matches = _match(
        "As shown (Ainsworth et al., 1978).",
        "Ainsworth, M. D. S., Blehar, M. C., Waters, E., & Wall, S. (1978). Patterns of attachment.",
        "Ainsworth, M. D. S., Blehar, M. C., Waters, E., & Wall, S. (1985). A later study.",
    )

    assert [(m.status, m.reference_n) for m in matches] == [(MatchStatus.RESOLVED, 1)]
