"""Tier 1 citation detection: GROBID's inline `<ref type="bibr">` body markers.

The TEI below is written for these tests rather than copied from GROBID's own test
corpus. The structure it exercises — `<ref type="bibr" target="#bXX">` inside `<body>`
paragraphs, pointing at `<biblStruct xml:id="bXX">` in `<back>`, with a grouped citation
split into one element per target — is the structure the citation plan already verified
against a primary source and recorded in its Constraints; TEI itself is a public
standard. Authoring the fixtures here keeps this repo free of a vendored third-party
file and lets each one isolate exactly one behaviour.
"""

import sys

import pytest
import requests

from openrefcheck.benchmark.grobid_client import parse_grobid_citation_contexts, parse_tei_root
from openrefcheck.extraction import grobid
from openrefcheck.extraction.grobid import (
    GrobidUnavailableError,
    extract_document_via_grobid,
    extract_references_via_grobid,
)


def _tei(body: str, back: str = "", *, abstract: str = "", annex: str = "") -> str:
    """A TEI response in the shape GROBID writes one.

    `abstract` goes under `teiHeader/profileDesc/abstract` and `annex` under
    `<back><div type="annex">` — the two places outside `<text><body>` where GROBID puts
    manuscript prose that cites, both verified against its own serializer.
    """
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader>
    <fileDesc><sourceDesc>
      <biblStruct>
        <analytic><author><persName><surname>PaperAuthor</surname></persName></author></analytic>
      </biblStruct>
    </sourceDesc></fileDesc>
    <profileDesc><abstract>{abstract}</abstract></profileDesc>
  </teiHeader>
  <text>
    <body><div>{body}</div></body>
    <back>
      <div type="annex">{annex}</div>
      <div type="references"><listBibl>{back}</listBibl></div>
    </back>
  </text>
</TEI>
"""


def _entry(xml_id: str, title: str, surname: str, year: str) -> str:
    return f"""
      <biblStruct xml:id="{xml_id}">
        <analytic>
          <title level="a" type="main">{title}</title>
          <author><persName><surname>{surname}</surname></persName></author>
        </analytic>
        <monogr><imprint><date type="published" when="{year}">{year}</date></imprint></monogr>
      </biblStruct>"""


# Ids deliberately out of order: b7 is the first entry, so anything that assumed
# "b7" means the eighth reference resolves to the wrong entry here.
_BACK = _entry("b7", "An earlier study", "Doe", "2018") + _entry(
    "b2", "A replication", "Roe", "2020"
) + _entry("b9", "A second replication", "Noe", "2021")

_BODY = """
        <head>Introduction</head>
        <p>Earlier work <ref type="bibr" target="#b7">[1]</ref> established the effect,
        but replications <ref type="bibr" target="#b2">[2]</ref><ref type="bibr" target="#b9">, [3]</ref>
        disagreed. See <ref type="figure" target="#fig_0">Figure 1</ref>.</p>
"""


def _contexts(tei: str):
    return parse_grobid_citation_contexts(parse_tei_root(tei))


def _fake_call(monkeypatch, tei: str) -> None:
    monkeypatch.setattr(grobid, "call_grobid", lambda path, grobid_url=None, headers=None: tei)


@pytest.fixture
def pdf_path(tmp_path):
    path = tmp_path / "manuscript.pdf"
    path.write_bytes(b"%PDF-1.4 fake")
    return path


# --------------------------------------------------------------------------------------
# TEI walk
# --------------------------------------------------------------------------------------


def test_body_markers_are_extracted_with_their_targets():
    contexts = _contexts(_tei(_BODY, _BACK))

    assert [c.target for c in contexts] == ["b7", "b2", "b9"]
    assert [c.marker_text for c in contexts] == ["[1]", "[2]", ", [3]"]


def test_a_grouped_marker_becomes_one_record_per_reference():
    """GROBID splits "[2, 3]" into two adjacent elements; both survive as separate records
    with distinct spans, which is the one-record-per-reference shape Tier 0 also uses."""
    second, third = _contexts(_tei(_BODY, _BACK))[1:]

    assert second.target != third.target
    assert second.end <= third.start
    assert second.paragraph_text == third.paragraph_text


def test_a_cross_reference_that_is_not_a_citation_is_ignored():
    contexts = _contexts(_tei(_BODY, _BACK))

    # The count is asserted too: without it a function returning nothing at all passes
    # this, and this is the only test guarding the type="bibr" filter.
    assert len(contexts) == 3
    assert all("Figure" not in c.marker_text for c in contexts)


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(_BODY, id="grouped_and_plain"),
        pytest.param(
            '<p>Split across\n          lines <ref type="bibr" target="#b7">[1]</ref>\n'
            "          here.</p>",
            id="wrapped_paragraph",
        ),
        pytest.param(
            '<p>Nested <hi rend="italic">inside <ref type="bibr" target="#b7">[1]</ref></hi>.</p>',
            id="nested_in_inline_element",
        ),
        pytest.param(
            '<p><ref type="bibr" target="#b7">[1]</ref> opens the paragraph.</p>',
            id="paragraph_initial",
        ),
        pytest.param(
            '<p>It closes the paragraph <ref type="bibr" target="#b7">[1]</ref>\n        </p>',
            id="paragraph_final",
        ),
        pytest.param(
            '<p>The marker itself wraps <ref type="bibr" target="#b7">\n          [1]\n'
            "          </ref> mid-line.</p>",
            id="marker_spans_a_line_break",
        ),
        pytest.param(
            '<p>Bracketed (<ref type="bibr" target="#b7">\n          [1]\n          </ref>) here.</p>',
            id="wrapped_marker_after_a_non_space",
        ),
    ],
)
def test_a_markers_offsets_index_its_own_paragraph_text(body):
    """The one invariant a caller can rely on. Without it a reviewer sent to `start` lands
    somewhere other than the marker, and the whole locator is decorative."""
    contexts = _contexts(_tei(body, _BACK))

    assert contexts
    for context in contexts:
        assert context.paragraph_text[context.start : context.end] == context.marker_text


def test_paragraph_text_collapses_the_line_breaks_tei_is_printed_with():
    body = '<p>Split across\n          lines <ref type="bibr" target="#b7">[1]</ref>\n          here.</p>'
    context = _contexts(_tei(body, _BACK))[0]

    assert context.paragraph_text == "Split across lines [1] here."


def test_a_marker_wrapped_onto_its_own_line_does_not_carry_the_surrounding_whitespace():
    """TEI's indentation lands inside the element, so an unstripped marker reads as
    " [1] " and its span covers whitespace a reviewer would be pointed at."""
    body = '<p>The marker itself wraps <ref type="bibr" target="#b7">\n          [1]\n          </ref> mid-line.</p>'
    context = _contexts(_tei(body, _BACK))[0]

    assert context.marker_text == "[1]"
    assert context.paragraph_text == "The marker itself wraps [1] mid-line."


def test_a_wrapped_marker_after_an_opening_bracket_keeps_its_offsets():
    """The case that reaches the leading-whitespace adjustment. After ordinary prose the
    preceding space is already collapsed away, so the adjustment is zero and a broken one
    goes unnoticed; after "(" the whitespace inside the element survives into the string
    and the offsets have to step over it."""
    body = '<p>Bracketed (<ref type="bibr" target="#b7">\n          [1]\n          </ref>) here.</p>'
    context = _contexts(_tei(body, _BACK))[0]

    assert context.paragraph_text == "Bracketed ( [1] ) here."
    assert context.marker_text == "[1]"
    assert (context.start, context.end) == (12, 15)


def test_a_paragraph_does_not_keep_the_whitespace_it_ends_with():
    body = '<p>It closes the paragraph <ref type="bibr" target="#b7">[1]</ref>\n        </p>'

    assert _contexts(_tei(body, _BACK))[0].paragraph_text == "It closes the paragraph [1]"


def test_a_marker_in_the_reference_list_is_not_a_citation():
    """A `<ref>` inside the bibliography is the reference list pointing at itself.
    Counting it would mark every reference as cited and empty the unused-reference
    report — the one exclusion this walk makes, and the reason it is by bibliography
    rather than by location."""
    back = _BACK + '<p>See also <ref type="bibr" target="#b2">[2]</ref>.</p>'
    body = '<p>The body cites <ref type="bibr" target="#b7">[1]</ref>.</p>'

    # The body marker is the control: a walk that found nothing would pass without it.
    assert [c.target for c in _contexts(_tei(body, back))] == ["b7"]


def test_an_empty_marker_is_skipped():
    body = (
        '<p>Nothing to show <ref type="bibr" target="#b7"/> but this one counts '
        '<ref type="bibr" target="#b2">[2]</ref>.</p>'
    )

    assert [c.target for c in _contexts(_tei(body, _BACK))] == ["b2"]


def test_a_document_with_nothing_to_walk_yields_no_citations():
    tei = '<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader/></TEI>'

    assert _contexts(tei) == []


# --------------------------------------------------------------------------------------
# Where GROBID puts prose that cites
# --------------------------------------------------------------------------------------


def test_an_appendix_citation_is_found():
    """`<back><div type="annex">` is manuscript prose, not the bibliography. GROBID's own
    committed fulltext sample has 6 of its 87 markers there, so a walk restricted to
    `<text><body>` under-counts every appendix citation and can report a reference cited
    only in an appendix as unused."""
    annex = '<div><head>A Sample Attacks</head><p>The tool is described in <ref type="bibr" target="#b9">[3]</ref>.</p></div>'

    assert [c.target for c in _contexts(_tei("<p>Body.</p>", _BACK, annex=annex))] == ["b9"]


def test_a_structured_abstract_citation_is_found():
    """GROBID serializes a structured abstract through the same code path as the body, so
    it carries real `<ref type="bibr">` markup — but it lives under
    `teiHeader/profileDesc/abstract`, outside `<text>` entirely."""
    abstract = '<div><p>Building on <ref type="bibr" target="#b7">[1]</ref>, we show...</p></div>'

    assert [c.target for c in _contexts(_tei("<p>Body.</p>", _BACK, abstract=abstract))] == ["b7"]


def test_a_footnote_citation_is_found():
    """GROBID wraps note content in a `<p>` inside a `<note>` and emits it inside
    `<body>` ("notes are still in the body")."""
    body = '<p>Body.</p><note place="foot" n="1"><p>But see <ref type="bibr" target="#b2">[2]</ref>.</p></note>'

    assert [c.target for c in _contexts(_tei(body, _BACK))] == ["b2"]


def test_a_reference_cited_only_in_the_appendix_is_not_reported_as_uncited(monkeypatch, pdf_path):
    """The failure this coverage gap produces, stated as the thing a reviewer would see:
    a real citation missed becomes a false 'unused reference', which is an accusation of
    an authoring error that was not made."""
    annex = '<div><p>Implementation details follow <ref type="bibr" target="#b9">[3]</ref>.</p></div>'
    body = '<p>Earlier work <ref type="bibr" target="#b7">[1]</ref> and <ref type="bibr" target="#b2">[2]</ref>.</p>'
    _fake_call(monkeypatch, _tei(body, _BACK, annex=annex))

    document = extract_document_via_grobid(pdf_path)

    cited = {c.reference_index for c in document.citations}
    assert {entry.index for entry in document.references} - cited == set()


def test_a_figure_caption_citation_is_found():
    """GROBID appends citation markers straight onto `<figDesc>` (`Figure.toTEI`), with no
    `<p>` between. A reference cited only in a caption would otherwise be reported unused."""
    body = '<figure><figDesc>Adapted from <ref type="bibr" target="#b2">[2]</ref>.</figDesc></figure>'

    assert [c.target for c in _contexts(_tei(body, _BACK))] == ["b2"]


def test_a_figure_caption_citation_is_found_with_sentence_segmentation_on():
    """The same caption, from a GROBID configured with sentence segmentation: the element
    holding the marker is renamed to `<p>` and wrapped in a `<div>` inside the `<figDesc>`.
    Which shape arrives is a property of the deployment, not of the manuscript."""
    body = (
        "<figure><figDesc><div><p>Adapted from "
        '<ref type="bibr" target="#b2">[2]</ref>.</p></div></figDesc></figure>'
    )

    contexts = _contexts(_tei(body, _BACK))
    assert [c.target for c in contexts] == ["b2"]
    assert contexts[0].paragraph_text == "Adapted from [2]."


def test_a_table_cell_citation_is_found():
    body = (
        "<figure type=\"table\"><table><row><cell>Method of "
        '<ref type="bibr" target="#b9">[3]</ref></cell></row></table></figure>'
    )

    assert [c.target for c in _contexts(_tei(body, _BACK))] == ["b9"]


def test_a_marker_appended_straight_to_its_div_is_found():
    """GROBID hangs a marker cluster on the enclosing `<div>` when it precedes the
    section's first paragraph (`parent = curParagraph != null ? curParagraph : curDiv`).
    No container tag anyone listed applies, and it is still a citation."""
    body = '<div><ref type="bibr" target="#b7">[1]</ref> opens the section.</div>'

    assert [c.target for c in _contexts(_tei(body, _BACK))] == ["b7"]


@pytest.mark.parametrize(
    ("body", "passage"),
    [
        pytest.param(
            '<p>We follow <hi rend="italic"><ref type="bibr" target="#b7">[1]</ref></hi> throughout.</p>',
            "We follow [1] throughout.",
            id="paragraph",
        ),
        pytest.param(
            "<figure><figDesc>Adapted from <hi>"
            '<ref type="bibr" target="#b7">[1]</ref></hi>, with changes.</figDesc></figure>',
            "Adapted from [1], with changes.",
            id="figure_caption",
        ),
    ],
)
def test_a_marker_nested_in_an_inline_element_still_gets_the_whole_passage(body, passage):
    """What the container list buys, now that the direct-child fallback covers finding the
    marker at all: a marker inside `<hi>` is *found* either way, but without the list the
    passage a reviewer is shown would be the `<hi>` — three words instead of the sentence.
    Coverage and passage quality are separate properties and need separate assertions."""
    assert _contexts(_tei(body, _BACK))[0].paragraph_text == passage


def test_a_marker_in_an_unanticipated_element_is_still_found():
    """The rule that makes the container list non-binding. A tag this module has never
    heard of yields its markers rather than swallowing them, because a marker is claimed
    by whatever holds it — which is the assumption that does not need maintaining."""
    body = '<quote><said>As put by <ref type="bibr" target="#b2">[2]</ref>.</said></quote>'

    assert [c.target for c in _contexts(_tei(body, _BACK))] == ["b2"]


def test_a_section_heading_is_not_swallowed_by_the_div_around_it():
    """A `<div>` whose markers all sit inside its `<p>`s is not itself the passage. If it
    were, a reviewer asking for the sentence would be handed the whole section."""
    body = '<div><head>Methods</head><p>We follow <ref type="bibr" target="#b7">[1]</ref>.</p></div>'
    context = _contexts(_tei(body, _BACK))[0]

    assert context.paragraph_text == "We follow [1]."


def test_a_nested_paragraph_does_not_report_the_same_marker_twice():
    body = '<p>Outer <p>inner cites <ref type="bibr" target="#b7">[1]</ref></p> end.</p>'

    assert len(_contexts(_tei(body, _BACK))) == 1


# --------------------------------------------------------------------------------------
# Resolving a marker to a bibliography entry
# --------------------------------------------------------------------------------------


def test_a_marker_resolves_through_the_tei_id_map_not_position(monkeypatch, pdf_path):
    """b7/b2/b9 are the first/second/third entries. Reading the id as a position would
    resolve every one of these markers to a reference that does not exist."""
    _fake_call(monkeypatch, _tei(_BODY, _BACK))

    document = extract_document_via_grobid(pdf_path)

    assert [c.reference_index for c in document.citations] == [1, 2, 3]
    titles = {entry.index: entry.title for entry in document.references}
    assert titles[document.citations[0].reference_index] == "An earlier study"


def test_a_target_no_entry_carries_stays_unresolved(monkeypatch, pdf_path):
    body = '<p>Pointing at nothing <ref type="bibr" target="#b99">[9]</ref>.</p>'
    _fake_call(monkeypatch, _tei(body, _BACK))

    citation = extract_document_via_grobid(pdf_path).citations[0]

    assert citation.reference_index is None
    assert citation.target == "b99"  # kept, so the marker is still reportable as orphaned


def test_a_marker_with_no_target_stays_unresolved(monkeypatch, pdf_path):
    body = '<p>Unresolved by GROBID <ref type="bibr">(Unknown, 1999)</ref>.</p>'
    _fake_call(monkeypatch, _tei(body, _BACK))

    citation = extract_document_via_grobid(pdf_path).citations[0]

    assert citation.reference_index is None
    assert citation.target is None


def test_a_duplicate_xml_id_resolves_to_the_entry_declared_first(monkeypatch, pdf_path):
    back = _entry("b1", "First declaration", "Doe", "2018") + _entry(
        "b1", "Malformed duplicate", "Roe", "2020"
    )
    body = '<p>Cited once <ref type="bibr" target="#b1">[1]</ref>.</p>'
    _fake_call(monkeypatch, _tei(body, back))

    document = extract_document_via_grobid(pdf_path)

    assert document.citations[0].reference_index == 1
    assert document.references[0].title == "First declaration"


def test_the_header_biblstruct_does_not_shift_reference_indices(monkeypatch, pdf_path):
    """The unmarked header `<biblStruct>` is dropped from the reference list, so the
    entry positions the map is built from must be the positions callers see."""
    _fake_call(monkeypatch, _tei(_BODY, _BACK))

    document = extract_document_via_grobid(pdf_path)

    assert [entry.index for entry in document.references] == [1, 2, 3]
    assert all("PaperAuthor" not in entry.raw_text for entry in document.references)


# --------------------------------------------------------------------------------------
# Fallback behaviour
# --------------------------------------------------------------------------------------


def test_a_processed_document_with_no_citations_is_not_an_error(monkeypatch, pdf_path):
    _fake_call(monkeypatch, _tei("<p>A manuscript that cites nothing.</p>", _BACK))

    document = extract_document_via_grobid(pdf_path)

    assert document.citations == []
    assert len(document.references) == 3


def test_a_connection_failure_raises_for_the_caller_to_fall_back(monkeypatch, pdf_path):
    def raise_connection_error(path, grobid_url=None, headers=None):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(grobid, "call_grobid", raise_connection_error)

    with pytest.raises(GrobidUnavailableError):
        extract_document_via_grobid(pdf_path)


def test_malformed_tei_raises_rather_than_returning_half_a_document(monkeypatch, pdf_path):
    _fake_call(monkeypatch, "<TEI><body><p>unclosed")

    with pytest.raises(GrobidUnavailableError):
        extract_document_via_grobid(pdf_path)


def test_a_reference_keeps_the_tei_id_it_was_resolved_by(monkeypatch, pdf_path):
    """The map is re-derivable from the references alone. Without the id on the entry it
    is a local variable inside one call, so a caller holding only a reference list cannot
    resolve a `<ref target="#bXX">` it was handed separately."""
    _fake_call(monkeypatch, _tei(_BODY, _BACK))

    document = extract_document_via_grobid(pdf_path)

    assert [entry.source_id for entry in document.references] == ["b7", "b2", "b9"]
    rebuilt = {entry.source_id: entry.index for entry in document.references}
    assert [rebuilt.get(c.target) for c in document.citations] == [
        c.reference_index for c in document.citations
    ]


def test_a_pathologically_nested_response_falls_back_rather_than_crashing(monkeypatch, pdf_path):
    """The paragraph walk recurses. document.py catches only GrobidUnavailableError, so a
    RecursionError escaping here would turn a best-effort upgrade into a failed check."""
    depth = sys.getrecursionlimit() * 2
    body = "<p>" + "<hi>" * depth + '<ref type="bibr" target="#b7">[1]</ref>' + "</hi>" * depth + "</p>"
    _fake_call(monkeypatch, _tei(body, _BACK))

    with pytest.raises(GrobidUnavailableError):
        extract_document_via_grobid(pdf_path)


def test_a_raw_passage_does_not_reach_a_repr(monkeypatch, pdf_path):
    """A failing assertion or a traceback holding one of these must not print manuscript
    prose (see the citation plan's privacy requirements)."""
    _fake_call(monkeypatch, _tei(_BODY, _BACK))

    citation = extract_document_via_grobid(pdf_path).citations[0]

    assert "Earlier work" in citation.paragraph_text
    assert "Earlier work" not in repr(citation)


def test_extract_references_via_grobid_returns_exactly_the_bundles_references(monkeypatch, pdf_path):
    """The bibliography-only contract document.py depends on is unchanged by Tier 1."""
    _fake_call(monkeypatch, _tei(_BODY, _BACK))

    assert extract_references_via_grobid(pdf_path) == extract_document_via_grobid(pdf_path).references
