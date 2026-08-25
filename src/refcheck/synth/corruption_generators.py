"""Generators that actually produce the defects catalogued in corruptions.py.

Three different techniques depending on what the defect actually corrupts, since
"corruption" means different things at different pipeline stages:

1. SPLIT-stage defects operate on real reference-list TEXT (extracted via PyMuPDF from
   an already-compiled clean PDF - see build_reference_text_corpus()) and are scored by
   running split_bibliography_block() directly. No GROBID/AnyStyle call needed: Tier 0
   is pure Python regex, so this is fast and deterministic.

2. CONTENT-stage defects (typos, transposed digits, malformed DOIs...) don't need a
   PDF at all: the interesting question isn't "can GROBID read a typo" (trivially yes -
   it faithfully reports whatever's printed), it's "does score.py/parsing_match.py's
   matching logic tolerate the corruption." So these are simulated by constructing the
   ExtractedReference a perfect-OCR tier *would* produce from the corrupted text (i.e.
   the mutated field value itself) and scoring it against the true original gold entry.

3. TEXT-stage layout defects that are genuinely about PDF rendering (two-column reflow,
   running headers) can't be simulated by mutating strings - they require an actual
   compiled PDF and a real GROBID call, so those go through latex_builder.build_pdf()
   with a modified template.

citation_reference_mismatch and retracted_paper_cited_unflagged are NOT implemented
here: both require features this project doesn't have yet (in-text citation extraction,
retraction-database lookup respectively) - see corruptions.py, they remain "planned"
and this module doesn't pretend otherwise.
"""

import random
import re
import unicodedata
from dataclasses import replace
from pathlib import Path

from refcheck.benchmark.crossref_gold import GoldReferenceEntry
from refcheck.benchmark.doi_utils import normalize_doi
from refcheck.benchmark.ensemble import merge_extracted
from refcheck.benchmark.grobid_client import ExtractedReference
from refcheck.benchmark.parsing_match import score_parsing
from refcheck.benchmark.score import score_document
from refcheck.synth.entries import SynthReferenceEntry

# --- 1. SPLIT-stage: text-level corruptions, scored via split_bibliography_block ---


def merge_all_entries(text: str) -> str:
    """merged_entries: collapse every line break into a single space, removing the
    line-start anchors _APA_AUTHOR_START_RE relies on entirely."""
    return re.sub(r"\s+", " ", text).strip()


def mixed_numbering(entries: list[str]) -> str:
    """mixed_numbering_styles: alternate bracket-numbered, dot-numbered, and
    unmarked entries within one list."""
    lines = []
    for i, entry in enumerate(entries):
        if i % 3 == 0:
            lines.append(f"[{i + 1}] {entry}")
        elif i % 3 == 1:
            lines.append(f"{i + 1}. {entry}")
        else:
            lines.append(entry)
    return "\n\n".join(lines)


def unsorted_order(entries: list[str], seed: int = 42) -> str:
    """unsorted_reference_list: shuffle entry order (still one-blank-line-separated,
    so this isolates whether a heuristic implicitly assumes alphabetical order)."""
    shuffled = entries.copy()
    random.Random(seed).shuffle(shuffled)
    return "\n\n".join(shuffled)


def mixed_citation_styles(apa_entries: list[str], numbered_entries: list[str]) -> str:
    """mixed_citation_styles: some entries in author-year prose form, others in a
    numbered list - as if copy-pasted from two different sources."""
    half = len(apa_entries) // 2
    numbered_half = [f"[{i + 1}] {e}" for i, e in enumerate(numbered_entries[: len(numbered_entries) // 2])]
    return "\n\n".join(apa_entries[:half] + numbered_half)


def smart_quotes_and_dashes(text: str) -> str:
    """smart_quotes_and_dash_variants: replace ASCII quotes/hyphens with Word/EndNote-
    style Unicode equivalents (curly quotes, en-dashes in page ranges)."""
    text = re.sub(r'"([^"]*)"', "\u201c\\1\u201d", text)
    text = re.sub(r"(\d)-(\d)", "\\1\u2013\\2", text)  # page ranges only, not hyphenated words
    return text


def truncate_reference_list(text: str, keep_fraction: float = 0.5) -> str:
    """truncated_reference_list: cut the list off partway through, simulating an
    incomplete PDF upload (e.g. last page missing)."""
    cutoff = int(len(text) * keep_fraction)
    return text[:cutoff]


# --- 2. CONTENT-stage: entry mutators, scored via score_document/score_parsing ---


def typo_in_author_name(entry: SynthReferenceEntry) -> SynthReferenceEntry:
    family = entry.authors[0].family
    if len(family) < 3:
        return entry
    # Transpose two adjacent characters - the single most common manual typo.
    # Needs at least 3 chars: mid + 1 must stay in range for the swap below.
    mid = len(family) // 2
    typo_family = family[:mid] + family[mid + 1] + family[mid] + family[mid + 2 :]
    authors = [replace(entry.authors[0], family=typo_family)] + entry.authors[1:]
    return replace(entry, authors=authors)


def transpose_year_digits(entry: SynthReferenceEntry) -> SynthReferenceEntry:
    year = entry.year
    if len(year) != 4:
        return entry
    transposed = year[0] + year[2] + year[1] + year[3]
    return replace(entry, year=transposed)


def swap_page_ranges(entry_a: SynthReferenceEntry, entry_b: SynthReferenceEntry):
    return replace(entry_a, pages=entry_b.pages), replace(entry_b, pages=entry_a.pages)


def typo_doi_digit(entry: SynthReferenceEntry) -> SynthReferenceEntry:
    if not entry.doi:
        return entry
    digits = [c for c in entry.doi if c.isdigit()]
    if not digits:
        return entry
    # Flip the last digit found in the DOI - a single-character error that still
    # looks like a syntactically valid DOI.
    last_digit_pos = max(i for i, c in enumerate(entry.doi) if c.isdigit())
    flipped_digit = str((int(entry.doi[last_digit_pos]) + 1) % 10)
    corrupted_doi = entry.doi[:last_digit_pos] + flipped_digit + entry.doi[last_digit_pos + 1 :]
    return replace(entry, doi=corrupted_doi)


def swap_author_order(entry: SynthReferenceEntry) -> SynthReferenceEntry:
    if len(entry.authors) < 2:
        return entry
    return replace(entry, authors=list(reversed(entry.authors)))


def abbreviate_journal(entry: SynthReferenceEntry) -> SynthReferenceEntry:
    if not entry.journal:
        return entry
    abbreviated = "".join(word[0] + "." for word in entry.journal.split() if word[0].isupper())
    return replace(entry, journal=abbreviated or entry.journal)


def drop_required_field(entry: SynthReferenceEntry) -> SynthReferenceEntry:
    return replace(entry, volume=None, number=None)


def corrupt_diacritics(entry: SynthReferenceEntry) -> SynthReferenceEntry:
    """Strip accents the way a bad PDF font's missing ToUnicode mapping would
    (e.g. 'Müller' -> 'Muller'), rather than a deliberate ASCII transliteration."""
    family = entry.authors[0].family
    stripped = "".join(
        c for c in unicodedata.normalize("NFKD", family) if not unicodedata.combining(c)
    )
    authors = [replace(entry.authors[0], family=stripped)] + entry.authors[1:]
    return replace(entry, authors=authors)


def doi_url_variants(doi: str) -> dict[str, str]:
    """doi_url_variants: the same DOI printed in the different textual forms a
    reference list can use - tests whether normalize_doi() treats them as identical."""
    bare = normalize_doi(doi)
    return {
        "bare": bare,
        "doi_colon_prefix": f"doi:{bare}",
        "https_resolver": f"https://doi.org/{bare}",
        "http_dx_resolver": f"http://dx.doi.org/{bare}",
    }


def duplicate_doi(entry_a: SynthReferenceEntry, entry_b: SynthReferenceEntry) -> SynthReferenceEntry:
    """Make entry_b (a genuinely different work) carry entry_a's DOI by mistake."""
    return replace(entry_b, doi=entry_a.doi)


def _gold_entry_for(entry: SynthReferenceEntry) -> GoldReferenceEntry:
    return GoldReferenceEntry(
        title=entry.title,
        year=entry.year,
        first_author_surname=entry.authors[0].family,
        doi=normalize_doi(entry.doi) if entry.doi else None,
    )


def _extracted_ref_for(entry: SynthReferenceEntry) -> ExtractedReference:
    """What a perfect-OCR tier would report having read off the (possibly corrupted)
    printed text - i.e. exactly the entry's own current field values."""
    return ExtractedReference(
        index=entry.key,
        title=entry.title,
        year=entry.year,
        doi=normalize_doi(entry.doi) if entry.doi else None,
        author_surnames=[a.family for a in entry.authors],
    )


def score_content_corruption(original: SynthReferenceEntry, corrupted: SynthReferenceEntry) -> dict:
    """Does matching still succeed when the printed reference itself is wrong?
    Scores the corrupted entry's "faithfully extracted" text against the true
    original as gold - i.e. does an editor's/verifier's exact-match lookup still find
    the real work despite the error in the manuscript."""
    gold = _gold_entry_for(original)
    extracted = _extracted_ref_for(corrupted)

    doi_match = bool(gold.doi and extracted.doi and gold.doi == extracted.doi)
    title_result = score_parsing([extracted], [gold])
    return {
        "doi_match": doi_match,
        "title_match": title_result.matched == 1,
    }


# --- 3. TEXT-stage: real PDF-level layout defects (need latex_builder + GROBID) ---

def build_two_column_pdf(entries: list[SynthReferenceEntry], build_dir: Path, style: str, doc_name: str) -> Path:
    """two_column_reflow: same content as build_pdf(), but \\twocolumn - tests
    whether naive top-to-bottom text extraction interleaves the two columns'
    reference entries out of order."""
    from refcheck.synth import latex_builder

    original_template = latex_builder._TEX_TEMPLATE
    try:
        # _TEX_TEMPLATE uses doubled braces ({{...}}) since it's a .format() template.
        latex_builder._TEX_TEMPLATE = original_template.replace(
            r"\documentclass{{article}}", r"\documentclass[twocolumn]{{article}}"
        )
        return latex_builder.build_pdf(entries, build_dir, style=style, doc_name=doc_name)
    finally:
        latex_builder._TEX_TEMPLATE = original_template


_RUNNING_HEADER_PREAMBLE_ADDITION = (
    # Braces doubled ({{...}}) since this gets spliced into a .format() template.
    r"\usepackage{{fancyhdr}}" "\n"
    r"\pagestyle{{fancy}}" "\n"
    r"\fancyhead[R]{{SYNTHETIC MANUSCRIPT BENCHMARK}}" "\n"
    r"\fancyfoot[C]{{\thepage}}"
)


def build_running_header_pdf(entries: list[SynthReferenceEntry], build_dir: Path, style: str, doc_name: str) -> Path:
    """running_header_injection: adds a real running header/footer via fancyhdr, so a
    multi-page reference list has repeated header text interleaved when pages'
    extracted text is concatenated (PyMuPDF/pdfminer don't know to strip it)."""
    from refcheck.synth import latex_builder

    original_template = latex_builder._TEX_TEMPLATE
    try:
        latex_builder._TEX_TEMPLATE = original_template.replace(
            r"\addbibresource{{{bib_name}}}",
            r"\addbibresource{{{bib_name}}}" "\n" + _RUNNING_HEADER_PREAMBLE_ADDITION,
        )
        return latex_builder.build_pdf(entries, build_dir, style=style, doc_name=doc_name)
    finally:
        latex_builder._TEX_TEMPLATE = original_template


# --- 4. MERGE-stage: dedup behavior, via merge_extracted() directly ---


def duplicate_reference_scenario(ref: ExtractedReference) -> list[ExtractedReference]:
    """duplicate_reference: the same work appears twice in one tier's own output
    (e.g. cited twice in the manuscript) - returns two tiers' worth of output, both
    containing the duplicate."""
    return [ref, replace(ref, index=ref.index + "_dup")]


def duplicate_doi_different_works_scenario(
    ref_a: ExtractedReference, ref_b: ExtractedReference
) -> list[ExtractedReference]:
    """duplicate_doi_different_works: two genuinely different works accidentally
    share the same (wrong) DOI - tests whether merge_extracted's DOI-keyed dedup
    silently collapses them into one."""
    corrupted_b = replace(ref_b, doi=ref_a.doi)
    return [ref_a, corrupted_b]


# --- 5. SPARSE/MIXED variants: corrupt only *some* entries within an otherwise-clean
# list. Everything above corrupts the whole document/entry wholesale, which is the
# easy case to measure but not the realistic one: a real reference list usually has
# one or two bad entries among many good ones. These functions isolate two questions
# wholesale corruption can't answer: (a) does a single localized text defect bleed
# into its neighbors during splitting, and (b) does one corrupted entry's fuzzy title
# match collide with a *different* gold entry instead of just failing its own match.


def sparse_split_corruption(entries_text: list[str], corrupt_index: int, defect_name: str = "merged_with_next") -> str:
    """Apply one split-stage defect to a single entry within an otherwise-clean list,
    then rejoin. Tests whether the damage stays localized (n-1 or n entries recovered)
    or corrupts neighboring entries too (collateral damage)."""
    entries = entries_text.copy()
    if defect_name == "merged_with_next":
        if corrupt_index + 1 >= len(entries):
            raise ValueError("corrupt_index has no next entry to merge with")
        merged = re.sub(r"\s+", " ", entries[corrupt_index] + " " + entries[corrupt_index + 1]).strip()
        entries = entries[:corrupt_index] + [merged] + entries[corrupt_index + 2 :]
    elif defect_name == "smart_quotes":
        entries[corrupt_index] = smart_quotes_and_dashes(entries[corrupt_index])
    else:
        raise ValueError(f"unknown defect_name: {defect_name}")
    return "\n\n".join(entries)


def sparse_content_corruption(
    entries: list[SynthReferenceEntry], corrupt_index: int, mutator
) -> tuple[list[ExtractedReference], list[GoldReferenceEntry]]:
    """Build a full extracted/gold pair where only entries[corrupt_index] carries a
    content-stage defect and every other entry is clean. Isolates whether one bad
    entry among many degrades just its own match (recall drops by exactly 1/n) or has
    collateral effect on a neighbor (e.g. a false title/DOI collision)."""
    corrupted_entry = mutator(entries[corrupt_index])
    extracted = [
        _extracted_ref_for(corrupted_entry if i == corrupt_index else e) for i, e in enumerate(entries)
    ]
    gold = [_gold_entry_for(e) for e in entries]
    return extracted, gold
