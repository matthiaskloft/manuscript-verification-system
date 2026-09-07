"""How much of a manuscript's in-text citation markers Tier 0 actually finds.

Every other test of `intext_signals` runs on text written alongside the detector — the
corpus in fixtures/intext_citations/ states what a marker looks like and then checks
that the detector agrees, which cannot falsify a shared misunderstanding of the shape.
This module measures the same detector against markers it had no hand in writing:
biblatex rendered them, from the same maintained apa/chicago/ieee/vancouver style
packages the fixture bibliographies come from, and the manifest records which key each
one stands for before the PDF exists.

That makes both directions checkable at once, which matters because they trade off.
Recall is `\\cite` count versus detections; precision is that the document contains
*only* those citations, so any extra detection is a false positive in running prose.
Asserting equality rather than a threshold is deliberate: these documents are small
enough that a regression on either side should fail here rather than be absorbed.

The numeric styles give the stronger measurement. IEEE and Vancouver number the
bibliography by order of first citation, and the plan cites every entry once in .bib
order, so a detected "[7]" can be checked against a known key instead of merely counted.

What these documents do *not* cover, so the headline figure is not read as more than it
is: a corporate author in an author-date marker (the two in the entry pool sit only in
the numbered documents, and see `intext_signals`' Known limits), a lead-in phrase
("see", "cf."), a no-date form, and anything German. Each of those has corpus coverage
and none of it has been through a real typesetting engine.
"""

import json
import re
import unicodedata
from pathlib import Path

import pytest

from openrefcheck.extraction import document
from openrefcheck.extraction.document import (
    build_document_artifact,
    extract_references,
    find_bibliography_section,
    normalize_markdown_text,
)
from openrefcheck.extraction.intext_signals import MarkerFamily, detect_citations, expected_families
from openrefcheck.extraction.style_profile import compute_style_profile
from openrefcheck.synth.entries import SynthReferenceEntry
from openrefcheck.synth.latex_builder import _KEYS_PER_FORM, plan_citations

SYNTHETIC = Path(__file__).parent / "fixtures" / "synthetic"
MANIFEST = json.loads((SYNTHETIC / "manifest.json").read_text(encoding="utf-8"))

# Which marker grammar each style package writes, as a property of the style rather than
# of what the detector found — the point of the test is to compare the two.
STYLE_FAMILY = {
    "apa7": MarkerFamily.AUTHOR_DATE,
    "chicago-authordate": MarkerFamily.AUTHOR_DATE,
    "ieee": MarkerFamily.NUMBERED,
    "vancouver": MarkerFamily.NUMBERED,
}


def _fold(text: str) -> str:
    """Casefolded and stripped of combining marks, as pymupdf displaces some diacritics."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def _by_marker(cited: list[dict]) -> list[list[dict]]:
    """Planned citations grouped into the `\\cite` each was written in, in document order."""
    return [[c for c in cited if c["marker"] == marker] for marker in dict.fromkeys(c["marker"] for c in cited)]


def _by_span(detected) -> list[list]:
    """Detections grouped by the span they share — the detected counterpart of a marker."""
    return [
        [c for c in detected if (c.start, c.end) == span]
        for span in dict.fromkeys((c.start, c.end) for c in detected)
    ]


def _comparable(text: str) -> str:
    """Folded and punctuation-free, so a title can be looked for inside an extracted entry."""
    return re.sub(r"[^a-z0-9]+", " ", _fold(text)).strip()


def _extract_without_grobid(path: Path):
    """Tier-0 extraction, pinned so the result does not depend on a running GROBID."""
    original = document.is_grobid_available
    document.is_grobid_available = lambda: False
    try:
        return extract_references(path)
    finally:
        document.is_grobid_available = original


@pytest.fixture(scope="module")
def detections():
    """Every document's markers, detected the way the pipeline will detect them.

    The families come from the bibliography's own style evidence rather than from the
    manifest, because that is the only signal available at runtime — and it is part of
    what is being measured: two of these bibliographies show evidence of both families,
    and detection has to stay clean when it is not narrowed.
    """
    found = {}
    for doc in MANIFEST["documents"]:
        artifact = build_document_artifact(SYNTHETIC / doc["pdf"])
        profile = compute_style_profile(find_bibliography_section(normalize_markdown_text(artifact.raw_text)))
        found[doc["pdf"]] = (artifact, detect_citations(artifact.body_text, families=expected_families(profile)))
    return found


def _ids(doc):
    return doc["style"] + "-" + doc["broad_field"]


@pytest.mark.parametrize("doc", MANIFEST["documents"], ids=_ids)
def test_every_rendered_marker_is_detected_and_nothing_else_is(doc, detections):
    _, detected = detections[doc["pdf"]]
    cited = doc["cited"]

    assert len(detected) == len(cited), (
        f"{doc['style']}: {len(detected)} markers detected for {len(cited)} citations — "
        f"detected {[c.marker_text for c in detected]}"
    )
    assert {c.family for c in detected} == {STYLE_FAMILY[doc["style"]]}


@pytest.mark.parametrize("doc", MANIFEST["documents"], ids=_ids)
def test_a_numbered_marker_names_the_reference_the_manifest_says_it_does(doc, detections):
    """The end-to-end claim a numbered style makes checkable: marker N is entry N.

    Phase 4 will do the resolving; this asserts the numbers are there to resolve, which
    is what a detector that quietly dropped or duplicated one would break.
    """
    if STYLE_FAMILY[doc["style"]] is not MarkerFamily.NUMBERED:
        pytest.skip("author-date style: its markers carry names, not indices")

    _, detected = detections[doc["pdf"]]

    assert [c.number for c in detected] == [c["position"] for c in doc["cited"]]


@pytest.mark.parametrize("doc", MANIFEST["documents"], ids=_ids)
def test_an_author_date_marker_carries_the_first_author_of_its_reference(doc, detections):
    """Compared per marker rather than per citation, because a style may reorder the
    references inside a group: the plan writes `\\parencite{milgram1963,festinger1957}`
    and APA renders "(Festinger, 1957; Milgram, 1963)". Which references a marker names
    is ground truth; the order it names them in is the style's business, and Phase 4 must
    not assume the detector's within-group order is the citation order.

    Compared on the head of the surname, not the whole family name, because a style may
    also drop the particle from the in-text form while keeping it in the bibliography:
    Chicago renders "de Beauvoir" as "Beauvoir (2011)". The corpus pins the opposite case
    — a German narrative marker keeps its "von", since the detector reports the author run
    as written. Phase 4's matcher therefore has to tolerate the particle on either side.
    """
    if STYLE_FAMILY[doc["style"]] is not MarkerFamily.AUTHOR_DATE:
        pytest.skip("numbered style: its markers carry indices, not names")

    _, detected = detections[doc["pdf"]]
    by_key = {entry["key"]: entry for entry in doc["entries"]}

    wrong = []
    for planned, markers in zip(_by_marker(doc["cited"]), _by_span(detected), strict=True):
        expected = {_fold(by_key[c["key"]]["authors"][0]["family"]).split()[-1] for c in planned}
        named = [_fold(marker.authors or "") for marker in markers]
        unnamed = {surname for surname in expected if not any(surname in author for author in named)}
        if unnamed:
            wrong.append((sorted(unnamed), markers[0].marker_text))

    assert not wrong, f"{doc['style']}: markers that do not name their reference's first author: {wrong}"


@pytest.mark.parametrize("doc", MANIFEST["documents"], ids=_ids)
def test_a_grouped_marker_is_one_span_naming_several_references(doc, detections):
    """The module's central invariant, which no single-key citation can test.

    A group is one thing a reviewer is sent to and several references to resolve, so the
    records have to share a span and stay separate as records. Getting this wrong in
    either direction is silent: one record per span loses references, one span per record
    sends a reviewer to a marker that is not the one being reported.
    """
    _, detected = detections[doc["pdf"]]
    planned = _by_marker(doc["cited"])

    assert [len(group) for group in _by_span(detected)] == [len(group) for group in planned]
    assert len({(c.start, c.end) for c in detected}) == len(planned)
    assert sum(len(group) for group in planned if len(group) > 1) > 0 or len(doc["cited"]) == 1


@pytest.mark.parametrize("doc", MANIFEST["documents"], ids=_ids)
def test_the_narrative_form_survives_rendering_and_extraction(doc, detections):
    r"""`\textcite` puts the author outside the parentheses; the detector has to say so.

    Only checked for the author-date styles. A numeric style renders \textcite as
    "Shannon [1]" — the name is prose and the marker is the bracket, so there is no
    narrative marker to detect and the manifest's flag says nothing about one.
    """
    if STYLE_FAMILY[doc["style"]] is not MarkerFamily.AUTHOR_DATE:
        pytest.skip("numbered style: \\textcite leaves the author outside the marker")

    _, detected = detections[doc["pdf"]]

    assert [c.narrative for c in detected] == [c["narrative"] for c in doc["cited"]]


@pytest.mark.parametrize("doc", MANIFEST["documents"], ids=_ids)
def test_every_detected_marker_anchors_back_into_the_document(doc, detections):
    """Detection offsets are only useful if a reviewer can be sent to them.

    Phase 1 built the artifact for this and Phase 2's offsets are into its `body_text`;
    nothing until now has run the two together on a real PDF.
    """
    artifact, detected = detections[doc["pdf"]]

    unanchored = [c.marker_text for c in detected if artifact.anchor_for(c.start, c.end) is None]

    assert not unanchored, f"{doc['style']}: markers with no position in the document: {unanchored}"
    assert all(artifact.body_text[c.start : c.end] == c.marker_text for c in detected)


@pytest.mark.parametrize("doc", MANIFEST["documents"], ids=_ids)
def test_every_detected_marker_resolves_to_the_raw_line_it_is_printed_on(doc, detections):
    """An anchor is only a locator if the raw line it names is the one holding the text.

    This is the assertion that was missing, and it did not fail by a little: while a
    merged normalized line carried a single origin, 0 of 121 markers across these five
    documents resolved to a line containing them. Every one landed on its section
    heading, because the pass that recovers column-split bibliography entries also folds
    a heading into the prose beneath it. Checking the anchor against the *raw* text is
    what makes that visible — asserting the paragraph merely starts with its raw line
    passes happily either way.
    """
    artifact, detected = detections[doc["pdf"]]

    misplaced = []
    for citation in detected:
        anchor = artifact.anchor_for(citation.start, citation.end)
        raw_line = artifact.raw_line_text(anchor.source_line) if anchor else None
        if raw_line is None or _comparable(citation.marker_text) not in _comparable(raw_line):
            misplaced.append((citation.marker_text, raw_line))

    assert not misplaced, f"{doc['style']}: markers whose raw line does not contain them: {misplaced}"


@pytest.mark.parametrize("count", [1, 2, 3, 4, 5, 7, 9, 30])
def test_the_plan_cites_every_entry_exactly_once_whatever_the_list_length(count):
    """Without \\nocite{*} an uncited entry leaves the bibliography entirely, so coverage
    is what keeps these PDFs the same reference-extraction fixtures they were.

    Checked against `plan_citations` over awkward lengths rather than against the
    manifest, which cannot fail: both sides of that comparison are derived from the same
    entry list. The lengths that matter are the ones where the form cycle runs out —
    a two-key group needs two entries left, and the "other" document has exactly one.
    """
    entries = [
        SynthReferenceEntry(key=f"k{index}", entry_type="article", broad_field="other", authors=[], year="2020", title="T")
        for index in range(count)
    ]

    plan = plan_citations(entries)

    assert [c.key for c in plan] == [e.key for e in entries]
    assert [c.position for c in plan] == list(range(1, count + 1))
    assert all(len(group) == _KEYS_PER_FORM[group[0]["form"]] for group in _by_marker([vars(c) for c in plan]))


@pytest.mark.parametrize("doc", MANIFEST["documents"], ids=_ids)
def test_a_numbered_bibliography_is_ordered_the_way_the_positions_assume(doc):
    """The assumption under "marker n is entry n", checked against the PDF.

    Everything else here compares a detected number to a manifest position. That is only
    a claim about the *reference* if the rendered bibliography really is ordered by first
    citation — biblatex's behaviour, but this project's fixtures, so it is measured.
    """
    if STYLE_FAMILY[doc["style"]] is not MarkerFamily.NUMBERED:
        pytest.skip("author-date style: its bibliography is alphabetical, not numbered")

    titles = {entry["key"]: entry["title"] for entry in doc["entries"]}
    listed = [_comparable(entry.raw_text) for entry in _extract_without_grobid(SYNTHETIC / doc["pdf"])]

    misplaced = [
        (cited["position"], cited["key"])
        for cited in doc["cited"]
        if _comparable(titles[cited["key"]])[:40] not in listed[cited["position"] - 1]
    ]

    assert not misplaced, f"{doc['style']}: references not listed at the position their marker names: {misplaced}"


def test_the_body_text_of_a_synthetic_manuscript_survives_cleanup():
    """The regression that made this whole measurement impossible.

    Every section used to share one filler paragraph, repeated verbatim four times, and
    normalize_markdown_text's running-header pass deleted all four copies — leaving 343
    characters of body text (a title, an abstract and four headings) with nothing in it
    to detect. A shared paragraph would pass every other test in this file by making
    both counts zero, so the guard is a floor on the text itself.
    """
    lengths = {
        doc["pdf"]: len(build_document_artifact(SYNTHETIC / doc["pdf"]).body_text)
        for doc in MANIFEST["documents"]
        if len(doc["cited"]) > 1
    }

    assert all(length > 1500 for length in lengths.values()), f"body text lost during cleanup: {lengths}"


def test_repeated_paragraphs_are_dropped_from_body_text():
    """Stated as behaviour, not just as a fixture property: the pass that ate the filler
    is a running-header defence and drops any isolated line that repeats, wherever it
    came from. It is why the sections above are worded differently from each other."""
    header = "SYNTHETIC MANUSCRIPT BENCHMARK"
    normalized = normalize_markdown_text(
        "\n\n".join([header, "First section prose that appears once.", header, "Second section prose.", header])
    )

    assert header not in normalized
    assert "First section prose that appears once." in normalized


# What each bibliography's own style evidence supports, measured rather than assumed.
# Chicago is the finding: an author-date bibliography that yields *no* author-date
# evidence, because its years are bare ("Kuhn, Thomas S. 1962.") and none of the three
# counters `expected_families` consults - parenthesised years, comma-years, JSS author
# lines - matches that. It only detects correctly because "no evidence either way"
# resolves upward to both families, the same branch as "evidence of both". So the
# cross-validation is not narrowing anything here; it is declining to.
_EVIDENCE = {
    "apa7-social_behavioral": {MarkerFamily.AUTHOR_DATE},
    "chicago-authordate-humanities_theology": set(MarkerFamily),
    "vancouver-medicine_life_sciences": {MarkerFamily.NUMBERED},
    "ieee-cs_engineering": set(MarkerFamily),
    "apa7-other": set(MarkerFamily),
}


@pytest.mark.parametrize("doc", MANIFEST["documents"], ids=_ids)
def test_the_style_evidence_each_bibliography_offers_is_the_one_recorded(doc):
    """Pinned because it is easy to read a passing detector as a working cross-validation.

    `bare_year_density` is computed and would separate Chicago from a numbered list at a
    glance — 1.39 bare years per line against Vancouver's 1.07 is not much of a gap, which
    is presumably why it is evidence rather than a verdict. Narrowing Chicago is a
    Phase 2 change with its own precision cost; recording what the evidence actually is
    keeps the gap visible until someone decides.
    """
    artifact = build_document_artifact(SYNTHETIC / doc["pdf"])
    profile = compute_style_profile(find_bibliography_section(normalize_markdown_text(artifact.raw_text)))

    assert expected_families(profile) == _EVIDENCE[_ids(doc)]

    if doc["style"] == "chicago-authordate":
        assert (profile.paren_year_matches, profile.comma_year_matches, profile.jss_author_lines) == (0, 0, 0)
        assert profile.bare_year_density > 1


@pytest.mark.parametrize("doc", MANIFEST["documents"], ids=_ids)
def test_a_marker_free_manuscript_is_still_the_precision_baseline(doc, detections):
    """Detection over the same prose with its markers cut out must return nothing.

    The old fixtures could only demonstrate this, since they had no markers at all. It is
    still worth its own assertion, because the counts above would also be equal if the
    detector found the right number of markers in the wrong places. Run over every
    document rather than the first one: which document that is depends on manifest order,
    and a numbered one would make this measure almost nothing.
    """
    artifact, _ = detections[doc["pdf"]]
    without_markers = re.sub(r"\s*[(\[][^)\]]*[)\]]", "", artifact.body_text)

    assert detect_citations(without_markers) == ()
