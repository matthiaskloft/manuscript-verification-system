"""Shared benchmark loop: run one tier's extractor over every manifest fixture and
score it two ways against the ground-truth manifest — DOI recall/precision (score.py)
and title-based parsing recall/precision (parsing_match.py). Used by
scripts/run_grobid_benchmark.py, run_anystyle_benchmark.py, and
run_ensemble_benchmark.py so all tiers are scored identically and their tables are
directly comparable.

The two metrics answer different questions: DOI recall can be low either because a
reference was never segmented/parsed or because the source PDF never printed a DOI in
the text for a correctly-parsed reference. Parsing recall isolates the first cause by
matching on Crossref's article-title/unstructured text, which many DOI-less gold
references still carry.
"""

import json
import math
import statistics
from collections.abc import Callable
from pathlib import Path

from refcheck.benchmark.crossref_gold import GoldReferenceEntry, GoldReferences
from refcheck.benchmark.grobid_client import ExtractedReference
from refcheck.benchmark.parsing_match import ParsingMatchResult, score_parsing
from refcheck.benchmark.score import BenchmarkResult, score_document

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent.parent / "tests" / "fixtures" / "local_pdfs"
GROUND_TRUTH_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent / "tests" / "fixtures" / "ground_truth.json"
)


def run_benchmark(
    extract_fn: Callable[[Path], list[ExtractedReference]],
) -> list[tuple[str, str, BenchmarkResult, ParsingMatchResult]]:
    manifest = json.loads(GROUND_TRUTH_PATH.read_text(encoding="utf-8"))

    rows: list[tuple[str, str, BenchmarkResult, ParsingMatchResult]] = []
    for entry in manifest:
        gold = GoldReferences(
            doi=entry["published_doi"],
            total_reference_count=max(
                entry["crossref_total_references"], entry["openalex_total_referenced_works"]
            ),
            dois_with_doi=set(entry["union_dois"]),
        )
        gold_entries = [
            GoldReferenceEntry(
                title=e["title"],
                year=e["year"],
                first_author_surname=e["first_author_surname"],
                doi=e["doi"],
            )
            for e in entry.get("crossref_entries", [])
        ]

        for variant in ("preprint", "published"):
            pdf_name = entry.get(f"{variant}_pdf")
            if pdf_name is None:
                continue
            pdf_path = FIXTURES_DIR / pdf_name
            if not pdf_path.exists():
                print(f"skipping {entry['manuscript']}/{variant}: {pdf_name} not found locally")
                continue

            print(f"processing {entry['manuscript']}/{variant} ({pdf_name}) ...")
            extracted = extract_fn(pdf_path)
            result = score_document(extracted, gold)
            parsing_result = score_parsing(extracted, gold_entries)
            rows.append((entry["manuscript"], variant, result, parsing_result))

    return rows


def print_report(rows: list[tuple[str, str, BenchmarkResult, ParsingMatchResult]]) -> None:
    header = (
        f"{'manuscript':<28} {'variant':<10} {'extracted':>9} {'gold_total':>10} "
        f"{'gold_union':>10} {'TP':>4} {'doi_rec':>7} {'doi_prec':>9} {'doi_F1':>6}  "
        f"{'gold_titled':>11} {'parse_rec':>9} {'parse_prec*':>11}"
    )
    print("\n" + header)
    print("-" * len(header))
    for manuscript, variant, r, p in rows:
        print(
            f"{manuscript:<28} {variant:<10} {r.n_extracted:>9} {r.n_gold_total:>10} "
            f"{r.n_gold_with_doi:>10} {r.true_positives:>4} {r.doi_recall:>7.2f} "
            f"{r.doi_precision:>9.2f} {r.doi_f1:>6.2f}  "
            f"{p.n_gold_with_title:>11} {p.parsing_recall:>9.2f} {p.parsing_precision:>11.2f}"
        )
    print("* parse_prec is a weak signal when gold_titled << gold_total - see parsing_match.py docstring")

    if rows:

        def _mean_excluding_nan(values: list[float]) -> tuple[float, int]:
            clean = [v for v in values if not math.isnan(v)]
            excluded = len(values) - len(clean)
            mean = statistics.fmean(clean) if clean else float("nan")
            return mean, excluded

        avg_recall, n_excl_recall = _mean_excluding_nan([r.doi_recall for _, _, r, _ in rows])
        avg_precision, n_excl_precision = _mean_excluding_nan([r.doi_precision for _, _, r, _ in rows])
        avg_parse_recall, n_excl_parse_recall = _mean_excluding_nan([p.parsing_recall for _, _, _, p in rows])
        avg_parse_precision, n_excl_parse_precision = _mean_excluding_nan(
            [p.parsing_precision for _, _, _, p in rows]
        )
        print(
            f"\naverage doi_recall={avg_recall:.3f} doi_precision={avg_precision:.3f} "
            f"parsing_recall={avg_parse_recall:.3f} parsing_precision={avg_parse_precision:.3f}"
        )
        print(
            f"excluded from average due to NaN: doi_recall={n_excl_recall} "
            f"doi_precision={n_excl_precision} parsing_recall={n_excl_parse_recall} "
            f"parsing_precision={n_excl_parse_precision} (of {len(rows)} rows)"
        )
