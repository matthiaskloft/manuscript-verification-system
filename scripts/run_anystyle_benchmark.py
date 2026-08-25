"""Run the Tier-2 (AnyStyle) extraction benchmark against the ground truth manifest.

Requires the local AnyStyle Docker image (see docs/project-plan.md and
docker/anystyle/Dockerfile — no official AnyStyle image exists upstream):
    docker build -t refcheck-anystyle -f docker/anystyle/Dockerfile docker/anystyle

Usage:
    python scripts/run_anystyle_benchmark.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from refcheck.benchmark.anystyle_client import call_anystyle, parse_anystyle_references
from refcheck.benchmark.runner import print_report, run_benchmark


def extract(pdf_path: Path):
    return parse_anystyle_references(call_anystyle(pdf_path))


if __name__ == "__main__":
    print_report(run_benchmark(extract))
