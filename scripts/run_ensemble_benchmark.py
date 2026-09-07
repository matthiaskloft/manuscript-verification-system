"""Run the Tier-3 (ensemble) extraction benchmark against the ground truth manifest.

Requires both a running GROBID instance and the local AnyStyle Docker image —
see scripts/run_grobid_benchmark.py and scripts/run_anystyle_benchmark.py.

Usage:
    python scripts/run_ensemble_benchmark.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from openrefcheck.benchmark.ensemble import extract_ensemble
from openrefcheck.benchmark.runner import print_report, run_benchmark

if __name__ == "__main__":
    print_report(run_benchmark(extract_ensemble))
