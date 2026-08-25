from refcheck.benchmark.ensemble import merge_extracted
from refcheck.benchmark.grobid_client import ExtractedReference


def test_merge_deduplicates_by_doi_filling_in_title_from_a_later_tier():
    tier0 = [ExtractedReference(index="0", doi="10.1/a")]  # bare regex hit, no title
    tier1 = [
        ExtractedReference(index="0", doi="10.1/a", title="richer title"),
        ExtractedReference(index="1", doi="10.1/b"),
    ]
    tier2 = [ExtractedReference(index="0", doi="10.1/c")]

    merged = merge_extracted(tier0, tier1, tier2)
    dois = {ref.doi for ref in merged}
    assert dois == {"10.1/a", "10.1/b", "10.1/c"}
    # tier1's titled version fills in tier0's title-less hit rather than being dropped
    assert next(r for r in merged if r.doi == "10.1/a").title == "richer title"


def test_merge_keeps_doi_less_references_deduped_by_title():
    tier0 = [ExtractedReference(index="0", doi=None, title="A Referenced Paper")]
    tier1 = [ExtractedReference(index="0", doi=None, title="a referenced paper")]
    merged = merge_extracted(tier0, tier1)
    assert len(merged) == 1
    assert merged[0].title == "A Referenced Paper"  # first-seen wins


def test_merge_drops_doi_less_references_without_a_title():
    tier0 = [ExtractedReference(index="0", doi=None, title=None)]
    merged = merge_extracted(tier0)
    assert merged == []


def test_merge_handles_no_overlap():
    tier0 = [ExtractedReference(index="0", doi="10.1/a")]
    tier1 = [ExtractedReference(index="0", doi="10.1/b")]
    merged = merge_extracted(tier0, tier1)
    assert {ref.doi for ref in merged} == {"10.1/a", "10.1/b"}


def test_merge_double_counts_a_doi_only_hit_alongside_a_title_only_hit_for_the_same_reference():
    # Known, documented limitation (see ensemble.py docstring): Tier 0's regex DOI scan
    # carries no title/year/author, so if a later tier reads the title correctly but
    # misses the DOI for that same physical reference, nothing can unify the two rows -
    # the DOI-only branch has no title to compare, and the title-only branch has no DOI
    # to compare. This locks in that current, understood behavior rather than pretending
    # it's fixed; it does not corrupt score_document/score_parsing since those key on
    # disjoint DOI-set and titled-entries subsets respectively.
    tier0 = [ExtractedReference(index="0", doi="10.1/a")]  # bare DOI hit, no title
    tier1 = [ExtractedReference(index="0", doi=None, title="A Referenced Paper")]  # DOI tagging missed
    merged = merge_extracted(tier0, tier1)
    assert len(merged) == 2
