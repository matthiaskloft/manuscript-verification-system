"""Merge Crossref- and OpenAlex-derived gold DOI sets into one ground truth per document.

Union rather than intersection: a reference missing a DOI in Crossref's metadata may
still be resolved by OpenAlex's citation graph (or vice versa), so combining sources
recovers more genuine references than either API alone — at the cost of also carrying
forward either source's individual mistakes. See docs/project-plan.md benchmark caveats.
"""

from dataclasses import dataclass, field

from refcheck.benchmark.crossref_gold import fetch_gold_references
from refcheck.benchmark.doi_utils import normalize_doi
from refcheck.benchmark.openalex_gold import fetch_openalex_gold_references
from refcheck.benchmark.score import BenchmarkResult, score_document
from refcheck.benchmark.grobid_client import ExtractedReference
from refcheck.benchmark.crossref_gold import GoldReferenceEntry, GoldReferences


@dataclass
class CombinedGoldReferences:
    doi: str
    crossref_total_references: int
    crossref_dois: set[str]
    openalex_total_referenced_works: int
    openalex_dois: set[str]
    crossref_entries: list[GoldReferenceEntry] = field(default_factory=list)

    @property
    def union_dois(self) -> set[str]:
        return self.crossref_dois | self.openalex_dois

    @property
    def overlap_dois(self) -> set[str]:
        return self.crossref_dois & self.openalex_dois

    def as_gold_references(self) -> GoldReferences:
        """Adapt to the single-source GoldReferences shape score_document() expects."""
        return GoldReferences(
            doi=self.doi,
            total_reference_count=max(self.crossref_total_references, self.openalex_total_referenced_works),
            dois_with_doi=self.union_dois,
        )


def build_combined_gold_references(doi: str) -> CombinedGoldReferences:
    crossref = fetch_gold_references(doi)
    openalex = fetch_openalex_gold_references(doi)
    return CombinedGoldReferences(
        doi=normalize_doi(doi),
        crossref_total_references=crossref.total_reference_count,
        crossref_dois=crossref.dois_with_doi,
        openalex_total_referenced_works=openalex.total_referenced_works,
        openalex_dois=openalex.dois_with_doi,
        crossref_entries=crossref.entries,
    )


def score_against_combined_gold(
    extracted: list[ExtractedReference], gold: CombinedGoldReferences
) -> BenchmarkResult:
    return score_document(extracted, gold.as_gold_references())
