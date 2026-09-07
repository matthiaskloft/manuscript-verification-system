"""Shared DOI normalization so gold and extracted DOIs compare equal regardless of
how they were written (bare DOI, doi.org URL, "doi:" prefix, mixed case)."""

import re

_DOI_URL_PREFIX_RE = re.compile(r"^https?://(dx\.)?doi\.org/", re.IGNORECASE)
# Found via corruption_generators.doi_url_variants(): a bare "doi:" prefix (no URL)
# is also common in reference lists and was previously left unstripped.
_DOI_COLON_PREFIX_RE = re.compile(r"^doi:\s*", re.IGNORECASE)


def normalize_doi(doi: str) -> str:
    stripped = _DOI_URL_PREFIX_RE.sub("", doi.strip())
    stripped = _DOI_COLON_PREFIX_RE.sub("", stripped)
    return stripped.lower()
