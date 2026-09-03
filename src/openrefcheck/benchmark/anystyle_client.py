"""Run AnyStyle (Tier 2, see docs/project-plan.md) via the local Docker image
built from docker/anystyle/Dockerfile — no official AnyStyle image exists, it's
normally distributed as a Ruby gem, not a container.

Build once with:
    docker build -t openrefcheck-anystyle -f docker/anystyle/Dockerfile docker/anystyle
"""

import json
import subprocess
from pathlib import Path

from openrefcheck.benchmark.doi_utils import normalize_doi
from openrefcheck.benchmark.grobid_client import ExtractedReference

_DOCKER_IMAGE = "openrefcheck-anystyle"


def call_anystyle(pdf_path: Path, docker_image: str = _DOCKER_IMAGE) -> list[dict]:
    """Run `anystyle find` on a PDF inside the Docker image and return the parsed
    CSL/JSON reference list (AnyStyle's own structured format, not yet our
    ExtractedReference shape — see parse_anystyle_references)."""
    pdf_path = pdf_path.resolve()
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{pdf_path.parent}:/data",
            docker_image,
            "--stdout",
            "-f",
            "json",
            "find",
            f"/data/{pdf_path.name}",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    )
    result.check_returncode()
    return json.loads(result.stdout)


def parse_anystyle_references(raw_references: list[dict]) -> list[ExtractedReference]:
    """Adapt AnyStyle's CSL-ish JSON into the same ExtractedReference shape used
    for GROBID, so both tiers can be scored with the same score_document()."""
    extracted = []
    for i, ref in enumerate(raw_references):
        title_list = ref.get("title", [])
        date_list = ref.get("date", [])
        doi_list = ref.get("doi", [])

        author_surnames = [a["family"] for a in ref.get("author", []) if "family" in a]

        extracted.append(
            ExtractedReference(
                index=str(i),
                title=title_list[0] if title_list else None,
                year=date_list[0] if date_list else None,
                doi=normalize_doi(doi_list[0]) if doi_list else None,
                author_surnames=author_surnames,
            )
        )
    return extracted
