"""Gold-standard reference DOIs from the Crossref Works API.

Per docs/project-plan.md ("Referenzextraktion" / "Einschränkungen dieses Benchmarks"):
Crossref reference lists are not guaranteed to be fully structured. Many publishers only
assert a DOI per reference without author/title/year fields. We therefore only use the
subset of gold references that carry an asserted DOI as ground truth for the DOI metric —
a recall/precision metric over that subset needs no manual labeling, at the cost of not
covering references Crossref itself couldn't resolve to a DOI.

Separately, many references that lack an asserted DOI still carry an `article-title`
(or at least an `unstructured` citation string) and a `year`. `entries` exposes that
richer, DOI-independent metadata so parsing_match.py can score whether a tier correctly
read a reference at all, without requiring the source PDF to print a DOI in the text.
"""

from dataclasses import dataclass, field

import requests

from openrefcheck.benchmark.doi_utils import normalize_doi
from openrefcheck.contact import contact_email

_USER_AGENT = "openrefcheck-benchmark"


def _crossref_headers() -> dict[str, str]:
    """Identify the benchmark to Crossref, with a mailto only if one is configured.

    Built per call rather than as a module constant so OPENREFCHECK_CONTACT_EMAIL is read at
    request time, and so an unset variable yields a plain User-Agent instead of a
    compiled-in address — see openrefcheck.contact.
    """
    email = contact_email()
    return {"User-Agent": f"{_USER_AGENT} (mailto:{email})" if email else _USER_AGENT}


@dataclass
class GoldReferenceEntry:
    title: str | None
    year: str | None
    first_author_surname: str | None
    doi: str | None


@dataclass
class GoldReferences:
    doi: str
    total_reference_count: int
    dois_with_doi: set[str]
    entries: list[GoldReferenceEntry] = field(default_factory=list)


def _entry_from_reference(r: dict) -> GoldReferenceEntry:
    title = r.get("article-title") or r.get("unstructured")
    first_author = r.get("author")
    return GoldReferenceEntry(
        title=title,
        year=r.get("year"),
        first_author_surname=first_author,
        doi=normalize_doi(r["DOI"]) if "DOI" in r else None,
    )


def fetch_gold_references(doi: str) -> GoldReferences:
    response = requests.get(
        f"https://api.crossref.org/works/{doi}", headers=_crossref_headers(), timeout=30
    )
    response.raise_for_status()
    refs = response.json()["message"].get("reference", [])
    dois_with_doi = {normalize_doi(r["DOI"]) for r in refs if "DOI" in r}
    entries = [_entry_from_reference(r) for r in refs]
    return GoldReferences(
        doi=normalize_doi(doi),
        total_reference_count=len(refs),
        dois_with_doi=dois_with_doi,
        entries=entries,
    )
