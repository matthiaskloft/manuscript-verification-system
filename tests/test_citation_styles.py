"""Cross-style regression corpus for the reference parser.

Every parser improvement so far has been motivated by one document and has broken a
*different* citation style: recovering a flattened APA list shredded German edition
numbers, stopping at an appendix heading truncated a wrapped title, requiring
sentence-terminal punctuation glued DOI-final entries together. Each of those was
found by hand after the change had already been reviewed.

This module runs every style that has ever been fixed against every change, so the
next one is caught here instead. The cases live in fixtures/citation_styles/, one file
per style; see meta.json before changing an expectation, since a case that must change
is a behaviour decision, not a test fix.
"""

import json
import re
import unicodedata
from pathlib import Path

import pytest

from citation_style_corpus import LAYERS, load_cases, load_meta, load_styles
from refcheck.extraction import document
from refcheck.extraction.document import extract_references, find_bibliography_section, normalize_markdown_text
from refcheck.extraction.tier0 import split_bibliography_block
from refcheck.extraction.title import extract_title

FIXTURES = Path(__file__).parent / "fixtures"
META = load_meta()
STYLES = load_styles()
CASES = load_cases()

SYNTHETIC = FIXTURES / "synthetic"
MANIFEST = json.loads((SYNTHETIC / "manifest.json").read_text(encoding="utf-8"))
DOCUMENT_EXPECTATIONS = META["synthetic_documents"]


def _cases_for(layer: str) -> list:
    return [
        pytest.param(case, id=f"{case['style']}/{case['id']}")
        for case in CASES
        if case["layer"] == layer
    ]


@pytest.mark.parametrize("case", _cases_for("normalize"))
def test_markdown_cleanup_by_citation_style(case):
    """Markdown cleanup must not lose or fuse a reference before splitting sees it.

    `count` here is the number of entries the *normalized* text splits into, which is
    what makes a cleanup defect visible: a merge at this layer deletes an entry, and
    every later layer then behaves correctly on text that is already wrong.
    """
    normalized = normalize_markdown_text(case["text"])
    expect = case["expect"]

    for fragment in expect.get("normalized_contains", []):
        assert fragment in normalized, case.get("note", "")
    for fragment in expect.get("normalized_excludes", []):
        assert fragment not in normalized, case.get("note", "")
    if "count" in expect:
        entries = split_bibliography_block(find_bibliography_section(normalized))
        assert len(entries) == expect["count"], f"{case['variant']}: {case.get('note', '')}"
        for index, prefix in expect.get("entry_starts", {}).items():
            assert entries[int(index)].raw_text.startswith(prefix)


@pytest.mark.parametrize("case", _cases_for("split"))
def test_entry_splitting_by_citation_style(case):
    entries = split_bibliography_block(case["text"])
    expect = case["expect"]

    assert len(entries) == expect["count"], f"{case['variant']}: {case.get('note', '')}"
    for index, prefix in expect.get("entry_starts", {}).items():
        assert entries[int(index)].raw_text.startswith(prefix)
    for index, fragment in expect.get("entry_contains", {}).items():
        assert fragment in entries[int(index)].raw_text


@pytest.mark.parametrize("case", _cases_for("section"))
def test_bibliography_section_boundaries_by_citation_style(case):
    section = find_bibliography_section(case["text"])
    expect = case["expect"]

    if "section_equals" in expect:
        assert section == expect["section_equals"], case.get("note", "")
    for fragment in expect.get("section_contains", []):
        assert fragment in section
    for fragment in expect.get("section_excludes", []):
        assert fragment not in section


@pytest.mark.parametrize("case", _cases_for("title"))
def test_title_extraction_by_citation_style(case):
    assert extract_title(case["raw"]) == case["expect"]["title"], case.get("note", "")


def _comparable(text: str) -> str:
    """Casefolded, punctuation-free text with combining marks removed.

    pymupdf renders some diacritics as a displaced combining character ("Atiologie¨"
    for "Ätiologie"), which is a glyph-order artifact of extraction, not a splitting
    defect. Stripping combining marks keeps this measurement about entry boundaries.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    return re.sub(r"[^a-z0-9]+", " ", "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()).strip()


@pytest.fixture(scope="module")
def extracted_documents():
    """Tier 0 extraction of every synthetic manuscript, once per module run."""
    original = document.is_grobid_available
    document.is_grobid_available = lambda: False
    try:
        return {doc["pdf"]: extract_references(SYNTHETIC / doc["pdf"]) for doc in MANIFEST["documents"]}
    finally:
        document.is_grobid_available = original


@pytest.mark.parametrize("doc", MANIFEST["documents"], ids=lambda d: d["style"] + "-" + d["broad_field"])
def test_every_reference_in_a_synthetic_manuscript_is_recovered_whole(doc, extracted_documents):
    """Each manifest reference must appear inside a single extracted entry.

    The manifest's golden entries are the corpus's base layer: four citation styles
    laid out as real PDFs, with titles known independently of the parser. A title that
    no longer fits inside one entry means its reference was split or merged, which an
    entry-count tolerance cannot see — a split and a merge cancel out in the total.
    """
    entries = [_comparable(entry.raw_text) for entry in extracted_documents[doc["pdf"]]]
    expected = DOCUMENT_EXPECTATIONS[doc["pdf"]]

    missing = [
        golden["title"]
        for golden in doc["entries"]
        if not any(_comparable(golden["title"])[:45] in entry for entry in entries)
    ]

    assert not missing, f"{doc['style']}: references no longer contained in a single entry: {missing}"
    assert len(entries) == expected["entry_count"], (
        f"{doc['style']}: {len(entries)} entries, expected {expected['entry_count']} — "
        f"{expected.get('note', 'update the corpus only if the new boundaries are correct')}"
    )


def test_every_case_is_exercised_by_one_of_the_layer_tests():
    # A typo in "layer" would silently drop a case from the corpus, which is the one
    # failure this file cannot afford: it would look like coverage while providing none.
    unknown = {case["id"]: case["layer"] for case in CASES if case["layer"] not in LAYERS}

    assert not unknown, f"cases with an unrecognised layer: {unknown}"


def test_case_ids_are_unique_across_style_files():
    seen: dict[str, str] = {}
    duplicates = {}
    for case in CASES:
        if case["id"] in seen:
            duplicates[case["id"]] = (seen[case["id"]], case["style"])
        seen[case["id"]] = case["style"]

    assert not duplicates, f"case ids reused across style files: {duplicates}"


def test_every_style_file_names_styles_that_exist():
    """confusable_with is the re-run list when a style's gates change.

    Once splitting is style-aware, this is what turns "I only touched the Vancouver
    path" into a checkable claim. A typo here would quietly shorten that list.
    """
    unknown = {
        style_key: [other for other in style["confusable_with"] if other not in STYLES]
        for style_key, style in STYLES.items()
    }

    assert not any(unknown.values()), f"confusable_with names unknown styles: {unknown}"


@pytest.mark.parametrize("case", [pytest.param(c, id=f"{c['style']}/{c['id']}") for c in CASES])
def test_every_case_states_the_failure_it_reproduces(case):
    """A case that never failed on any parser is not a regression test.

    The corpus is only worth running if each case distinguishes a fixed parser from a
    broken one. A 'recovery' case has to carry the wrong output measured at a real
    commit — scripts/check_corpus_reproduces.py replays it there — and a 'guard' case
    has to name the fix it would catch. Neither can be satisfied by writing a case
    that happens to pass.
    """
    reproduces = case.get("reproduces")
    assert reproduces, f"{case['id']} does not say which failure it reproduces (see meta.json)"

    if reproduces["kind"] == "recovery":
        assert reproduces.get("broken_at"), f"{case['id']} must name the commit it failed at"
        observed = reproduces.get("observed_then")
        assert observed, f"{case['id']} must record the wrong output measured at that commit"
        assert observed != case["expect"], (
            f"{case['id']} records the same output before and after its fix, so it "
            "reproduces nothing — it is a guard case, not a recovery case"
        )
    elif reproduces["kind"] == "guard":
        assert reproduces.get("passed_at"), f"{case['id']} must name the commit it already passed at"
        assert reproduces.get("protects_against"), (
            f"{case['id']} is a guard case that does not name the fix it guards against"
        )
    else:
        pytest.fail(f"{case['id']}: unknown reproduces.kind {reproduces['kind']!r}")
