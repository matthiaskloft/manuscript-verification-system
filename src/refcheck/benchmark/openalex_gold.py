"""Gold-standard reference DOIs from OpenAlex's `referenced_works` graph.

Complements crossref_gold.py: Crossref only asserts a DOI for references a publisher
explicitly tagged with one. OpenAlex independently resolves a work's reference list
against its own citation graph, so it can recover references Crossref left as bare
unstructured strings. Neither is complete on its own — see docs/project-plan.md.
"""

from dataclasses import dataclass

import pyalex
from pyalex import Works

from refcheck.benchmark.doi_utils import normalize_doi
from refcheck.contact import contact_email as _configured_contact_email

_BATCH_SIZE = 50


@dataclass
class OpenAlexGoldReferences:
    doi: str
    total_referenced_works: int
    dois_with_doi: set[str]


def _short_openalex_id(work_id: str) -> str:
    return work_id.rsplit("/", 1)[-1]


def fetch_openalex_gold_references(
    doi: str, contact_email: str | None = None
) -> OpenAlexGoldReferences:
    """Look up a work's referenced_works graph.

    `contact_email` identifies the caller to OpenAlex's polite pool. It defaults to
    REFCHECK_CONTACT_EMAIL, and to None (the anonymous pool) when that is unset — never
    to a compiled-in address, which a benchmark run from a fork would otherwise send to
    OpenAlex on the original author's behalf. See refcheck.contact.
    """
    pyalex.config.email = contact_email or _configured_contact_email()

    work = Works()[f"https://doi.org/{doi}"]
    referenced_work_ids = work.get("referenced_works", [])

    dois_with_doi: set[str] = set()
    short_ids = [_short_openalex_id(w) for w in referenced_work_ids]
    for i in range(0, len(short_ids), _BATCH_SIZE):
        batch = short_ids[i : i + _BATCH_SIZE]
        results = Works().filter(openalex_id="|".join(batch)).select(["id", "doi"]).get()
        for r in results:
            if r.get("doi"):
                dois_with_doi.add(normalize_doi(r["doi"]))

    return OpenAlexGoldReferences(
        doi=normalize_doi(doi),
        total_referenced_works=len(referenced_work_ids),
        dois_with_doi=dois_with_doi,
    )
