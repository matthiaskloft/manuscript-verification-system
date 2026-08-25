"""Run the Tier-1 (GROBID) extraction benchmark against the ground truth manifest.

Requires a running GROBID instance (see docs/project-plan.md):
    docker run --rm -p 8070:8070 grobid/grobid:0.8.1

Ground truth (Crossref + OpenAlex gold reference DOIs, one entry per manuscript, with
a preprint and/or published PDF) is built by scripts/build_ground_truth.py and
committed at tests/fixtures/ground_truth.json. The PDFs themselves are not committed
(see tests/fixtures/local_pdfs/, gitignored) — the shared runner skips any fixture
that isn't present locally.

Usage:
    python scripts/run_grobid_benchmark.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from refcheck.benchmark.grobid_client import call_grobid, parse_grobid_tei
from refcheck.benchmark.runner import print_report, run_benchmark


def extract(pdf_path: Path):
    return parse_grobid_tei(call_grobid(pdf_path))


if __name__ == "__main__":
    print_report(run_benchmark(extract))
