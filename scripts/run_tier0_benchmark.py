"""Run the Tier-0 (structured, no external parser) extraction benchmark against the
ground truth manifest.

Unlike regex_doi_extractor.py (a bare whole-document DOI scan, used as Tier 0's
contribution to the ensemble in run_ensemble_benchmark.py), this exercises the actual
structured Tier-0 pipeline a real check uses: refcheck.extraction.document
(bibliography isolation + tier0 splitting) and refcheck.extraction.title (title
heuristics) — the same code real_pipeline.py drives for the GUI's live checks. The
whole-document DOI regex scores DOI recall/precision only and can't be scored on
parsing recall/precision at all (it never produces a title). This script fills that
gap so the splitter/title logic has its own benchmark entry, separate from the
ensemble's DOI-only Tier 0 row.

See scripts/run_grobid_benchmark.py for the ground-truth/fixture setup this shares.

Usage:
    python scripts/run_tier0_benchmark.py
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from refcheck.benchmark.doi_utils import normalize_doi
from refcheck.benchmark.grobid_client import ExtractedReference
from refcheck.benchmark.runner import print_report, run_benchmark
from refcheck.extraction.document import NoBibliographySectionError, extract_references
from refcheck.extraction.title import extract_title

_DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")


def _first_doi(raw_text: str) -> str | None:
    match = _DOI_RE.search(raw_text)
    return normalize_doi(match.group(0).rstrip(".,;)")) if match else None


def extract(pdf_path: Path) -> list[ExtractedReference]:
    try:
        raw_entries = extract_references(pdf_path)
    except NoBibliographySectionError:
        return []
    return [
        ExtractedReference(
            index=str(entry.index),
            title=extract_title(entry.raw_text),
            doi=_first_doi(entry.raw_text),
        )
        for entry in raw_entries
    ]


if __name__ == "__main__":
    print_report(run_benchmark(extract))
