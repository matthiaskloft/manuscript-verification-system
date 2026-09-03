"""Build the ground-truth reference DOI sets for the benchmark fixtures.

Combines Crossref (docs/project-plan.md: gold via Crossref Works API) and OpenAlex's
citation graph per document, then writes a manifest that's safe to commit — it only
contains DOIs and counts, no copyrighted PDF content (the actual PDFs stay in the
gitignored tests/fixtures/local_pdfs/).

One preprint + one published version per manuscript (deduplicated: an earlier OSF
preprint version that was superseded by a later version pointing at the same final
paper is dropped, not tracked twice).

Usage:
    python scripts/build_ground_truth.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from openrefcheck.benchmark.combined_gold import build_combined_gold_references

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "ground_truth.json"

# One entry per manuscript. preprint_pdf is None where no local preprint PDF exists
# (e.g. discriminant_validity: the preprint has no attached PDF in Zotero).
MANUSCRIPTS = [
    {
        "manuscript": "dirichlet_dual_response",
        "published_doi": "10.1007/s11336-023-09924-7",
        "preprint_doi": "10.31234/osf.io/h4f8a",
        "published_pdf": "published_2023_dirichlet_dual_response.pdf",
        "preprint_pdf": "preprint_2022_dirichlet_dual_response.pdf",
    },
    {
        "manuscript": "measuring_variability",
        "published_doi": "10.3758/s13428-024-02394-4",
        "preprint_doi": "10.31234/osf.io/pa4m3",
        "published_pdf": "published_2024_measuring_variability.pdf",
        "preprint_pdf": "preprint_2023_measuring_variability.pdf",
    },
    {
        "manuscript": "discriminant_validity",
        "published_doi": "10.1177/00131644241283400",
        "preprint_doi": "10.31234/osf.io/esvxk",
        "published_pdf": "published_2025_discriminant_validity.pdf",
        "preprint_pdf": None,
    },
    {
        "manuscript": "interval_consensus_model",
        "published_doi": "10.1017/psy.2025.10058",
        "preprint_doi": "10.31234/osf.io/dzvw2_v2",
        "published_pdf": "published_2025_interval_consensus_model.pdf",
        "preprint_pdf": "preprint_2025_interval_consensus_model.pdf",
    },
]


def main() -> None:
    manifest = []
    for entry in MANUSCRIPTS:
        print(f"fetching gold references for {entry['manuscript']} ({entry['published_doi']}) ...")
        gold = build_combined_gold_references(entry["published_doi"])
        manifest.append(
            {
                **entry,
                "crossref_total_references": gold.crossref_total_references,
                "crossref_dois": sorted(gold.crossref_dois),
                "openalex_total_referenced_works": gold.openalex_total_referenced_works,
                "openalex_dois": sorted(gold.openalex_dois),
                "union_dois": sorted(gold.union_dois),
                "overlap_dois": sorted(gold.overlap_dois),
                # Crossref-only, title-bearing entries (may lack a DOI) — used by
                # parsing_match.py to score parsing quality independent of DOI.
                "crossref_entries": [
                    {
                        "title": e.title,
                        "year": e.year,
                        "first_author_surname": e.first_author_surname,
                        "doi": e.doi,
                    }
                    for e in gold.crossref_entries
                ],
            }
        )
        print(
            f"  crossref: {len(gold.crossref_dois)}/{gold.crossref_total_references} with DOI, "
            f"openalex: {len(gold.openalex_dois)}/{gold.openalex_total_referenced_works} with DOI, "
            f"union: {len(gold.union_dois)}, overlap: {len(gold.overlap_dois)}"
        )

    OUTPUT_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nwrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
