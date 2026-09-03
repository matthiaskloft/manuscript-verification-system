"""Tier 0's contribution to the ensemble: a bare regex DOI scan over the whole PDF
text, no reference-list splitting involved. split_bibliography_block() (see
openrefcheck.extraction.tier0) isolates entries but doesn't itself parse a DOI out of
each one — for the ensemble we only need DOI hits, not full structured entries, so
scanning the whole page text directly is simpler and cheaper than wiring splitting
and per-entry DOI parsing together for this purpose.

This will also occasionally pick up the paper's own DOI (printed in a running
header/footer) as a false "reference" — acceptable noise for a Tier 0 baseline; it
only shows up as a precision hit against the ensemble's gold set, which does not
include the source document's own DOI.
"""

import re
from pathlib import Path

import fitz  # PyMuPDF

from openrefcheck.benchmark.doi_utils import normalize_doi
from openrefcheck.benchmark.grobid_client import ExtractedReference

# Standard DOI syntax (Crossref's own recommended pattern), case-insensitive.
_DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")


def extract_dois_via_regex(pdf_path: Path) -> list[ExtractedReference]:
    doc = fitz.open(pdf_path)
    text = "\n".join(page.get_text() for page in doc)
    doc.close()

    dois = {normalize_doi(m.group(0).rstrip(".,;)")) for m in _DOI_RE.finditer(text)}
    return [ExtractedReference(index=str(i), doi=doi) for i, doi in enumerate(sorted(dois))]
