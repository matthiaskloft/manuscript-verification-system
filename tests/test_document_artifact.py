"""Tests for the position-tracked body-text artifact (Phase 1 of the in-text
citation plan, docs/plans/plan-in-text-citation-parsing.md).

Two things are worth more than the rest here: that a span's offsets are exact slices
of body_text rather than approximations, and that source_line still points at the
right raw line after the normalization chain has dropped and merged lines around it.
The second is the one that can rot silently — a new normalization pass that forgets to
retag looks fine in every other test in the suite.
"""

from pathlib import Path

import pytest

from openrefcheck.extraction.document import (
    build_document_artifact,
    extract_full_text,
    normalize_markdown_text,
    _normalize_markdown_line,
    _normalize_markdown_lines,
)
from openrefcheck.extraction.document_artifact import (
    DocumentArtifact,
    SourceLine,
    concat_tag,
    origin_at,
    origin_of,
    retag,
)
from openrefcheck.extraction.intext_signals import detect_citations


def artifact_from_text(text: str, *, raw_text: str | None = None) -> DocumentArtifact:
    raw = text if raw_text is None else raw_text
    lines = [SourceLine(line, i) for i, line in enumerate(text.splitlines())]
    return DocumentArtifact.from_lines(lines, raw_text=raw, parser="test")


# --- SourceLine ------------------------------------------------------------------


def test_source_line_is_an_ordinary_string():
    # The whole reason document.py's normalization passes can carry provenance without
    # being rewritten: every str operation they perform still works.
    line = SourceLine("  ## References  ", 7)

    assert line == "  ## References  "
    assert line.strip() == "## References"
    assert {line: 1}["  ## References  "] == 1
    assert origin_of(line) == 7


def test_untagged_string_has_no_origin_rather_than_line_zero():
    assert origin_of("plain text") is None
    assert origin_of(retag("derived", "plain text")) is None


def test_retag_carries_origin_to_a_newly_built_string():
    merged = retag("first second", SourceLine("first", 3))

    assert merged == "first second"
    assert origin_of(merged) == 3


# --- paragraph spans -------------------------------------------------------------


def test_paragraph_spans_are_exact_slices_of_body_text():
    artifact = artifact_from_text("First para line one.\nStill para one.\n\nSecond para.")

    assert len(artifact.paragraphs) == 2
    for paragraph in artifact.paragraphs:
        assert artifact.body_text[paragraph.start : paragraph.end] == paragraph.text
    assert artifact.paragraphs[0].text == "First para line one.\nStill para one."
    assert artifact.paragraphs[1].text == "Second para."


def test_paragraph_takes_the_source_line_of_its_first_line():
    artifact = artifact_from_text("Alpha.\nBeta.\n\nGamma.")

    assert artifact.paragraphs[0].source_line == 0
    assert artifact.paragraphs[1].source_line == 3


def test_repeated_and_trailing_blank_lines_do_not_create_empty_paragraphs():
    artifact = artifact_from_text("Alpha.\n\n\n\nBeta.\n\n\n")

    assert [p.text for p in artifact.paragraphs] == ["Alpha.", "Beta."]


def test_empty_document_has_no_paragraphs():
    artifact = artifact_from_text("")

    assert artifact.paragraphs == ()
    assert artifact.paragraph_at(0) is None


# --- anchoring -------------------------------------------------------------------


def test_anchor_for_resolves_a_span_to_its_paragraph_and_source_line():
    artifact = artifact_from_text("Intro sentence.\n\nAs shown by Doe (2020), the effect holds.")
    start = artifact.body_text.index("Doe (2020)")

    anchor = artifact.anchor_for(start, start + len("Doe (2020)"))

    assert anchor is not None
    assert artifact.body_text[anchor.start : anchor.end] == "Doe (2020)"
    assert anchor.paragraph_index == 1
    assert anchor.source_line == 2


def test_anchor_for_returns_none_for_a_span_outside_any_paragraph():
    artifact = artifact_from_text("Alpha.\n\nBeta.")
    blank_offset = artifact.body_text.index("\n\n") + 1

    assert artifact.anchor_for(blank_offset, blank_offset + 1) is None


@pytest.mark.parametrize("leading", [0, 1, 2], ids=["separator_start", "mid_separator", "paragraph_start"])
def test_anchor_for_accepts_a_span_that_starts_on_a_blank_line_but_reaches_a_paragraph(leading):
    """The span is "Beta.", however much of the separator before it got included.

    Checking `paragraph_index` alone was not enough: it was right while `source_line`
    resolved the *separator's* origin — the raw line before the passage, the one piece
    of text the span demonstrably is not. Both coordinates have to name the same
    paragraph or the anchor contradicts itself.
    """
    artifact = artifact_from_text("Alpha.\n\nBeta.")
    start = artifact.body_text.index("\n\n") + leading

    anchor = artifact.anchor_for(start, len(artifact.body_text))

    assert anchor is not None
    assert anchor.paragraph_index == 1
    assert anchor.source_line == 2
    assert artifact.raw_line_text(anchor.source_line) == "Beta."


def test_anchor_for_rejects_out_of_range_and_empty_spans():
    artifact = artifact_from_text("Alpha.")

    assert artifact.anchor_for(-1, 3) is None
    assert artifact.anchor_for(0, len(artifact.body_text) + 1) is None
    assert artifact.anchor_for(2, 2) is None


def test_paragraph_at_returns_none_on_a_blank_line():
    artifact = artifact_from_text("Alpha.\n\nBeta.")

    assert artifact.paragraph_at(0).text == "Alpha."
    assert artifact.paragraph_at(artifact.body_text.index("\n\n") + 1) is None


# --- occurrence search -----------------------------------------------------------


def test_find_occurrences_returns_every_match_not_just_the_first():
    # A repeated marker is several real citations; collapsing them would undercount
    # "cited N times" and could turn a cited reference into a spurious unused one.
    artifact = artifact_from_text("Doe (2020) found it.\n\nLater work (Doe, 2020) agrees with Doe (2020).")

    anchors = artifact.find_occurrences("Doe (2020)")

    assert len(anchors) == 2
    assert [a.paragraph_index for a in anchors] == [0, 1]
    assert all(artifact.body_text[a.start : a.end] == "Doe (2020)" for a in anchors)


def test_find_occurrences_is_empty_for_absent_and_empty_needles():
    artifact = artifact_from_text("Alpha.")

    assert artifact.find_occurrences("Beta") == ()
    assert artifact.find_occurrences("") == ()


def test_find_occurrences_does_not_return_overlapping_matches():
    artifact = artifact_from_text("aaaa")

    assert len(artifact.find_occurrences("aa")) == 2


# --- context lookup --------------------------------------------------------------


def test_snippet_is_clipped_to_its_own_paragraph():
    artifact = artifact_from_text("Neighbouring paragraph text.\n\nShort target here.\n\nAnother neighbour.")
    start = artifact.body_text.index("target")
    anchor = artifact.anchor_for(start, start + len("target"))

    snippet = artifact.snippet(anchor, radius=500)

    assert snippet == "Short target here."
    assert "Neighbouring" not in snippet
    assert "Another neighbour" not in snippet


def test_snippet_narrows_to_the_requested_radius():
    artifact = artifact_from_text("x" * 200 + " target " + "y" * 200)
    start = artifact.body_text.index("target")
    anchor = artifact.anchor_for(start, start + len("target"))

    snippet = artifact.snippet(anchor, radius=5)

    assert snippet == "xxxx target yyyy"


def test_paragraph_text_expands_to_the_full_paragraph():
    artifact = artifact_from_text("Alpha.\n\nA longer second paragraph\nwrapped over two lines.")
    start = artifact.body_text.index("wrapped")
    anchor = artifact.anchor_for(start, start + len("wrapped"))

    assert artifact.paragraph_text(anchor) == "A longer second paragraph\nwrapped over two lines."


def test_raw_line_text_returns_the_pre_normalization_line():
    raw = "# Heading\n\n**Bold body text.**"
    artifact = artifact_from_text("Heading\n\nBold body text.", raw_text=raw)

    assert artifact.raw_line_text(artifact.paragraphs[1].source_line) == "**Bold body text.**"
    assert artifact.raw_line_text(None) is None
    assert artifact.raw_line_text(999) is None


# --- provenance through the normalization chain ----------------------------------


def test_source_line_survives_dropped_page_footers():
    # The footer "12" is dropped, so every line after it shifts by one in the
    # normalized output while its raw-line index must not.
    raw = "Body paragraph one.\n\n12\n\nBody paragraph two."
    lines = _normalize_markdown_lines(raw.splitlines())
    artifact = DocumentArtifact.from_lines(lines, raw_text=raw, parser="test")

    assert [p.text for p in artifact.paragraphs] == ["Body paragraph one.", "Body paragraph two."]
    assert artifact.paragraphs[1].source_line == 4
    assert artifact.raw_line_text(artifact.paragraphs[1].source_line) == "Body paragraph two."


def test_source_line_survives_markdown_marker_stripping():
    raw = "Introduction.\n\n**Emphasised body text.**"
    lines = _normalize_markdown_lines(raw.splitlines())
    artifact = DocumentArtifact.from_lines(lines, raw_text=raw, parser="test")

    assert artifact.paragraphs[1].text == "Emphasised body text."
    assert artifact.raw_line_text(artifact.paragraphs[1].source_line) == "**Emphasised body text.**"


def test_body_paragraphs_can_be_merged_by_the_bibliography_tuned_chain():
    """Pins a known coarseness rather than asserting it is desirable.

    _merge_mid_entry_paragraph_breaks joins a blank-line-separated pair whenever the
    line before the blank doesn't look like a finished reference. In a reference list
    that recovers entries split across a column break; over body text it also joins a
    section heading to the prose under it, because a heading has no terminal
    punctuation either. It costs the citation feature nothing — the text and its
    ordering are intact, and detection works on offsets, not paragraph identity — but
    a consumer using paragraph boundaries as document structure needs to know they are
    approximate here. Applying a *different* normalization to body text was the
    alternative, and a second definition of "normalized text" is the divergence
    signals.py exists to prevent.
    """
    raw = "Methods\n\nWe follow Doe (2020)."
    lines = _normalize_markdown_lines(raw.splitlines())
    artifact = DocumentArtifact.from_lines(lines, raw_text=raw, parser="test")

    assert len(artifact.paragraphs) == 1
    assert artifact.paragraphs[0].text == "Methods We follow Doe (2020)."


def test_a_span_after_a_merge_resolves_to_its_own_raw_line():
    """The regression the segment map exists for.

    While a merged line carried one origin, every span in it claimed the *first*
    fragment's raw line. Because the merge above folds a heading into the prose under
    it, that meant every citation in every synthetic fixture — 121 of 121 — resolved to
    its section heading. The paragraph-level answer is still available and still
    correct; it is simply not the answer a span asked for.
    """
    raw = "Methods\n\nWe follow Doe (2020)."
    lines = _normalize_markdown_lines(raw.splitlines())
    artifact = DocumentArtifact.from_lines(lines, raw_text=raw, parser="test")
    start = artifact.body_text.index("Doe (2020)")

    anchor = artifact.anchor_for(start, start + len("Doe (2020)"))

    assert anchor is not None
    assert anchor.source_line == 2
    assert "Doe (2020)" in artifact.raw_line_text(anchor.source_line)
    assert anchor.paragraph_source_line == 0


def test_a_segment_boundary_survives_markdown_stripping():
    """A line merged *before* the Markdown pass gets rewritten underneath its segments.

    The page-break merge runs first, so its two origins are already in place when
    marker stripping shortens the text around them. A boundary recorded against the
    pre-strip text would land mid-word — here three characters late, the width of the
    "## " that goes away.
    """
    raw = "## Sentence continuing,\n\n7\n\n**finishing here.**"
    lines = _normalize_markdown_lines(raw.splitlines())
    artifact = DocumentArtifact.from_lines(lines, raw_text=raw, parser="test")
    start = artifact.body_text.index("finishing")

    assert artifact.body_text == "Sentence continuing, finishing here."
    assert artifact.source_line_at(start) == 4
    assert artifact.source_line_at(0) == 0


def test_a_twice_merged_line_keeps_all_three_origins():
    merged = concat_tag("a b", SourceLine("a", 0), SourceLine("b", 4), 2)
    twice = concat_tag("a b c", merged, SourceLine("c", 9), 4)

    assert [origin_at(twice, offset) for offset in (0, 2, 4)] == [0, 4, 9]


def test_merged_page_break_continuation_anchors_to_where_it_starts():
    raw = "Sentence continuing across a page,\n\n7\n\nfinishing on the next page."
    lines = _normalize_markdown_lines(raw.splitlines())
    artifact = DocumentArtifact.from_lines(lines, raw_text=raw, parser="test")

    assert artifact.paragraphs[0].text == "Sentence continuing across a page, finishing on the next page."
    assert artifact.paragraphs[0].source_line == 0


def test_every_paragraph_source_line_round_trips_to_real_raw_text():
    raw = (
        "# A Study\n\n"
        "Introductory prose citing Doe (2020).\n\n"
        "3\n\n"
        "**More prose** citing Roe (2019).\n\n"
        "Closing remarks.\n"
    )
    lines = _normalize_markdown_lines(raw.splitlines())
    artifact = DocumentArtifact.from_lines(lines, raw_text=raw, parser="test")

    assert artifact.paragraphs
    for paragraph in artifact.paragraphs:
        raw_line = artifact.raw_line_text(paragraph.source_line)
        assert raw_line is not None
        # A paragraph begins where its raw line does, once that line's Markdown
        # decoration is stripped — it can continue past it (a wrap or a merge), but it
        # can never start somewhere else.
        assert paragraph.text.startswith(_normalize_markdown_line(raw_line).strip())


# --- body/bibliography split -----------------------------------------------------


def write_docx(tmp_path: Path, *paragraphs: str) -> Path:
    docx = pytest.importorskip("docx")
    path = tmp_path / "manuscript.docx"
    document = docx.Document()
    for text in paragraphs:
        document.add_paragraph(text)
    document.save(str(path))
    return path


def test_build_document_artifact_excludes_the_bibliography(tmp_path):
    path = write_docx(
        tmp_path,
        "Introduction citing Doe (2020).",
        "References",
        "Doe, J. (2020). A title. Journal, 1(1), 1-10.",
    )

    artifact = build_document_artifact(path)

    assert "Introduction citing Doe (2020)." in artifact.body_text
    assert "References" not in artifact.body_text
    assert "Journal, 1(1), 1-10" not in artifact.body_text
    assert artifact.parser == "python-docx"


def test_build_document_artifact_keeps_text_after_the_bibliography(tmp_path):
    # An appendix cites references too; dropping it would report every
    # appendix-only citation's target as an unused reference.
    path = write_docx(
        tmp_path,
        "Introduction citing Doe (2020).",
        "References",
        "Doe, J. (2020). A title. Journal, 1(1), 1-10.",
        "Appendix",
        "Further analysis following Roe (2019).",
    )

    artifact = build_document_artifact(path)

    assert "Further analysis following Roe (2019)." in artifact.body_text
    assert "Doe, J. (2020). A title." not in artifact.body_text


def test_docx_consecutive_paragraphs_stay_separate(tmp_path):
    # python-docx paragraphs arrive joined by a single newline, with no blank line
    # between them. Read as body text that means one paragraph, not three — so this
    # asserts the boundaries a DOCX actually has, not the ones its serialization
    # happens to make visible.
    path = write_docx(
        tmp_path,
        "First body paragraph citing Doe (2020).",
        "Second body paragraph citing Roe (2019).",
        "Third body paragraph.",
        "References",
        "Doe, J. (2020). A title.",
    )

    artifact = build_document_artifact(path)

    assert [p.text for p in artifact.paragraphs] == [
        "First body paragraph citing Doe (2020).",
        "Second body paragraph citing Roe (2019).",
        "Third body paragraph.",
    ]
    assert [p.source_line for p in artifact.paragraphs] == [0, 1, 2]


def test_docx_anchor_resolves_to_its_own_paragraph_and_source_line(tmp_path):
    path = write_docx(
        tmp_path,
        "First body paragraph citing Doe (2020).",
        "Second body paragraph citing Roe (2019).",
        "References",
        "Doe, J. (2020). A title.",
    )
    artifact = build_document_artifact(path)

    anchor = artifact.find_occurrences("Roe (2019)")[0]

    assert anchor.paragraph_index == 1
    assert anchor.source_line == 1
    assert artifact.raw_line_text(anchor.source_line) == "Second body paragraph citing Roe (2019)."


def test_docx_context_expansion_cannot_reach_a_neighbouring_paragraph(tmp_path):
    # paragraph_text is what the reviewer sees when they expand a snippet, so the
    # artifact's paragraph is the boundary of that disclosure. Collapsed DOCX
    # paragraphs would have made "expand" mean "show the whole manuscript body".
    path = write_docx(
        tmp_path,
        "Confidential unrelated paragraph.",
        "The cited claim rests on Doe (2020).",
        "Another unrelated paragraph.",
        "References",
        "Doe, J. (2020). A title.",
    )
    artifact = build_document_artifact(path)
    anchor = artifact.find_occurrences("Doe (2020)")[0]

    expanded = artifact.paragraph_text(anchor)

    assert expanded == "The cited claim rests on Doe (2020)."
    assert "Confidential unrelated paragraph." not in expanded
    assert "Another unrelated paragraph." not in expanded
    assert artifact.snippet(anchor, radius=500) == expanded


def test_docx_blank_paragraph_does_not_create_an_empty_artifact_paragraph(tmp_path):
    path = write_docx(tmp_path, "First paragraph.", "", "Second paragraph.")

    artifact = build_document_artifact(path)

    assert [p.text for p in artifact.paragraphs] == ["First paragraph.", "Second paragraph."]
    assert [p.source_line for p in artifact.paragraphs] == [0, 2]


def test_build_document_artifact_without_a_bibliography_heading_keeps_everything(tmp_path):
    path = write_docx(tmp_path, "Just prose citing Doe (2020).", "More prose.")

    artifact = build_document_artifact(path)

    assert "Just prose citing Doe (2020)." in artifact.body_text
    assert "More prose." in artifact.body_text


def test_build_document_artifact_rejects_unsupported_suffix(tmp_path):
    bogus = tmp_path / "manuscript.txt"
    bogus.write_text("hello")

    with pytest.raises(ValueError, match="Unsupported file type"):
        build_document_artifact(bogus)


def test_build_document_artifact_on_a_pdf_anchors_into_the_original_markdown(tmp_path):
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Introduction citing Doe (2020).")
    page.insert_text((72, 100), "References")
    page.insert_text((72, 128), "Doe, J. (2020). A title.")
    path = tmp_path / "manuscript.pdf"
    doc.save(str(path))
    doc.close()

    artifact = build_document_artifact(path)

    assert artifact.parser == "pymupdf4llm"
    assert "Introduction citing Doe (2020)." in artifact.body_text
    assert "Doe, J. (2020). A title." not in artifact.body_text
    anchor = artifact.find_occurrences("Doe (2020)")[0]
    assert anchor.source_line is not None
    assert "Doe (2020)" in artifact.raw_line_text(anchor.source_line)


# --- regression: tagging changed no existing behavior -----------------------------


def test_normalize_markdown_text_output_is_unchanged_by_tagging():
    # Provenance tagging must be invisible to every existing caller: the normalization
    # chain still returns plain-looking text, byte for byte.
    raw = "Body paragraph one.\n\n12\n\n**Body** paragraph two.\n\nReferences\n\nDoe, J. (2020). A title."

    assert normalize_markdown_text(raw) == "Body paragraph one.\n\nBody paragraph two.\n\nReferences\n\nDoe, J. (2020). A title."


def test_extract_full_text_is_unaffected_by_artifact_building(tmp_path):
    path = write_docx(tmp_path, "Introduction.", "References", "Doe, J. (2020). A title.")

    before = extract_full_text(path)
    build_document_artifact(path)

    assert extract_full_text(path) == before


def test_the_artifact_does_not_quote_the_manuscript_in_its_repr():
    """The citation plan requires a raw passage never to reach a log, an error message or
    a crash report, and a dataclass repr is how one gets there without anyone deciding to
    put it there. This object *is* the manuscript, and Phase 4 put it inside the pipeline's
    result bundle and the session state — the two things most likely to be printed while
    debugging or captured by a crash reporter.
    """
    lines = ["A body paragraph whose text must not be quoted back.", "", "A second paragraph."]
    artifact = DocumentArtifact.from_lines(lines, raw_text="\n".join(lines), parser="test")

    assert "must not be quoted back" not in repr(artifact)
    assert "must not be quoted back" not in repr(artifact.paragraphs[0])
    assert "second paragraph" not in repr(artifact)
    # Still reachable for the consumer that is allowed to show it.
    assert artifact.paragraphs[0].text.startswith("A body paragraph")


# --- sentence bounds (the context viewer's collapsed depth) -------------------------


def _sentence_around(text: str, target: str) -> str:
    artifact = artifact_from_text(text)
    start = artifact.body_text.index(target)
    return artifact.sentence(artifact.anchor_for(start, start + len(target)))


def test_the_sentence_is_returned_whole_rather_than_a_character_window():
    """What this replaced cut mid-word at both ends ("… he network perspective has
    inspired …"), leaving a reviewer to judge whether a citation belonged from a fragment
    that began in the middle of a word."""
    text = (
        "An earlier sentence sets something up. The effect replicates (Author, 2020) in "
        "every sample. A later sentence continues."
    )

    assert _sentence_around(text, "(Author, 2020)") == (
        "The effect replicates (Author, 2020) in every sample."
    )


@pytest.mark.parametrize(
    "marker",
    ["Doe (2020)", "(Doe, 2020)", "[1]"],
)
def test_a_marker_that_opens_a_sentence_does_not_drag_the_previous_one_in(marker):
    """Every sentence test above puts its marker mid-sentence, and that is where this hid.

    The boundary immediately before the marker was never found, because the search was
    stopped at `anchor.start` and the pattern needs to see one character past the space to
    know a sentence began there — the character being the marker itself. A narrative
    citation opening a sentence is one of the commonest positions there is, so the
    collapsed view was routinely showing two sentences while saying it shows one. Over-
    disclosure rather than under, but the depth a reviewer chose is the depth they get.
    """
    text = f"A previous sentence ends here. {marker} carries the claim. A third follows."

    assert _sentence_around(text, marker) == f"{marker} carries the claim."


def test_an_abbreviation_before_an_opening_marker_still_holds_the_sentence_together():
    """The other side of the same search, and the reason the filter is on the boundary
    rather than on the position: "cf." looks exactly like a sentence end, so widening the
    search must not turn one sentence into two."""
    text = "An opening claim, cf. Doe (2020) mid-clause, continues past it. A second one."

    assert _sentence_around(text, "Doe (2020)") == (
        "An opening claim, cf. Doe (2020) mid-clause, continues past it."
    )


def test_a_citation_after_an_abbreviation_does_not_split_the_sentence():
    """"e.g." is a period followed by a capital, which is exactly the shape of a sentence
    end — and it turns up immediately before a citation more often than anywhere else."""
    text = "Several later studies (e.g., Epskamp, 2018) reached the same conclusion. Then more."

    assert _sentence_around(text, "Epskamp") == (
        "Several later studies (e.g., Epskamp, 2018) reached the same conclusion."
    )


def test_an_authors_initial_does_not_end_a_sentence():
    text = "The work of Borsboom, D. (2021) is the reference here. A following sentence."

    assert _sentence_around(text, "(2021)") == (
        "The work of Borsboom, D. (2021) is the reference here."
    )


def test_et_al_does_not_end_a_sentence():
    text = "As Smith et al. (2019) showed in a replication. Another sentence follows."

    assert _sentence_around(text, "(2019)").startswith("As Smith et al. (2019) showed")


def test_a_sentence_never_reaches_into_a_neighbouring_paragraph():
    """Same rule as `snippet`: both as context and as disclosure, a passage stops at its
    own paragraph even when that paragraph has no terminal punctuation."""
    text = "A previous paragraph ends here.\n\nA target sentence with no full stop\n\nA third paragraph."

    sentence = _sentence_around(text, "target")

    assert sentence == "A target sentence with no full stop"
    assert "previous" not in sentence
    assert "third" not in sentence


def test_a_single_sentence_paragraph_returns_itself():
    assert _sentence_around("Only one sentence here (Author, 2020).", "(Author, 2020)") == (
        "Only one sentence here (Author, 2020)."
    )


def test_the_bounds_locate_the_marker_inside_the_result():
    """Offsets, not text: the caller highlights the marker at a known position, and
    searching the sentence for the marker's text would find the wrong occurrence when one
    sentence cites the same work twice."""
    text = "First (Author, 2020) and again (Author, 2020) in one sentence. Next."
    artifact = artifact_from_text(text)
    second = artifact.body_text.index("(Author, 2020)", 10)
    anchor = artifact.anchor_for(second, second + len("(Author, 2020)"))

    start, end = artifact.sentence_bounds(anchor)

    assert start <= second < end
    assert artifact.body_text[start:end].strip().endswith("in one sentence.")


# --- a span that straddles a paragraph boundary -----------------------------------


_STRADDLING = "As several have shown (Doe, 2020;\n\nRoe, 2019) the effect is robust."


def _straddling_anchor():
    """A real detector reading, not a hand-built anchor.

    The point of going through `detect_citations` is that this shape is reachable from the
    shipped pipeline rather than only constructible here: a grouped parenthetical whose
    members fall either side of a block boundary, which PDF extraction produces whenever a
    citation group is split across a column or page break.
    """
    artifact = artifact_from_text(_STRADDLING)
    detected = detect_citations(artifact.body_text)
    citation = next(d for d in detected if "Roe" in d.marker_text)
    anchor = artifact.anchor_for(citation.start, citation.end)
    assert anchor is not None
    return artifact, anchor


def test_a_span_crossing_a_paragraph_boundary_is_not_cut_in_half_by_its_context():
    """The defect: `anchor_for` resolves a straddling span to the first paragraph it
    overlaps — correctly, since no single paragraph contains it — but every context method
    then clipped to that paragraph and cut the anchor in two.

    A reviewer checking the citation to Roe 2019 was shown "As several have shown (Doe,
    2020;" — a passage whose one job was to contain the marker, and which stopped just
    before it. Showing a reviewer text that does not say what they were told it says is a
    worse error than quoting one paragraph too many.
    """
    artifact, anchor = _straddling_anchor()
    span = artifact.body_text[anchor.start : anchor.end]

    assert "Roe, 2019)" in span  # the half that used to be lost
    assert span in artifact.snippet(anchor)
    assert span in artifact.sentence(anchor)
    assert span in artifact.paragraph_text(anchor)


def test_context_never_excludes_the_span_it_is_the_context_for():
    """The invariant behind the fix, asserted over ordinary spans as well as straddling
    ones — the plan recorded that nothing checked it, which is why the straddling case went
    unnoticed. `sentence` is excluded from the exact-substring form because it strips."""
    texts = [
        _STRADDLING,
        "One paragraph with (Author, 2020) inside it.",
        "Leading paragraph.\n\nA marker (Author, 2020) here.\n\nTrailing paragraph.",
        "Short (A, 1999).",
        "A group (Doe, 2020; Roe, 2019; Fry, 2018) spanning one line.",
    ]
    for text in texts:
        artifact = artifact_from_text(text)
        for citation in detect_citations(artifact.body_text):
            anchor = artifact.anchor_for(citation.start, citation.end)
            if anchor is None:
                continue
            span = artifact.body_text[anchor.start : anchor.end]
            assert span in artifact.snippet(anchor), (text, span)
            assert span in artifact.paragraph_text(anchor), (text, span)
            assert span.strip() in artifact.sentence(anchor), (text, span)


def test_a_span_inside_one_paragraph_still_stops_at_its_own_paragraph():
    """The widening is not a general loosening: it covers the paragraphs the anchor
    actually runs into and no others, so the disclosure rule the clip enforces is intact
    for every span that does not straddle one."""
    artifact, anchor = _straddling_anchor()
    assert artifact.context_bounds(anchor) == (0, len(artifact.body_text))

    plain = artifact_from_text("Previous paragraph.\n\nA marker (Author, 2020) here.\n\nNext one.")
    start = plain.body_text.index("(Author, 2020)")
    inside = plain.anchor_for(start, start + len("(Author, 2020)"))
    paragraph = plain.paragraphs[inside.paragraph_index]

    assert plain.context_bounds(inside) == (paragraph.start, paragraph.end)
    assert "Previous" not in plain.snippet(inside, radius=200)
    assert "Next" not in plain.snippet(inside, radius=200)
    assert plain.paragraph_text(inside) == paragraph.text
