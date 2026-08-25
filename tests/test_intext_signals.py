"""Tier-0 in-text citation marker detection.

Two halves. The corpus tests run every case in fixtures/intext_citations and are where
style coverage lives — adding a marker form means adding a case there, not a test here.
The rest pins the decisions the corpus cannot express in a text-and-expectation pair:
what the style cross-validation does with contradictory evidence, that offsets survive
into a `DocumentArtifact` anchor, and that the vocabulary this module borrows from
signals.py is still the vocabulary the bibliography path reads.
"""

import re
import time

import pytest

from intext_citation_corpus import expected_citations, load_cases, load_meta, load_styles
from refcheck.extraction.document_artifact import DocumentArtifact
from refcheck.extraction.intext_signals import (
    DetectedCitation,
    MarkerFamily,
    detect_citations,
    expected_families,
)
from refcheck.extraction.signals import NO_DATE, NO_DATE_RE
from refcheck.extraction.style_profile import StyleProfile, compute_style_profile

CASES = load_cases()
STYLES = load_styles()
META = load_meta()

IEEE_BIBLIOGRAPHY = (
    '[1] A. Doe, "A first title," Journal of Examples, vol. 1, no. 1, pp. 1-10, 2020.\n'
    '[2] B. Roe, "A second title," Journal of Methods, vol. 2, no. 3, pp. 20-30, 2019.\n'
    '[3] C. Fry, "A third title," Journal of Systems, vol. 3, no. 2, pp. 40-55, 2018.'
)
VANCOUVER_BIBLIOGRAPHY = (
    "1. Doe A, Roe B. A first title. Journal of Examples. 2020;12(3):45-50.\n"
    "2. Fry C, Nolan D. A second title. Journal of Methods. 2019;8(1):11-19.\n"
    "3. Weber E. A third title. Journal of Systems. 2018;4(2):100-108."
)
APA_BIBLIOGRAPHY = (
    "Doe, J. (2020). A first title. Journal of Examples, 1(1), 1-10.\n"
    "Roe, R. (2019). A second title. Journal of Methods, 2(3), 20-30.\n"
    "Fry, F. (2018). A third title. Journal of Systems, 3(2), 40-55."
)


def _as_dict(citation: DetectedCitation) -> dict:
    return {
        "family": citation.family.value,
        "marker": citation.marker_text,
        "authors": citation.authors,
        "year": citation.year,
        "number": citation.number,
        "narrative": citation.narrative,
    }


def _families_for(case: dict):
    if "families" not in case:
        return None
    return {MarkerFamily(name) for name in case["families"]}


@pytest.mark.parametrize("case", [pytest.param(c, id=f"{c['style']}/{c['id']}") for c in CASES])
def test_detection_by_citation_style(case):
    found = detect_citations(case["text"], families=_families_for(case))

    assert [_as_dict(c) for c in found] == expected_citations(case), case["note"]


@pytest.mark.parametrize("case", [pytest.param(c, id=f"{c['style']}/{c['id']}") for c in CASES])
def test_every_detected_span_is_the_marker_it_reports(case):
    """`marker_text` has to be literally `text[start:end]`.

    The offsets are the only thing a reviewer-facing locator can be built from, and a
    marker string that agrees with the case's expectation while the span points
    somewhere else would satisfy every other test in this file.
    """
    for citation in detect_citations(case["text"], families=_families_for(case)):
        assert case["text"][citation.start : citation.end] == citation.marker_text


def test_grouped_marker_members_share_one_span():
    found = detect_citations("Three agree (Doe, 2020; Roe, 2019; Fry, 2018).")

    assert len({(c.start, c.end) for c in found}) == 1
    assert [c.authors for c in found] == ["Doe", "Roe", "Fry"]


def test_citations_are_returned_in_document_order():
    """Mixed families in one pass still come back in reading order.

    The two families are detected by separate scans, so document order is a property of
    the merge rather than of either scan — which is exactly the kind of thing that works
    until a third scan is added.
    """
    text = "First [1], then Doe (2020), then (Roe, 2019), then [4]."

    found = detect_citations(text)

    assert [c.start for c in found] == sorted(c.start for c in found)
    assert [c.family for c in found] == [
        MarkerFamily.NUMBERED,
        MarkerFamily.AUTHOR_DATE,
        MarkerFamily.AUTHOR_DATE,
        MarkerFamily.NUMBERED,
    ]


def test_requesting_one_family_does_not_run_the_other():
    text = "Both shapes appear here: [1] and (Doe, 2020)."

    assert [c.number for c in detect_citations(text, families={MarkerFamily.NUMBERED})] == [1]
    assert [c.authors for c in detect_citations(text, families={MarkerFamily.AUTHOR_DATE})] == ["Doe"]


def test_detection_on_empty_text_finds_nothing():
    assert detect_citations("") == ()


# --------------------------------------------------------------------------------------
# Style cross-validation
# --------------------------------------------------------------------------------------


def test_a_numbered_bibliography_with_no_author_date_evidence_expects_only_numbered():
    assert expected_families(compute_style_profile(VANCOUVER_BIBLIOGRAPHY)) == frozenset(
        {MarkerFamily.NUMBERED}
    )


def test_an_ieee_bibliography_narrows_to_numbered():
    """IEEE puts its year after a page range, not after a name, so no author-date
    evidence fires and the document narrows to numbered.

    Worth pinning because narrowing is what unlocks the parenthesised-numeral pattern,
    and IEEE is also the style most likely to number its display equations — the two
    facts meet in `test_an_equation_number_at_the_end_of_a_line_is_not_a_citation`.
    """
    assert expected_families(compute_style_profile(IEEE_BIBLIOGRAPHY)) == frozenset(
        {MarkerFamily.NUMBERED}
    )


def test_an_author_date_bibliography_expects_only_author_date():
    assert expected_families(compute_style_profile(APA_BIBLIOGRAPHY)) == frozenset(
        {MarkerFamily.AUTHOR_DATE}
    )


def test_a_bibliography_showing_both_kinds_of_evidence_expects_both_families():
    """A numbered list of APA-shaped entries is genuinely both, and says so.

    Resolving that upward to both families is the deliberate choice: narrowing to one
    can only remove real markers, while the cost of running both scans is a regex pass.
    The price is that this document does not unlock the parenthesised-numeral pattern,
    which is the intended trade — its markers could be either shape.
    """
    numbered_apa = "\n".join(
        f"{n}. {entry}" for n, entry in enumerate(APA_BIBLIOGRAPHY.splitlines(), start=1)
    )

    assert expected_families(compute_style_profile(numbered_apa)) == frozenset(MarkerFamily)


def test_a_bibliography_with_no_style_evidence_expects_both_families():
    assert expected_families(compute_style_profile("A block with nothing style-shaped in it.")) == (
        frozenset(MarkerFamily)
    )


def test_one_numbered_line_is_not_enough_evidence_to_narrow():
    """A single occurrence is an accident; the threshold is what makes it evidence.

    Built as a StyleProfile directly rather than from text, because the point is the
    threshold and not whether some contrived block happens to produce exactly one hit.
    """
    barely = StyleProfile(
        paren_year_matches=0,
        comma_year_matches=0,
        bare_year_density=0.0,
        bracket_numbered_lines=1,
        dot_numbered_lines=0,
        quoted_titles=0,
        jss_author_lines=0,
        german_markers=0,
    )

    assert expected_families(barely) == frozenset(MarkerFamily)


def test_parenthesised_numerals_are_unlocked_by_a_numbered_bibliography_end_to_end():
    """The cross-validation is only worth having if it changes what is detected.

    Runs the whole path the pipeline will run: profile the bibliography, ask which
    families it supports, detect with that answer.
    """
    body = "The original trial reported a smaller effect (3)."

    numbered = detect_citations(body, families=expected_families(compute_style_profile(VANCOUVER_BIBLIOGRAPHY)))
    author_date = detect_citations(body, families=expected_families(compute_style_profile(APA_BIBLIOGRAPHY)))

    assert [c.number for c in numbered] == [3]
    assert author_date == ()


# --------------------------------------------------------------------------------------
# Numeric groups
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "A marker cannot be zero [0].",
        "Nor can a group contain one [0, 2].",
        "A page span is not a citation group [1-400].",
        "A descending pair is not a range [6-4].",
        "A degenerate range is not a range [4-4].",
    ],
)
def test_implausible_numeric_groups_are_rejected_whole(text):
    """A group that fails anywhere fails entirely, rather than being salvaged.

    Emitting the members that did parse would turn a page range into two citations to
    whatever references happen to sit at its endpoints — a wrong answer presented with
    the same confidence as a right one.
    """
    assert detect_citations(text, families={MarkerFamily.NUMBERED}) == ()


def test_a_range_at_the_length_limit_still_expands():
    found = detect_citations("The full set [1-41] is surveyed.", families={MarkerFamily.NUMBERED})

    assert [c.number for c in found] == list(range(1, 42))


# --------------------------------------------------------------------------------------
# Integration with the document artifact
# --------------------------------------------------------------------------------------


def test_detected_offsets_anchor_into_the_document_artifact():
    """Detection offsets have to be usable as artifact offsets without adjustment.

    This is the seam between Phase 1 and Phase 2: the detector never sees a paragraph,
    and the artifact never sees a marker, so nothing but this test says the two agree
    about what an offset means.
    """
    artifact = DocumentArtifact.from_lines(
        ["An opening paragraph with no citation.", "", "A later claim (Doe, 2020) appears here."],
        raw_text="",
        parser="test",
    )

    citation = detect_citations(artifact.body_text)[0]
    anchor = artifact.anchor_for(citation.start, citation.end)

    assert anchor is not None
    assert anchor.paragraph_index == 1
    assert artifact.body_text[anchor.start : anchor.end] == "(Doe, 2020)"


def test_a_marker_split_across_a_line_break_is_still_detected():
    """Body text keeps whatever line wrapping the source had.

    A marker the typesetter broke across a line contains a newline, and refusing to
    match across one would cost real markers in every wrapped document — which is all of
    them. The span is bounded by the closing parenthesis and by needing a plausible
    author and a date inside, not by the line, so letting it cross a newline does not
    let it run away.
    """
    found = detect_citations("A claim (Doe,\n2020) appears here.")

    assert [(c.authors, c.year) for c in found] == [("Doe", "2020")]


def test_an_equation_number_at_the_end_of_a_line_is_not_a_citation():
    """The parenthesised-numeral pattern's worst collision, in the documents that use it.

    A display equation puts its number alone at the end of its own line, with no cue
    word in front of it — so neither the cross-reference cue nor the notes-list check
    sees it, and a numbered manuscript would report one orphaned citation per equation.
    """
    text = "The estimator satisfies\n    y = a + bx    (1)\nfor all admissible inputs (3)."

    found = detect_citations(text, families={MarkerFamily.NUMBERED})

    assert [c.number for c in found] == [3]


def test_a_marker_that_ends_its_line_is_still_a_citation():
    """The other side of the equation-number exclusion, which it must not swallow.

    Extraction wraps lines wherever the source did, so a real marker ends a line as often
    as an equation number does. Prose before it on that line is what separates them, and
    rejecting on the empty remainder alone would silently lose one citation per wrap in
    exactly the numbered documents the parenthesised pattern exists for.
    """
    text = "Earlier trials found the effect (3)\nunder controlled conditions."

    found = detect_citations(text, families={MarkerFamily.NUMBERED})

    assert [c.number for c in found] == [3]


def test_every_entry_of_a_notes_list_is_excluded_not_only_the_first():
    """A notes block is consecutive lines, so a paragraph-initial test only sees entry one.

    Suppressing "[1]" and then emitting "[2]" and "[3]" is worse than not suppressing at
    all: it invents a second occurrence of some cited references and not others, which
    reads as a real citation pattern rather than as an obvious extraction artefact.
    """
    text = "Notes\n\n[1] The first point is made here.\n[2] The second follows.\n[3] And a third."

    found = detect_citations(text, families={MarkerFamily.NUMBERED})

    assert found == ()


def test_an_author_run_of_repeated_particles_does_not_backtrack():
    """A failing author run must fail in linear time, not by trying every parse of it.

    The run is anchored, so an input that cannot match has to exhaust the alternatives
    before the regex gives up. Overlapping particle spellings made that exponential —
    a few hundred characters of extraction noise was enough to hang the detector on a
    document that contains no citations at all.
    """
    noise = "van der " * 60 + "!"

    start = time.perf_counter()
    detect_citations(f"{noise} (2020)")

    assert time.perf_counter() - start < 1.0


def test_detection_does_not_rescan_the_document_for_every_marker():
    """Cost must grow with the document, not with the document times its markers.

    Every cue this module reads backwards from a marker used to be searched for over
    `text[:match.start()]` — a fresh copy of everything before it, scanned end to end. One
    marker cost a pass over the document, so a manuscript with twice the markers cost four
    times the time. Measured on this input before the window was introduced: 3.6 s at
    28 KB, 15 s at 57 KB, 68 s at 114 KB, all inside the check and before verification.
    It now runs in 0.66 s at 114 KB and scales linearly.

    The bound is deliberately loose — this asserts "not quadratic", not a throughput
    figure, and a slow CI machine is allowed to be slow. The old code cannot reach it: it
    needed two orders of magnitude longer on the same text. The marker count is asserted
    alongside it because a detector that found nothing would be very fast indeed.
    """
    paragraph = (
        "Recent work has established the effect in several populations [%d], and a "
        "follow-up replication confirmed the direction of the estimate [%d].\n\n"
    )
    text = "".join(paragraph % (n % 90 + 1, n % 90 + 2) for n in range(800))
    assert len(text) > 100_000

    start = time.perf_counter()
    found = detect_citations(text)
    elapsed = time.perf_counter() - start

    assert len(found) == 1600
    assert elapsed < 10.0, f"detection took {elapsed:.1f}s on {len(text)} characters"


def test_a_cue_still_suppresses_a_marker_far_behind_it():
    """The window is measured from the whitespace run, not from the marker.

    Guards the exactness the bounded search would otherwise cost. A cue's own text is
    short, but the whitespace it may sit behind is unbounded — extraction routinely leaves
    a long run where a PDF had a column break — and a cross-reference is still a
    cross-reference across it. A window that did not skip the run passes every other test
    in this file and fails this one, emitting "[3]" as a citation to reference 3.

    The interval cue is the contrast, and it is measured rather than assumed: it allows
    twenty non-bracket characters and no more, so it stops reaching at twenty-one. That
    cliff is unchanged by the window — it belongs to `_INTERVAL_BEFORE_RE`'s own bound,
    and it is pinned here so a later change to the window cannot quietly move it.
    """
    for gap in (1, 40, 600, 3000):
        assert detect_citations(f"See Figure{' ' * gap}[3] for the effect.") == ()

    assert detect_citations(f"a 95% CI{' ' * 20}[2, 5] wide") == ()
    assert len(detect_citations(f"a 95% CI{' ' * 21}[2, 5] wide")) == 2


def test_a_cue_still_suppresses_a_marker_behind_very_long_words():
    """PR #64's review. The window counts words because words are what these grammars
    bound, and a character window is not the same thing.

    `_DETERMINER_BEFORE_RE` allows three intervening words and says nothing about how long
    a word may be, so "Die" plus three 200-character tokens stays inside the grammar while
    leaving any fixed character window — and PDF extraction produces runs like that
    whenever it loses the spaces between words. The same applies with the whole distance in
    one token.

    The direction is what makes it worth a test rather than a note: the window *emitted* a
    marker the unbounded search suppressed. A false positive reaches a reviewer as an
    orphaned citation — an authoring error that is not there — which this module treats as
    the more expensive of the two failures everywhere else.
    """
    for word_count, word_length in ((3, 200), (1, 600), (2, 400), (3, 700)):
        words = " ".join(letter * word_length for letter in "abc"[:word_count])
        assert detect_citations(f"Die {words} Doe (2020) berichtet.") == ()

    # Still detected once the phrase leaves the grammar: four intervening words is not a
    # determiner phrase however short they are, and suppressing it would be the opposite
    # error.
    assert len(detect_citations("Die a b c d Doe (2020) berichtet.")) == 1


def test_an_interval_cue_split_by_a_column_break_still_suppresses():
    """The other half of the same lesson, found while fixing the first.

    `_INTERVAL_BEFORE_RE` spells one of its cues "scale\\s+from", and that whitespace is as
    unbounded as the whitespace before the marker — extraction can put a column break
    between the two words of a single cue. Walking back a fixed number of characters loses
    it; walking back a fixed number of *words* does not, whatever sits between them.
    """
    assert detect_citations("auf einer scale" + " " * 600 + "from [2, 5] wide") == ()
    assert detect_citations("eine scale from a b c d e f g h i [2, 5] wide") == ()
    """Guards the one character past the marker that the notes check has to see.

    `_opens_a_note` asks whether the line begins with a bracket number, using a pattern
    that ends in a lookahead for whitespace-or-end-of-text. It reads a window now rather
    than the whole rest of the document, and a window stopping *on* the closing bracket
    would satisfy that lookahead with its own edge — turning every line-initial marker
    into a suppressed note, whatever followed it.
    """
    glued = detect_citations("A finished sentence.\n[1]x and the text continues.")
    note = detect_citations("A finished sentence.\n[1] Kahneman argues something else.")

    assert [c.number for c in glued] == [1]
    assert note == ()


# --------------------------------------------------------------------------------------
# Shared vocabulary
# --------------------------------------------------------------------------------------


def test_the_no_date_vocabulary_is_the_one_the_bibliography_path_reads():
    """Splitting NO_DATE out of NO_DATE_RE must not have changed NO_DATE_RE.

    The whole point of taking the in-text form from signals.py is that the two paths
    cannot drift; a refactor that quietly narrowed the bibliography's own pattern while
    doing it would have defeated that in the same commit.

    The expected pattern is written out rather than rebuilt from NO_DATE, because a test
    that recomputes the implementation restates it: narrowing the constant would narrow
    both sides and pass. This is the one place the vocabulary is spelled twice on
    purpose.
    """
    assert NO_DATE_RE.pattern == r"\((?:n\.\s?d\.|no date|in press|forthcoming|o\.\s?J\.|im Druck)\)"
    assert NO_DATE_RE.pattern == rf"\({NO_DATE}\)"
    assert NO_DATE_RE.flags & re.IGNORECASE
    assert all(NO_DATE_RE.search(f"({form})") for form in ("n.d.", "no date", "in press", "o. J.", "im Druck"))


@pytest.mark.parametrize("form", ["n.d.", "n. d.", "no date", "in press", "forthcoming", "o. J.", "im Druck"])
def test_every_no_date_form_is_detectable_in_text(form):
    found = detect_citations(f"The guidance stands (Doe, {form}).")

    assert [c.year for c in found] == [form]


def test_an_institutional_author_is_not_detected():
    """A recorded limit, pinned so Phase 4 does not assume it away.

    The synthetic manuscripts carry two of these ("World Health Organization",
    "R Core Team") but only in their numbered documents, where a marker is an index and
    the name never has to be read — so the recall corpus passes without touching this.
    Admitting a multi-word capitalised phrase as an author run is what would fix it, and
    that is indistinguishable from the start of an ordinary English sentence; see this
    module's Known limits for why the entry side is the cheaper place to solve it.
    """
    assert detect_citations("Guidance was issued (World Health Organization, 1948).") == ()
    assert detect_citations("Analyses used R (R Core Team, 2023).") == ()

    narrative = detect_citations("World Health Organization (1948) issued the first guidance.")

    assert [c.authors for c in narrative] == ["Organization"]


# --------------------------------------------------------------------------------------
# Corpus hygiene
# --------------------------------------------------------------------------------------


def test_case_ids_are_unique_across_style_files():
    seen: dict[str, str] = {}
    duplicates = {}
    for case in CASES:
        if case["id"] in seen:
            duplicates[case["id"]] = (seen[case["id"]], case["style"])
        seen[case["id"]] = case["style"]

    assert not duplicates, f"case ids reused across style files: {duplicates}"


def test_every_case_states_what_it_pins():
    """A case with no note is a case nobody can maintain.

    The corpus's value is that a red case explains itself — the alternative is a failing
    string comparison and a guess at whether the expectation or the detector is wrong.
    """
    unexplained = [case["id"] for case in CASES if not case.get("note")]

    assert not unexplained, f"cases with no note: {unexplained}"


def test_every_style_file_declares_a_family_the_detector_knows():
    known = {family.value for family in MarkerFamily} | {"none"}
    unknown = {key: style["family"] for key, style in STYLES.items() if style["family"] not in known}

    assert not unknown, f"style files declaring an unknown marker family: {unknown}"


def test_every_case_restricts_families_to_names_the_detector_knows():
    known = {family.value for family in MarkerFamily}
    unknown = {
        case["id"]: [name for name in case["families"] if name not in known]
        for case in CASES
        if "families" in case
    }

    assert not any(unknown.values()), f"cases restricting to unknown families: {unknown}"


def test_the_corpus_covers_both_marker_families_and_their_exclusions():
    """A corpus that only proves the detector fires is half a corpus.

    The exclusion cases are the ones that matter most — a spurious marker becomes a
    displayed orphaned citation — so their presence is asserted rather than assumed.
    """
    detected_families = {
        citation["family"] for case in CASES for citation in case["expect"]["citations"]
    }
    exclusions = [case for case in CASES if not case["expect"]["citations"]]

    assert detected_families == {family.value for family in MarkerFamily}
    assert len(exclusions) >= len(MarkerFamily)


def test_meta_documents_the_case_schema_the_loader_applies():
    """meta.json is what a later contributor reads instead of the loader.

    A field the loader defaults but meta.json never mentions is a field nobody knows
    they can omit — or, worse, one they assume is unchecked.
    """
    documented = set(META["case_schema"]) | set(META["case_schema"]["expect"])

    assert {"id", "note", "text", "families", "expect", "citations"} <= documented
