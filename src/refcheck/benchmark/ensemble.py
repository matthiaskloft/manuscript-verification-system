"""Tier 3: ensemble of Tier 0 (regex DOI scan), Tier 1 (GROBID), and Tier 2 (AnyStyle).

Merge strategy is "swiss cheese": a reference counts as found if any tier extracted
it, matched either by DOI or (when no tier gave that particular reference a DOI) by
fuzzy title. Earlier this merged by DOI only and silently dropped every DOI-less
reference — which gutted parsing_recall (see parsing_match.py) down to near zero even
though the underlying tiers individually parsed most references correctly, just
without an in-text DOI to key on. Title-based dedup keeps those references instead of
discarding them, at the cost of also inheriting every tier's title-parsing mistakes.

Tier 0 (bare regex DOI scan) never attaches a title, and it runs first — so plain
"first-seen wins" would let a bare Tier 0 DOI hit permanently block GROBID's or
AnyStyle's richer (titled) version of the same reference from ever entering the merged
set. To avoid that, a later tier's entry for an already-seen DOI is used to fill in a
missing title rather than being discarded outright.

Known limitation: this only unifies a Tier 0 entry with a later tier's entry when the
later tier's DOI extraction *also* succeeded for that reference. If GROBID/AnyStyle
correctly reads a reference's title but fails to tag its DOI (a real, distinct GROBID
failure mode from Tier 0's own independent full-text DOI scan), the merged list ends up
with two rows for one physical reference: Tier 0's DOI-only hit and the later tier's
title-only entry. Neither branch below can catch this, because regex_doi_extractor.py
gives Tier 0 nothing but a bare DOI - no title, year, or author to compare against the
title-only entry with. There is no sound way to unify them without an external lookup
(e.g. resolving the title-only entry's own DOI), which is out of scope for a pure
merge step. In practice this does not corrupt score.py/parsing_match.py's recall or
precision (they key on disjoint subsets - the DOI set and the titled-entries list -
so a row missing one field never satisfies the other metric's denominator), but it does
inflate the raw merged-list length reported as n_extracted.
"""

from pathlib import Path

from refcheck.benchmark.anystyle_client import call_anystyle, parse_anystyle_references
from refcheck.benchmark.grobid_client import ExtractedReference, call_grobid, parse_grobid_tei
from refcheck.benchmark.parsing_match import TITLE_MATCH_THRESHOLD, normalize_title, title_similarity
from refcheck.benchmark.regex_doi_extractor import extract_dois_via_regex


def merge_extracted(*ref_lists: list[ExtractedReference]) -> list[ExtractedReference]:
    merged: list[ExtractedReference] = []
    doi_positions: dict[str, int] = {}
    for refs in ref_lists:
        for ref in refs:
            if ref.doi:
                if ref.doi in doi_positions:
                    existing = merged[doi_positions[ref.doi]]
                    if not existing.title and ref.title:
                        merged[doi_positions[ref.doi]] = ref
                    continue
                doi_positions[ref.doi] = len(merged)
                merged.append(ref)
                continue

            if not ref.title:
                continue
            ref_norm = normalize_title(ref.title)
            if any(
                existing.title and title_similarity(ref_norm, normalize_title(existing.title)) >= TITLE_MATCH_THRESHOLD
                for existing in merged
            ):
                continue
            merged.append(ref)
    return merged


def extract_ensemble(pdf_path: Path) -> list[ExtractedReference]:
    tier0 = extract_dois_via_regex(pdf_path)
    tier1 = parse_grobid_tei(call_grobid(pdf_path))
    tier2 = parse_anystyle_references(call_anystyle(pdf_path))
    return merge_extracted(tier0, tier1, tier2)
