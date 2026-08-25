"""Score extracted references against the Crossref-derived gold DOI set.

Precision/recall are computed only over the DOI field, and only over the subset of gold
references Crossref itself resolved to a DOI (see crossref_gold.py docstring for why).
This is a deliberately narrower metric than the plan's original "P/R/F1 per field"
aspiration, traded for being fully automatic (no manual labeling).
"""

from dataclasses import dataclass

from refcheck.benchmark.crossref_gold import GoldReferences
from refcheck.benchmark.grobid_client import ExtractedReference


@dataclass
class BenchmarkResult:
    doi: str
    n_extracted: int
    n_extracted_with_doi: int
    n_gold_total: int
    n_gold_with_doi: int
    true_positives: int
    doi_recall: float
    doi_precision: float
    doi_f1: float


def score_document(
    extracted: list[ExtractedReference], gold: GoldReferences
) -> BenchmarkResult:
    extracted_dois = {ref.doi for ref in extracted if ref.doi}
    true_positives = len(extracted_dois & gold.dois_with_doi)

    doi_recall = true_positives / gold.dois_with_doi.__len__() if gold.dois_with_doi else float("nan")
    doi_precision = true_positives / len(extracted_dois) if extracted_dois else float("nan")
    doi_f1 = (
        2 * doi_precision * doi_recall / (doi_precision + doi_recall)
        if doi_precision and doi_recall and (doi_precision + doi_recall) > 0
        else float("nan")
    )

    return BenchmarkResult(
        doi=gold.doi,
        n_extracted=len(extracted),
        n_extracted_with_doi=len(extracted_dois),
        n_gold_total=gold.total_reference_count,
        n_gold_with_doi=len(gold.dois_with_doi),
        true_positives=true_positives,
        doi_recall=doi_recall,
        doi_precision=doi_precision,
        doi_f1=doi_f1,
    )
