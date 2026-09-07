"""Run every implemented corruption generator and report results.

Three kinds of evidence, matching corruption_generators.py's three techniques:
1. SPLIT-stage: split_bibliography_block() counts, before/after corruption.
2. CONTENT-stage: does DOI/title matching still find the real work despite the error.
3. TEXT-stage (layout): real compiled PDFs run through GROBID, recall vs. clean baseline.

Usage:
    python scripts/run_corruption_benchmark.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import fitz

from openrefcheck.benchmark.crossref_gold import GoldReferenceEntry, GoldReferences
from openrefcheck.benchmark.doi_utils import normalize_doi
from openrefcheck.benchmark.grobid_client import call_grobid, parse_grobid_tei
from openrefcheck.benchmark.parsing_match import score_parsing
from openrefcheck.benchmark.score import score_document
from openrefcheck.extraction.tier0 import split_bibliography_block
from openrefcheck.synth import corruption_generators as cg
from openrefcheck.synth.entries import CURATED_ENTRIES

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "synthetic"
CORRUPTION_BUILD_DIR = FIXTURES_DIR / "corruption_variants"

_SOCIAL_BEHAVIORAL = [e for e in CURATED_ENTRIES if e.broad_field == "social_behavioral"]


def _extract_reference_section_text(pdf_path: Path) -> str:
    doc = fitz.open(pdf_path)
    text = "".join(page.get_text() for page in doc)
    doc.close()
    idx = text.find("References")
    return text[idx + len("References") :].strip()


def run_split_stage_report() -> None:
    print("\n=== SPLIT-stage (split_bibliography_block) ===")
    clean_pdf = FIXTURES_DIR / "synthetic_social_behavioral_apa7_clean.pdf"
    clean_text = _extract_reference_section_text(clean_pdf)
    baseline = split_bibliography_block(clean_text)
    print(f"baseline (clean text, real compiled PDF): {len(baseline)} entries recovered (30 gold)")

    merged = split_bibliography_block(cg.merge_all_entries(clean_text))
    print(f"merged_entries:              {len(merged)} entries recovered (defect: collapses to 1)")

    entries_text = [e.raw_text for e in baseline]
    mixed_num = split_bibliography_block(cg.mixed_numbering(entries_text))
    print(f"mixed_numbering_styles:      {len(mixed_num)} entries recovered (defect: silently absorbs non-bracket entries)")

    unsorted = split_bibliography_block(cg.unsorted_order(entries_text))
    print(f"unsorted_reference_list:     {len(unsorted)} entries recovered (order doesn't matter to this heuristic)")

    apa_texts = entries_text
    numbered_texts = [f"placeholder numbered entry {i}" for i in range(len(entries_text))]
    mixed_styles = split_bibliography_block(cg.mixed_citation_styles(apa_texts, numbered_texts))
    print(f"mixed_citation_styles:       {len(mixed_styles)} entries recovered (half APA prose + half bracket-numbered)")


def run_content_stage_report() -> None:
    print("\n=== CONTENT-stage (does matching survive the error) ===")
    sample = _SOCIAL_BEHAVIORAL[0]
    other = _SOCIAL_BEHAVIORAL[1]

    corruptors = {
        "typo_in_author_name": lambda: cg.typo_in_author_name(sample),
        "transposed_year_or_volume_digits": lambda: cg.transpose_year_digits(sample),
        "malformed_doi_single_character_typo": lambda: cg.typo_doi_digit(sample),
        "author_order_swapped": lambda: cg.swap_author_order(sample),
        "inconsistent_journal_abbreviation": lambda: cg.abbreviate_journal(sample),
        "missing_required_field": lambda: cg.drop_required_field(sample),
        "diacritic_corruption": lambda: cg.corrupt_diacritics(sample),
    }
    for name, make_corrupted in corruptors.items():
        corrupted = make_corrupted()
        result = cg.score_content_corruption(sample, corrupted)
        print(f"{name:<38} doi_match={result['doi_match']!s:<5} title_match={result['title_match']!s:<5}")

    corrupted_a, corrupted_b = cg.swap_page_ranges(sample, other)
    print(f"{'incorrect_page_range':<38} pages swapped: {sample.pages!r} <-> {other.pages!r} "
          f"(score.py/parsing_match.py don't check pages at all - undetectable by current metrics)")

    duped = cg.duplicate_doi(sample, other)
    print(f"{'duplicate_doi_different_works':<38} {other.key} now carries {sample.key}'s DOI "
          f"({duped.doi}) - see MERGE-stage report for the dedup consequence")


def run_merge_stage_report() -> None:
    print("\n=== MERGE-stage (ensemble.py dedup behavior) ===")
    from dataclasses import replace as dc_replace

    from openrefcheck.benchmark.ensemble import merge_extracted
    from openrefcheck.benchmark.grobid_client import ExtractedReference

    ref = ExtractedReference(index="a", doi="10.1/x", title="Some paper", author_surnames=["Smith"])
    dup_scenario = cg.duplicate_reference_scenario(ref)
    merged = merge_extracted(dup_scenario)
    print(f"duplicate_reference:            {len(dup_scenario)} raw -> {len(merged)} after merge (correctly deduped)")

    ref_a = ExtractedReference(index="a", doi="10.1/x", title="Paper A", author_surnames=["Smith"])
    ref_b = ExtractedReference(index="b", doi="10.1/y", title="Paper B, unrelated", author_surnames=["Jones"])
    corrupted_scenario = cg.duplicate_doi_different_works_scenario(ref_a, ref_b)
    merged2 = merge_extracted(corrupted_scenario)
    print(f"duplicate_doi_different_works:   2 genuinely different works -> {len(merged2)} after merge "
          f"({'Paper B silently dropped - false merge' if len(merged2) == 1 else 'both kept'})")


def run_text_stage_report() -> None:
    print("\n=== TEXT-stage (real PDF layout defects, via GROBID) ===")

    manifest_path = FIXTURES_DIR / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    social_doc = next(d for d in manifest["documents"] if d["broad_field"] == "social_behavioral")
    gold_entries = [
        GoldReferenceEntry(
            title=e["title"], year=e["year"], first_author_surname=e["authors"][0]["family"],
            doi=normalize_doi(e["doi"]) if e["doi"] else None,
        )
        for e in social_doc["entries"]
    ]

    clean_pdf = FIXTURES_DIR / social_doc["pdf"]
    clean_extracted = parse_grobid_tei(call_grobid(clean_pdf))
    clean_result = score_parsing(clean_extracted, gold_entries)
    print(f"clean baseline (social_behavioral, APA7): extracted={len(clean_extracted)} "
          f"parsing_recall={clean_result.parsing_recall:.2f}")

    print("compiling two-column variant ...")
    two_col_pdf = cg.build_two_column_pdf(
        _SOCIAL_BEHAVIORAL, CORRUPTION_BUILD_DIR, style="apa7", doc_name="corrupt_two_column"
    )
    two_col_extracted = parse_grobid_tei(call_grobid(two_col_pdf))
    two_col_result = score_parsing(two_col_extracted, gold_entries)
    print(f"two_column_reflow:                        extracted={len(two_col_extracted)} "
          f"parsing_recall={two_col_result.parsing_recall:.2f}")

    print("compiling running-header variant ...")
    header_pdf = cg.build_running_header_pdf(
        _SOCIAL_BEHAVIORAL, CORRUPTION_BUILD_DIR, style="apa7", doc_name="corrupt_running_header"
    )
    header_extracted = parse_grobid_tei(call_grobid(header_pdf))
    header_result = score_parsing(header_extracted, gold_entries)
    print(f"running_header_injection:                 extracted={len(header_extracted)} "
          f"parsing_recall={header_result.parsing_recall:.2f}")


def run_doi_url_variants_report() -> None:
    print("\n=== CONTENT-stage (doi_url_variants) ===")
    from openrefcheck.benchmark.doi_utils import normalize_doi

    variants = cg.doi_url_variants("10.1234/Example.5678")
    canonical = variants["bare"]
    for name, form in variants.items():
        matches = normalize_doi(form) == canonical
        print(f"{name:<20} {form:<40} normalize_doi() matches bare form: {matches}")


def run_truncation_report() -> None:
    print("\n=== TEXT-stage (truncated_reference_list) ===")
    clean_pdf = FIXTURES_DIR / "synthetic_social_behavioral_apa7_clean.pdf"
    clean_text = _extract_reference_section_text(clean_pdf)
    baseline = split_bibliography_block(clean_text)
    truncated_text = cg.truncate_reference_list(clean_text, keep_fraction=0.5)
    truncated = split_bibliography_block(truncated_text)
    print(f"baseline: {len(baseline)} entries, truncated to 50% of text: {len(truncated)} entries recovered "
          f"({len(truncated) / len(baseline):.0%} of baseline count - degrades roughly proportionally, no crash)")


def run_smart_quotes_report() -> None:
    print("\n=== TEXT-stage (smart_quotes_and_dash_variants, text-level) ===")
    clean_pdf = FIXTURES_DIR / "synthetic_social_behavioral_apa7_clean.pdf"
    clean_text = _extract_reference_section_text(clean_pdf)
    baseline = split_bibliography_block(clean_text)
    corrupted_text = cg.smart_quotes_and_dashes(clean_text)
    corrupted = split_bibliography_block(corrupted_text)
    print(f"baseline: {len(baseline)} entries, smart-quotes variant: {len(corrupted)} entries "
          f"({'no effect on splitting' if len(baseline) == len(corrupted) else 'splitting changed'})")


def run_sparse_variants_report() -> None:
    print("\n=== SPARSE/MIXED variants (one bad entry among many clean ones) ===")

    clean_pdf = FIXTURES_DIR / "synthetic_social_behavioral_apa7_clean.pdf"
    clean_text = _extract_reference_section_text(clean_pdf)
    baseline_entries = split_bibliography_block(clean_text)
    entries_text = [e.raw_text for e in baseline_entries]
    n_baseline = len(baseline_entries)

    merged_text = cg.sparse_split_corruption(entries_text, corrupt_index=5, defect_name="merged_with_next")
    merged = split_bibliography_block(merged_text)
    verdict = "localized (exactly 1 fewer)" if len(merged) == n_baseline - 1 else "COLLATERAL DAMAGE"
    print(f"one entry merged with its neighbor: {len(merged)}/{n_baseline} entries recovered ({verdict})")

    quotes_text = cg.sparse_split_corruption(entries_text, corrupt_index=5, defect_name="smart_quotes")
    quotes = split_bibliography_block(quotes_text)
    verdict = "no effect" if len(quotes) == n_baseline else "COLLATERAL DAMAGE"
    print(f"one entry with smart quotes only:   {len(quotes)}/{n_baseline} entries recovered ({verdict})")

    # Content-stage: one entry gets a title-preserving but DOI-corrupting typo, scored
    # against the full 30-entry gold set via score_document's DOI-only matching, so we
    # can see whether the aggregate recall drop is exactly 1/n (isolated) or more.
    n = len(_SOCIAL_BEHAVIORAL)
    extracted, _ = cg.sparse_content_corruption(_SOCIAL_BEHAVIORAL, corrupt_index=0, mutator=cg.typo_doi_digit)
    clean_dois = {normalize_doi(e.doi) for e in _SOCIAL_BEHAVIORAL if e.doi}
    gold_doc = GoldReferences(doi="synthetic", total_reference_count=n, dois_with_doi=clean_dois)
    result = score_document(extracted, gold_doc)
    expected_recall = (len(clean_dois) - 1) / len(clean_dois)
    verdict = "isolated (exactly 1 DOI lost)" if abs(result.doi_recall - expected_recall) < 1e-9 else "unexpected"
    print(f"one entry with malformed DOI among {n}: doi_recall={result.doi_recall:.3f} ({verdict})")

    # Content-stage: one entry gets an author-name typo (title untouched), scored by
    # title-based parsing_match across the full gold set - checks the typo doesn't
    # accidentally make this entry's title collide with a *different* gold title.
    extracted2, gold2 = cg.sparse_content_corruption(_SOCIAL_BEHAVIORAL, corrupt_index=0, mutator=cg.typo_in_author_name)
    result2 = score_parsing(extracted2, gold2)
    verdict2 = "no collision (title untouched, still matches)" if result2.parsing_recall == 1.0 else "unexpected drop"
    print(f"one entry with author-name typo among {n}: parsing_recall={result2.parsing_recall:.3f} ({verdict2})")


if __name__ == "__main__":
    run_split_stage_report()
    run_content_stage_report()
    run_doi_url_variants_report()
    run_merge_stage_report()
    run_smart_quotes_report()
    run_truncation_report()
    run_text_stage_report()
    run_sparse_variants_report()
