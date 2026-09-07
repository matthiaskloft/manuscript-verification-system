import json
from pathlib import Path

import pytest

from openrefcheck.extraction import document
from openrefcheck.extraction.document import (
    NoBibliographySectionError,
    _drop_isolated_decorative_list_markers,
    _drop_repeated_isolated_lines,
    _merge_mid_entry_paragraph_breaks,
    _merge_page_break_continuations,
    extract_full_text,
    extract_references,
    find_bibliography_section,
    normalize_markdown_text,
)
from openrefcheck.extraction.engine_status import ENGINE_ANCHOR, ENGINE_GROBID
from openrefcheck.extraction.grobid import GrobidDocument, GrobidUnavailableError
from openrefcheck.extraction.tier0 import RawReferenceEntry

FIXTURES = Path(__file__).parent / "fixtures" / "synthetic"
MANIFEST = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))


def test_find_bibliography_section_basic():
    text = "Intro text.\n\nReferences\nDoe, J. (2020). A title.\nRoe, R. (2019). Another title."
    section = find_bibliography_section(text)
    assert section == "Doe, J. (2020). A title.\nRoe, R. (2019). Another title."


def test_find_bibliography_section_stops_at_appendix():
    text = "References\nDoe, J. (2020). A title.\n\nAppendix\nSupplementary tables here."
    section = find_bibliography_section(text)
    assert "Doe, J." in section
    assert "Supplementary tables" not in section


def test_find_bibliography_section_stops_at_named_appendix():
    text = "References\nDoe, J. (2020). A title.\nAppendix A.\nSupporting material"

    assert find_bibliography_section(text) == "Doe, J. (2020). A title."


def test_find_bibliography_section_stops_at_descriptive_appendix_heading():
    text = "References\nDoe, J. (2020). A title.\nAppendix B Additional analyses\nSupporting material"

    assert find_bibliography_section(text) == "Doe, J. (2020). A title."


def test_find_bibliography_section_stops_at_author_biography():
    text = "References\nDoe, J. (2020). A title.\nAuthors\nBiographical text"

    assert find_bibliography_section(text) == "Doe, J. (2020). A title."


def test_find_bibliography_section_stops_at_received_metadata():
    text = "References\nDoe, J. (2020). A title.\nManuscript received: March 5, 2020"

    assert find_bibliography_section(text) == "Doe, J. (2020). A title."


def test_find_bibliography_section_keeps_reference_starting_with_received():
    # "Received ..." ends the bibliography only as a submission-history metadata line.
    # A reference whose own text opens with the word must not truncate everything
    # after it, so the stop pattern stays heading-shaped (short, no interior period).
    text = (
        "References\nDoe, J. (2020). A title.\n"
        "Received signal strength studies. Journal, 1, 1-10.\n"
        "Roe, R. (2019). Another title."
    )

    section = find_bibliography_section(text)

    assert "Received signal strength studies." in section
    assert "Roe, R. (2019)." in section


def test_find_bibliography_section_scales_with_a_long_run_of_blank_lines():
    # The stop check needs the last non-blank line before it. Re-scanning backwards
    # for that is quadratic, which a bibliography padded with blank lines exposes.
    text = "References\nDoe, J. (2020). A title.\n" + "\n" * 20000 + "Roe, R. (2019). Another title."

    section = find_bibliography_section(text)

    assert section.startswith("Doe, J. (2020).")
    assert section.endswith("Roe, R. (2019). Another title.")


def test_find_bibliography_section_stops_at_appendix_after_a_doi_final_entry():
    # The completed-entry rule can't require a period: an APA entry ending in a DOI
    # has none, and a real appendix heading following one must still be recognized.
    text = (
        "References\nDoe, J. (2020). A title. https://doi.org/10.1000/xyz123\n"
        "Appendix A. Supplementary analyses\nSupporting material here."
    )

    assert find_bibliography_section(text) == "Doe, J. (2020). A title. https://doi.org/10.1000/xyz123"


def test_find_bibliography_section_keeps_wrapped_line_starting_with_received():
    # A wrapped title line ("Received signal strength fingerprints") is short and has
    # no interior period, so length alone can't tell it from submission metadata. The
    # unfinished line above it can: a heading never interrupts an incomplete entry.
    text = (
        "References\nDoe, J. (2020). A title about\n"
        "Received signal strength fingerprints\n"
        "in buildings. Journal, 1, 1-10.\n"
        "Roe, R. (2019). Another title."
    )

    section = find_bibliography_section(text)

    assert "in buildings. Journal, 1, 1-10." in section
    assert "Roe, R. (2019)." in section


def test_find_bibliography_section_keeps_wrapped_line_starting_with_appendix():
    text = (
        "References\nUnited States Congress. Hearings before the committee,\n"
        "Appendix to the Hearings, Volume XXVI\n"
        "Washington. 1946.\n"
        "Roe, R. (2019). Another title."
    )

    section = find_bibliography_section(text)

    assert "Appendix to the Hearings" in section
    assert "Roe, R. (2019)." in section


def test_find_bibliography_section_keeps_reference_starting_with_appendices():
    text = (
        "References\nDoe, J. (2020). A title.\n"
        "Appendices in applied statistics: a review of reporting practice. Journal, 2, 1-9.\n"
        "Roe, R. (2019). Another title."
    )

    section = find_bibliography_section(text)

    assert "Appendices in applied statistics" in section
    assert "Roe, R. (2019)." in section


def test_expand_markdown_table_reference_rows_recovers_numbered_entries():
    lines = [
        "|**9.**<br>Doe AB. First title. Journal. 2020.<br>**10.**<br>Roe CD. Second title. Journal. 2021.|",
        "|---|",
    ]

    assert document._expand_markdown_table_reference_rows(lines) == [
        "9. Doe AB. First title. Journal. 2020.",
        "10. Roe CD. Second title. Journal. 2021.",
        "|---|",
    ]


def test_find_bibliography_section_case_insensitive_and_german_heading():
    text = "Einleitung.\n\nLITERATURVERZEICHNIS\nMeier, T. (2019). Ein Titel."
    section = find_bibliography_section(text)
    assert section == "Meier, T. (2019). Ein Titel."


def test_find_bibliography_section_uses_first_heading_not_last():
    # A running header repeating "References" on every page of a multi-page
    # bibliography must not cause everything before the last repeat to be dropped.
    text = "References\nEntry one.\nReferences\nEntry two."
    section = find_bibliography_section(text)
    assert "Entry one." in section
    assert "Entry two." in section


def test_find_bibliography_section_raises_without_heading():
    with pytest.raises(NoBibliographySectionError):
        find_bibliography_section("Just some prose with no bibliography heading at all.")


def test_extract_full_text_rejects_unsupported_suffix(tmp_path):
    bogus = tmp_path / "manuscript.txt"
    bogus.write_text("hello")
    with pytest.raises(ValueError, match="Unsupported file type"):
        extract_full_text(bogus)


def test_extract_full_text_docx_round_trip(tmp_path):
    docx = pytest.importorskip("docx")
    path = tmp_path / "manuscript.docx"
    document = docx.Document()
    document.add_paragraph("Introduction text.")
    document.add_paragraph("References")
    document.add_paragraph("Doe, J. (2020). A title. Journal, 1(1), 1-10.")
    document.add_paragraph("Roe, R. (2019). Another title. Journal, 2(2), 11-20.")
    document.save(str(path))

    entries = extract_references(path)
    assert len(entries) == 2
    assert entries[0].raw_text.startswith("Doe, J.")
    assert entries[1].raw_text.startswith("Roe, R.")


def test_extract_pdf_text_drops_isolated_page_footer_numbers(tmp_path):
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    page1 = doc.new_page()
    page1.insert_text((72, 72), "References\nDoe, J. (2020). A title.")
    page1.insert_text((72, 700), "1")  # page-footer number, own last line
    page2 = doc.new_page()
    page2.insert_text((72, 72), "Roe, R. (2019). Another title.")
    page2.insert_text((72, 700), "2")
    path = tmp_path / "manuscript.pdf"
    doc.save(str(path))
    doc.close()

    text = extract_full_text(path)
    lines = text.splitlines()

    # The page-footer numbers "1" and "2" must be dropped as their own lines — a bare
    # number sitting alone in its own blank-delimited paragraph, exactly what
    # pymupdf4llm produces for a page footer — so tier0's blank-line-separator
    # heuristic doesn't pick them up as spurious extra entries.
    assert "1" not in lines
    assert "2" not in lines
    assert "Doe, J." in text
    assert "Roe, R." in text


def test_merge_page_break_continuations_rejoins_long_author_list():
    lines = [
        "References",
        "",
        "Able, A., Baker, B., Carter, C.,",
        "",
        "12",
        "",
        "Diaz, D., Evans, E., and Foster, F. (2024). A long synthetic reference. "
        "Psychological Methods. doi:10.1037/met0000687.",
        "",
        "Young, Y. (2025). The next reference. Journal of Examples, 1, 1-2.",
    ]

    result = _merge_page_break_continuations(lines)

    assert (
        "Able, A., Baker, B., Carter, C., Diaz, D., Evans, E., and Foster, F. (2024). "
        "A long synthetic reference. Psychological Methods. doi:10.1037/met0000687."
        in result
    )
    assert "Young, Y. (2025). The next reference. Journal of Examples, 1, 1-2." in result


def test_merge_page_break_continuations_keeps_complete_reference_boundary():
    lines = [
        "References",
        "",
        "Able, A. (2024). A complete reference. doi:10.1234/example",
        "",
        "12",
        "",
        "Baker, B. (2025). The next reference.",
    ]

    assert _merge_page_break_continuations(lines) == lines


def test_extract_reference_split_across_fixture_page_break():
    path = FIXTURES / "corruption_variants" / "reference_page_break.pdf"

    entries = extract_references(path, engine=ENGINE_ANCHOR)

    assert len(entries) == 2
    long_reference = entries[0].raw_text
    assert long_reference.startswith("Van Den Akker")
    assert "Dechterenko" in long_reference
    assert "The potential of preregistration in psychology" in long_reference
    assert "10.1037/met0000687" in long_reference
    assert entries[1].raw_text.startswith("Kahneman, D.")
    assert "10.2307/1914185" in entries[1].raw_text


def test_drop_repeated_isolated_lines_removes_running_footer_with_page_number():
    lines = [
        "References",
        "",
        "Doe, J. (2020). A title. Journal, 1(1), 1-10.",
        "",
        "www.example.org * A Study 501",
        "",
        "Roe, R. (2019). Another title. Journal, 2(2), 11-20.",
        "",
        "www.example.org * A Study 502",
    ]

    result = _drop_repeated_isolated_lines(lines)

    assert "www.example.org * A Study 501" not in result
    assert "www.example.org * A Study 502" not in result
    assert "Doe, J. (2020). A title. Journal, 1(1), 1-10." in result
    assert "Roe, R. (2019). Another title. Journal, 2(2), 11-20." in result


def test_drop_repeated_isolated_lines_keeps_a_single_occurrence():
    # A footer/header that only appears once (e.g. a single-page document) isn't
    # distinguishable from real, isolated one-line content by repetition alone, so it
    # must be left alone rather than guessed at.
    lines = ["References", "", "Doe, J. (2020). A title.", "", "www.example.org * A Study 501"]

    result = _drop_repeated_isolated_lines(lines)

    assert "www.example.org * A Study 501" in result


def test_drop_repeated_isolated_lines_keeps_a_repeated_sentence_of_prose():
    # Two occurrences is a low bar and ordinary body text clears it: a table note under
    # two tables, a methods sentence repeated across two studies. Deleting those loses
    # the citations in them, and a citation lost here is reported to the reviewer as an
    # unused reference — a finding that isn't there. A running header is a label; a
    # sentence is not a running header however often it repeats.
    note = "Note. Adapted from Doe (2020)."
    lines = ["Table 1", "", note, "", "Table 2", "", note]

    result = _drop_repeated_isolated_lines(lines)

    assert result.count(note) == 2


def test_drop_repeated_isolated_lines_keeps_captions_differing_only_in_a_number():
    # The digit-collapsed key is what makes the old rule reach so far: these two lines
    # are not identical, they merely canonicalize alike.
    lines = [
        "Figure 1. Mean response by condition, after Roe (2019).",
        "",
        "Figure 2. Mean response by condition, after Roe (2019).",
    ]

    assert _drop_repeated_isolated_lines(lines) == lines


def test_a_manuscript_of_repeated_sentences_is_not_emptied():
    # End to end, because this is how the failure actually presented: four ordinary
    # paragraphs, two of them repeating, normalized to "" — every reference in the
    # document would then be reported as uncited.
    body = "\n\n".join(
        [
            "Study 1 used the standard protocol.",
            "All procedures followed Smith (2018).",
            "Study 2 used the standard protocol.",
            "All procedures followed Smith (2018).",
        ]
    )

    normalized = normalize_markdown_text(body)

    assert normalized.count("All procedures followed Smith (2018).") == 2
    assert normalized.count("used the standard protocol.") == 2


def test_drop_repeated_isolated_lines_still_drops_an_abbreviated_running_head():
    # Why the prose rule needs a word floor and not just terminal punctuation: an
    # abbreviated journal running head is three words and ends in a period, so
    # punctuation alone would protect it and hand tier0 a spurious entry per page.
    head = "Annu. Rev. Psychol."
    lines = [head, "", "Doe, J. (2020). A title. Journal, 1(1), 1-10.", "", head]

    result = _drop_repeated_isolated_lines(lines)

    assert head not in result
    assert "Doe, J. (2020). A title. Journal, 1(1), 1-10." in result


def test_drop_repeated_isolated_lines_still_drops_a_repeated_label():
    # The residual the prose rule accepts rather than hides. A short numbered label has
    # no terminal punctuation, so it is indistinguishable by shape from the running
    # header this pass exists to remove, and both copies still go. Nothing citable lives
    # in a line this short, which is why the trade lands here rather than the other way.
    lines = ["Analysis 1", "", "Body prose.", "", "Analysis 2"]

    result = _drop_repeated_isolated_lines(lines)

    assert "Analysis 1" not in result
    assert "Analysis 2" not in result


def test_drop_repeated_isolated_lines_never_touches_bullet_entries():
    # Two bulleted bibliography entries that happen to be identical apart from a
    # digit must never be dropped — a Markdown list item is real content, never a
    # running header/footer, regardless of repetition.
    lines = ["- Doe, J. (2020). A title. p. 1", "", "- Doe, J. (2020). A title. p. 2"]

    result = _drop_repeated_isolated_lines(lines)

    assert result == lines


def test_drop_isolated_decorative_list_markers_removes_single_character_artifact():
    lines = [
        "Conner, C. (2009). A complete reference.",
        "",
        "   - x",
        "",
        "Doe, D. (2010). Another complete reference.",
    ]

    assert _drop_isolated_decorative_list_markers(lines) == [
        "Conner, C. (2009). A complete reference.",
        "",
        "",
        "Doe, D. (2010). Another complete reference.",
    ]


def test_drop_isolated_decorative_list_markers_removes_text_free_bullet():
    # Same artifact with nothing at all after the marker — equally impossible as an
    # entry, so it must not survive where "- x" is dropped.
    lines = [
        "Conner, C. (2009). A complete reference.",
        "",
        "- ",
        "",
        "Doe, D. (2010). Another complete reference.",
    ]

    assert _drop_isolated_decorative_list_markers(lines) == [
        "Conner, C. (2009). A complete reference.",
        "",
        "",
        "Doe, D. (2010). Another complete reference.",
    ]


def test_drop_isolated_decorative_list_markers_keeps_marker_inside_a_real_list():
    # A short bullet that sits in a list (no blank line on either side) is never a
    # page decoration, so isolation — not brevity alone — has to gate the drop.
    lines = [
        "- Conner, C. (2009). A complete reference.",
        "- x",
        "- Doe, D. (2010). Another complete reference.",
    ]

    assert _drop_isolated_decorative_list_markers(lines) == lines


def test_drop_isolated_decorative_list_markers_preserves_bibliography_entry():
    lines = ["- X. (2010). A complete reference."]

    assert _drop_isolated_decorative_list_markers(lines) == lines


def test_drop_repeated_isolated_lines_never_touches_numbered_entries():
    # Two short, formulaic numbered entries (e.g. successive editions of the same
    # standard) that canonicalize to an identical digit-stripped key must never be
    # dropped just because they repeat — each looks like a real entry's own start
    # (tier0's numbered-marker pattern), which a running header/footer never does.
    lines = ["[3] ISO 8601:2019. Date and time format.", "", "[7] ISO 8601:2022. Date and time format."]

    result = _drop_repeated_isolated_lines(lines)

    assert result == lines


def test_merge_mid_entry_paragraph_breaks_rejoins_spurious_column_break():
    lines = [
        "References",
        "",
        "Smith AB, Jones CD. 2000. A study of things that requires accurate estimation of",
        "",
        "some outcome. Journal of Things 24(2):173-79",
        "",
        "Doe J. 2001. A second, unrelated study. Journal of Things 25(1):1-10",
    ]

    result = _merge_mid_entry_paragraph_breaks(lines)

    assert (
        "Smith AB, Jones CD. 2000. A study of things that requires accurate estimation of "
        "some outcome. Journal of Things 24(2):173-79" in result
    )
    assert "Doe J. 2001. A second, unrelated study. Journal of Things 25(1):1-10" in result
    assert len([line for line in result if line.strip()]) == 3  # heading + 2 real entries


def test_merge_mid_entry_paragraph_breaks_rejoins_bulleted_entry_split_by_page_break():
    # pymupdf4llm renders a numbered/bulleted bibliography as one "- ..." list item per
    # entry, but a page break falling mid-entry can make it emit the continuation as
    # its own separate bullet too (observed on a real PDF: a wrapped hyphenated word
    # split across a page, the fragment after the break landing in its own bullet).
    # Neither surrounding line is a section heading, and the continuation has no
    # author-start marker and no parenthesised year of its own, so it cannot be a real
    # new entry.
    lines = [
        "References",
        "",
        "- Doe, J. (2020). A title split across a page break –",
        "",
        "- onto its continuation with no author or year. Journal of Examples, 1(1), 1-10.",
        "",
        "- Young, Y. (2021). A second, real entry. Journal of Cases, 4(1), 1-5.",
    ]

    result = _merge_mid_entry_paragraph_breaks(lines)

    assert (
        "Doe, J. (2020). A title split across a page break – onto its continuation "
        "with no author or year. Journal of Examples, 1(1), 1-10." in result
    )
    assert "Young, Y. (2021). A second, real entry. Journal of Cases, 4(1), 1-5." in result
    assert len([line for line in result if line.strip()]) == 3  # heading + 2 real entries


def test_merge_mid_entry_paragraph_breaks_rejoins_bulleted_entry_ending_in_a_title_period():
    # The harder case: the fragment before the break ends in ordinary sentence-terminal
    # punctuation (a title-ending period before the journal name, exactly how APA
    # closes a title) rather than a dangling hyphen, so entry_is_complete alone cannot
    # tell this apart from a genuinely finished entry. The continuation still carries
    # no author-start marker and no year, which is the reliable signal here.
    lines = [
        "References",
        "",
        "- Molenaar, P. (2004). A manifesto on idiographic science, this time forever.",
        "",
        "- Measurement: Interdisciplinary Research, 2(4), 201-218. https://doi.org/10.1/x",
        "",
        "- Morey, R. D. (2011). A second, real entry. Psychological Methods, 16(4), 1-19.",
    ]

    result = _merge_mid_entry_paragraph_breaks(lines)

    assert (
        "Molenaar, P. (2004). A manifesto on idiographic science, this time forever. "
        "Measurement: Interdisciplinary Research, 2(4), 201-218. https://doi.org/10.1/x" in result
    )
    assert "Morey, R. D. (2011). A second, real entry. Psychological Methods, 16(4), 1-19." in result
    assert len([line for line in result if line.strip()]) == 3  # heading + 2 real entries


def test_merge_mid_entry_paragraph_breaks_keeps_bulleted_corporate_author_entry_apart():
    # Guard: a bulleted corporate-author entry (no comma-initial author marker) must
    # not be swallowed into the bulleted period-final entry before it just because it
    # matches none of the author-start markers — it still carries its own parenthesised
    # year, which is the fallback signal that stops the two recovery cases above from
    # over-merging a real second entry.
    lines = [
        "References",
        "",
        "- Doe, J. (2020). A first article title. Journal of Examples, 1(1), 1-10.",
        "",
        "- World Health Organization. (2021). Global report on something measurable.",
    ]

    # _merge_mid_entry_paragraph_breaks always strips the Markdown bullet marker as
    # part of its own normalization pass, independent of whether it merges anything —
    # so the "kept apart" expectation is the two entries with that marker gone, not
    # byte-identical input.
    assert _merge_mid_entry_paragraph_breaks(lines) == [
        "References",
        "",
        "Doe, J. (2020). A first article title. Journal of Examples, 1(1), 1-10.",
        "",
        "World Health Organization. (2021). Global report on something measurable.",
    ]


def test_merge_mid_entry_paragraph_breaks_keeps_undated_bulleted_entry_apart():
    # Guard: an undated, title-first bulleted entry (no comma-initial author marker
    # and no year at all — e.g. a corporate author or a standards document) must not
    # be swallowed into the complete bulleted entry before it just because it lacks
    # its own author/year marker. Lacking that marker is also true of a genuine
    # continuation fragment (a journal name plus locator), so telling the two apart
    # requires the continuation fragment's own positive evidence — a locator shape or
    # a DOI/URL — which this entry has neither of.
    lines = [
        "References",
        "",
        "- Doe, J. (2020). A first article title. Journal of Examples, 1(1), 1-10.",
        "",
        "- World Health Organization. Global report on something measurable.",
    ]

    assert _merge_mid_entry_paragraph_breaks(lines) == [
        "References",
        "",
        "Doe, J. (2020). A first article title. Journal of Examples, 1(1), 1-10.",
        "",
        "World Health Organization. Global report on something measurable.",
    ]


def test_merge_mid_entry_paragraph_breaks_keeps_bare_number_entries_apart():
    # A bare-number-style bibliography (tier0's _BARE_NUMBER_RE: no bracket or dot
    # after the marker) whose first entry ends in a bare DOI, not sentence-terminal
    # punctuation — the punctuation signal alone would wrongly call this a spurious
    # mid-entry break. The next line starting with "2 " must be recognized as a real
    # new entry so the two are never fused into one.
    lines = [
        "References",
        "",
        "1 Doll R and Hill AB. Smoking and carcinoma of the lung. BMJ 1950; 2:739 doi: 10.1136/bmj.2.4682.739",
        "",
        "2 Watson JD and Crick FHC. Molecular structure of nucleic acids. Nature 1953; 171:737",
    ]

    result = _merge_mid_entry_paragraph_breaks(lines)

    assert "1 Doll R and Hill AB. Smoking and carcinoma of the lung. BMJ 1950; 2:739 doi: 10.1136/bmj.2.4682.739" in result
    assert "2 Watson JD and Crick FHC. Molecular structure of nucleic acids. Nature 1953; 171:737" in result


def _grobid_document(path):
    """One GROBID-extracted reference, in the shape extract_document_via_grobid returns."""
    return GrobidDocument(references=[RawReferenceEntry(1, "Doe, J. (2020) A Title", title="A Title")])


def test_extract_references_uses_grobid_when_available(monkeypatch, tmp_path):
    pdf_path = tmp_path / "manuscript.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(document, "is_grobid_available", lambda: True)
    monkeypatch.setattr(document, "extract_document_via_grobid", _grobid_document)

    entries = extract_references(pdf_path)

    assert len(entries) == 1
    assert entries[0].title == "A Title"


def test_extract_references_falls_back_to_tier0_when_grobid_unavailable(monkeypatch, tmp_path):
    pdf_path = tmp_path / "manuscript.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(document, "is_grobid_available", lambda: False)
    monkeypatch.setattr(document, "_read_source_text", lambda path: "References\nDoe, J. (2020). A title.\n\nRoe, R. (2019). Another title.")

    entries = extract_references(pdf_path)

    assert len(entries) == 2
    assert entries[0].title is None


def test_extract_references_falls_back_to_tier0_when_grobid_returns_no_references(monkeypatch, tmp_path):
    # A 200 response with zero parseable references (e.g. a scanned/OCR-hostile PDF, or
    # a layout GROBID's segmentation model misses) is not a GrobidUnavailableError — it
    # must still trigger the Tier 0 fallback rather than returning an empty result.
    pdf_path = tmp_path / "manuscript.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(document, "is_grobid_available", lambda: True)
    monkeypatch.setattr(document, "extract_document_via_grobid", lambda path: GrobidDocument())
    monkeypatch.setattr(document, "_read_source_text", lambda path: "References\nDoe, J. (2020). A title.\n\nRoe, R. (2019). Another title.")

    entries = extract_references(pdf_path)

    assert len(entries) == 2


def test_extract_references_falls_back_to_tier0_when_grobid_call_fails(monkeypatch, tmp_path):
    pdf_path = tmp_path / "manuscript.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(document, "is_grobid_available", lambda: True)

    def raise_unavailable(path):
        raise GrobidUnavailableError("connection refused")

    monkeypatch.setattr(document, "extract_document_via_grobid", raise_unavailable)
    monkeypatch.setattr(document, "_read_source_text", lambda path: "References\nDoe, J. (2020). A title.\n\nRoe, R. (2019). Another title.")

    entries = extract_references(pdf_path)

    assert len(entries) == 2


def test_extract_references_engine_anchor_never_touches_grobid(monkeypatch, tmp_path):
    # ENGINE_ANCHOR must skip GROBID outright, without even checking reachability —
    # e.g. to compare Tier 0 output against GROBID's, or when GROBID is known-
    # unreliable for a given document (see extract_references's docstring).
    pdf_path = tmp_path / "manuscript.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")

    def _fail_if_called(*_args, **_kwargs):
        raise AssertionError("GROBID must not be touched when ENGINE_ANCHOR is forced")

    monkeypatch.setattr(document, "is_grobid_available", _fail_if_called)
    monkeypatch.setattr(document, "extract_document_via_grobid", _fail_if_called)
    monkeypatch.setattr(document, "_read_source_text", lambda path: "References\nDoe, J. (2020). A title.\n\nRoe, R. (2019). Another title.")

    entries = extract_references(pdf_path, engine=ENGINE_ANCHOR)

    assert len(entries) == 2


def test_extract_references_engine_grobid_skips_reachability_check(monkeypatch, tmp_path):
    # ENGINE_GROBID forces an attempt regardless of reachability, rather than
    # silently falling back the way the default auto-detect would.
    pdf_path = tmp_path / "manuscript.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")

    def _fail_if_called():
        raise AssertionError("is_grobid_available should not be consulted when ENGINE_GROBID is forced")

    monkeypatch.setattr(document, "is_grobid_available", _fail_if_called)
    monkeypatch.setattr(document, "extract_document_via_grobid", _grobid_document)

    entries = extract_references(pdf_path, engine=ENGINE_GROBID)

    assert len(entries) == 1
    assert entries[0].title == "A Title"


def test_extract_references_engine_grobid_still_falls_back_on_failure(monkeypatch, tmp_path):
    # A pinned ENGINE_GROBID is still a best-effort upgrade, not a hard dependency —
    # a bad GROBID call must still fall back to Tier 0 rather than raising.
    pdf_path = tmp_path / "manuscript.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")

    def raise_unavailable(path):
        raise GrobidUnavailableError("connection refused")

    monkeypatch.setattr(document, "extract_document_via_grobid", raise_unavailable)
    monkeypatch.setattr(document, "_read_source_text", lambda path: "References\nDoe, J. (2020). A title.\n\nRoe, R. (2019). Another title.")

    entries = extract_references(pdf_path, engine=ENGINE_GROBID)

    assert len(entries) == 2


@pytest.mark.parametrize("doc", MANIFEST["documents"], ids=lambda d: d["pdf"])
def test_extract_references_from_real_pdfs(doc, monkeypatch):
    """Extraction should isolate roughly the right number of references from each
    synthetic manuscript PDF — not exact-match, since tier0 is a baseline heuristic
    splitter (see extraction/tier0.py docstring), not a guarantee of perfect splitting
    for every citation style. Forces Tier 0 (bypassing GROBID) so this stays a test of
    tier0.py plus pymupdf4llm-based extraction specifically, regardless of whether a
    GROBID instance happens to be reachable in the environment this runs in.

    Chicago author-date (full first names, no numbering) used to be a documented Tier
    0 gap under the old fitz get_text()-based extraction: no blank-line separators
    between entries, so tier0 fell back to returning the whole section unsplit.
    pymupdf4llm's Markdown list rendering inserts a blank line between entries, which
    fixes that gap — see docs/project-plan.md's pymupdf4llm TODO — so this style is
    covered by the same tolerance as the rest below now.
    """
    monkeypatch.setattr(document, "is_grobid_available", lambda: False)
    path = FIXTURES / doc["pdf"]
    golden_count = len(doc["entries"])
    entries = extract_references(path)

    assert entries, f"no entries extracted from {doc['pdf']}"
    tolerance = max(3, round(golden_count * 0.15))
    assert abs(len(entries) - golden_count) <= tolerance, (
        f"{doc['pdf']}: extracted {len(entries)}, expected ~{golden_count} (+/-{tolerance})"
    )
