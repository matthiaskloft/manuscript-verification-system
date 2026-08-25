"""Call a running GROBID service and parse its TEI-XML reference list.

Tier 1 in the extraction benchmark (see docs/project-plan.md, "Referenzextraktion").
Requires GROBID running separately, e.g.:
    docker run --rm -p 8070:8070 grobid/grobid:0.8.1
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

import requests

from refcheck.benchmark.doi_utils import normalize_doi

_TEI_NS = {"tei": "http://www.tei-c.org/ns/1.0"}
_TEI_URI = "http://www.tei-c.org/ns/1.0"
_P_TAG = f"{{{_TEI_URI}}}p"
_REF_TAG = f"{{{_TEI_URI}}}ref"
# The reference list itself, in the two shapes GROBID writes it. A <ref> inside one of
# these is the bibliography pointing at itself, not the manuscript citing a reference.
_BIBLIOGRAPHY_TAGS = frozenset({f"{{{_TEI_URI}}}listBibl", f"{{{_TEI_URI}}}biblStruct"})

# Elements that bound a passage a reviewer would be shown. Not a list of everywhere a
# marker can appear — _citation_contexts does not depend on this being complete — only
# of the containers worth preferring over a deeper one when both would work. <figDesc>
# is here because GROBID renames it to <p> and wraps it in a <div> when sentence
# segmentation is on, and leaves it a bare <figDesc> when it is off; naming both keeps
# one caption one passage either way.
_CONTEXT_TAGS = frozenset(
    {_P_TAG, f"{{{_TEI_URI}}}figDesc", f"{{{_TEI_URI}}}head", f"{{{_TEI_URI}}}cell"}
)


@dataclass
class ExtractedReference:
    index: str
    title: str | None = None
    year: str | None = None
    doi: str | None = None
    author_surnames: list[str] = field(default_factory=list)
    raw_reference: str | None = None
    """The entry as the document printed it, when GROBID was asked for it.

    None when the response predates includeRawCitations or the entry carries no such
    note. Everything else on this dataclass is GROBID's reading of this string.
    """


@dataclass
class ExtractedCitationRef:
    """One in-text citation marker GROBID located in the document body.

    `target` is the `xml:id` of the `<biblStruct>` the marker points at, with the
    leading "#" of the TEI reference removed — the same string `ExtractedReference.index`
    carries, which is what lets a caller join the two. It is None when GROBID marked a
    span as a citation but resolved it to no entry; that stays None rather than being
    guessed at, because a wrong id is indistinguishable from a real match downstream.

    A grouped marker arrives as several records: GROBID emits one `<ref>` element per
    target, so "[3,4]" is two elements with adjacent spans rather than one carrying a
    list. That is the same one-record-per-reference shape `DetectedCitation` uses on the
    Tier 0 side, so both tiers hand the matching engine the same thing.

    `start`/`end` index into `paragraph_text`, not into the manuscript: TEI is GROBID's
    own rendering of the document and its offsets do not correspond to anything in a
    `DocumentArtifact`. The invariant that does hold is
    `paragraph_text[start:end] == marker_text`.

    `paragraph_text` is raw manuscript prose and is kept out of the generated repr, so
    that a traceback or a failing assertion holding one of these cannot print it.
    """

    target: str | None
    marker_text: str
    paragraph_text: str = field(repr=False)
    start: int
    end: int


def call_grobid(
    pdf_path: Path, grobid_url: str = "http://localhost:8070", headers: dict[str, str] | None = None
) -> str:
    """Send a PDF to a running GROBID instance and return the raw TEI-XML response.

    headers is for a private/authenticated GROBID deployment (see
    refcheck.extraction.grobid._identity_token_header) — unused by benchmark callers,
    which only ever talk to a local, unauthenticated container.
    """
    with open(pdf_path, "rb") as f:
        response = requests.post(
            f"{grobid_url}/api/processFulltextDocument",
            files={"input": (pdf_path.name, f, "application/pdf")},
            # includeRawCitations asks GROBID to keep each entry's original string in a
            # <note type="raw_reference"> beside its structured parse. The structured
            # fields are a lossy reading of that string — a reprint's date slot can be
            # dropped in favour of the original work's year, an author list can come back
            # empty — and a caller that only ever sees the parse cannot tell that happened.
            # See extraction/citation_matching.py's _entry_text for who needs the original.
            data={"consolidateCitations": "0", "includeRawCitations": "1"},
            timeout=180,
            headers=headers,
        )
    response.raise_for_status()
    return response.text


def parse_tei_root(tei_xml: str) -> ET.Element:
    """Parse a TEI-XML response once, for callers that want more than one thing from it.

    Both the bibliography walk and the citation-context walk below take a root rather
    than a string, so a caller needing both (refcheck.extraction.grobid) pays for one
    parse instead of two. parse_grobid_tei keeps its string signature for the callers
    that only ever want references.
    """
    return ET.fromstring(tei_xml)


def parse_grobid_tei(tei_xml: str) -> list[ExtractedReference]:
    """Extract the bibliography (not the paper's own header) from GROBID's TEI-XML."""
    return parse_grobid_references(parse_tei_root(tei_xml))


def parse_grobid_references(root: ET.Element) -> list[ExtractedReference]:
    """Extract the bibliography (not the paper's own header) from a parsed TEI root.

    Only <biblStruct> elements with an xml:id are genuine reference-list entries —
    GROBID also emits an unmarked <biblStruct> for the source document's own header
    metadata, which we deliberately exclude here.
    """
    references = []
    for bibl in root.iter("{http://www.tei-c.org/ns/1.0}biblStruct"):
        xml_id = bibl.get("{http://www.w3.org/XML/1998/namespace}id")
        if xml_id is None:
            continue

        title_el = bibl.find(".//tei:title[@level='a']", _TEI_NS)
        if title_el is None:
            title_el = bibl.find(".//tei:title", _TEI_NS)
        title = title_el.text if title_el is not None else None

        date_el = bibl.find(".//tei:date[@type='published']", _TEI_NS)
        year = date_el.get("when") if date_el is not None else None

        doi_el = bibl.find(".//tei:idno[@type='DOI']", _TEI_NS)
        doi = normalize_doi(doi_el.text) if doi_el is not None and doi_el.text else None

        surnames = [
            surname_el.text
            for surname_el in bibl.findall(".//tei:author/tei:persName/tei:surname", _TEI_NS)
            if surname_el.text
        ]

        note_el = bibl.find("./tei:note[@type='raw_reference']", _TEI_NS)
        raw_reference = " ".join(note_el.text.split()) if note_el is not None and note_el.text else None

        references.append(
            ExtractedReference(
                index=xml_id,
                title=title,
                year=year,
                doi=doi,
                author_surnames=surnames,
                raw_reference=raw_reference,
            )
        )
    return references


_WHITESPACE_RE = re.compile(r"\s+")


def parse_grobid_citation_contexts(root: ET.Element) -> list[ExtractedCitationRef]:
    """Extract the body's inline `<ref type="bibr">` citation markers from a TEI root.

    The one place a marker must *not* be counted is the reference list itself, where a
    `<ref>` is the bibliography pointing at itself rather than the manuscript citing a
    reference — counting those would make every reference look cited and empty the
    unused-reference check this exists to feed. That is the exclusion `_citation_contexts`
    applies, and it is the whole of it. Everywhere else GROBID puts a marker is a citation
    for this purpose, which is deliberately a weaker claim than knowing where those places
    are: three of them were missed by earlier versions of this function, each found only
    after someone went looking.

    `<back><div type="annex">` was one — appendix prose, which cites like any other
    section, and 6 of the 87 markers in GROBID's own committed fulltext sample. A
    structured abstract was another: serialized through the same code path as the body
    (`TEIFormatter.toTEITextPiece`), so it carries real `<ref type="bibr">` markup, but it
    lives under `teiHeader/profileDesc/abstract`. A figure caption was the third, and the
    one that shows why the rule has to be structural: GROBID appends markers straight onto
    `<figDesc>` (`Figure.toTEI`) with sentence segmentation off, and onto a `<p>` inside it
    with segmentation on, so which element holds the marker depends on the deployment's
    config rather than on the document. A reference cited only in an appendix, an abstract
    or a caption would be reported to a reviewer as uncited — a false accusation in exactly
    the check this feeds.

    A `<ref>` with no text is skipped: a zero-width marker cannot be shown to a reviewer
    or located in the manuscript, so there is nothing a caller could do with it.
    """
    contexts: list[ExtractedCitationRef] = []
    for paragraph in _citation_contexts(root):
        text, refs = _flatten_paragraph(paragraph)
        for element, start, end in refs:
            marker = text[start:end]
            leading = len(marker) - len(marker.lstrip())
            marker = marker.strip()
            if not marker:
                continue
            target = element.get("target")
            contexts.append(
                ExtractedCitationRef(
                    target=target.lstrip("#") or None if target else None,
                    marker_text=marker,
                    paragraph_text=text,
                    start=start + leading,
                    end=start + leading + len(marker),
                )
            )
    return contexts


def _citation_contexts(root: ET.Element) -> list[ET.Element]:
    """Every element that bounds a passage a citation marker sits in, outermost first.

    An element is taken as a context when it is one of `_CONTEXT_TAGS` *or* when it holds
    a marker as a direct child. The second clause is what makes the first one non-binding:
    a tag nobody listed still yields its markers, bounded by itself, so a marker cannot be
    dropped merely because this module did not anticipate where GROBID would put it. That
    matters concretely — GROBID appends citation markers straight onto `<figDesc>`
    (`Figure.toTEI`), and onto the enclosing `<div>` when a marker cluster precedes the
    section's first paragraph (`TEIFormatter`) — and it is a weaker assumption than any
    list of container tags can be.

    Descent stops at a `<listBibl>` or `<biblStruct>` — the reference list citing itself,
    the one exclusion — and at each context found, so no marker is reported twice under
    two different passages. Filtering by where the bibliography *is* rather than by where
    prose is expected to be is what makes an unlisted element harmless in the other
    direction too: a `<p>` in the publication statement contains no markers, so it
    produces no records.
    """
    found: list[ET.Element] = []

    def descend(element: ET.Element) -> None:
        for child in element:
            if child.tag in _BIBLIOGRAPHY_TAGS:
                continue
            if child.tag in _CONTEXT_TAGS or _holds_a_marker(child):
                found.append(child)
            else:
                descend(child)

    descend(root)
    return found


def _holds_a_marker(element: ET.Element) -> bool:
    """Whether element has a citation marker as a direct child.

    Direct children only: a `<div>` whose markers all sit inside its `<p>`s is not itself
    the passage — the paragraph is — and treating it as one would hand a reviewer a whole
    section where a sentence was meant.
    """
    return any(child.tag == _REF_TAG and child.get("type") == "bibr" for child in element)


def _flatten_paragraph(paragraph: ET.Element) -> tuple[str, list[tuple[ET.Element, int, int]]]:
    """A paragraph's text as one line, plus the span each bibr `<ref>` occupies in it.

    Whitespace is collapsed while the string is being built rather than afterwards,
    because collapsing afterwards would move every offset recorded before it. TEI is
    pretty-printed, so a paragraph arrives with newlines and indentation inside it that
    would otherwise show up in the middle of a reviewer-facing snippet.

    The walk is recursive because a `<ref>` need not be a direct child — GROBID nests
    markers inside other inline elements — and a tail is appended after its element's
    span is closed so that the text following a marker is never counted as part of it.
    """
    parts: list[str] = []
    length = 0
    refs: list[tuple[ET.Element, int, int]] = []

    def append(text: str | None) -> None:
        nonlocal length
        if not text:
            return
        collapsed = _WHITESPACE_RE.sub(" ", text)
        if collapsed.startswith(" ") and (length == 0 or parts[-1].endswith(" ")):
            collapsed = collapsed[1:]
        if not collapsed:
            return
        parts.append(collapsed)
        length += len(collapsed)

    def walk(element: ET.Element) -> None:
        append(element.text)
        for child in element:
            start = length
            walk(child)
            if child.tag == _REF_TAG and child.get("type") == "bibr":
                refs.append((child, start, length))
            append(child.tail)

    walk(paragraph)
    # A recorded span may run one character past the trimmed length, when the last thing
    # in the paragraph is a marker whose own text ends in a space ("<ref>[1] </ref>").
    # The caller closes that by stripping marker_text and re-deriving end from it — the
    # spans returned here are the untrimmed ones, and only that strip makes them tight.
    return "".join(parts).rstrip(), refs
