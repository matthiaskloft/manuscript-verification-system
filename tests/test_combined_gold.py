from openrefcheck.benchmark.combined_gold import CombinedGoldReferences


def _make(crossref: set[str], openalex: set[str]) -> CombinedGoldReferences:
    return CombinedGoldReferences(
        doi="10.1234/example",
        crossref_total_references=10,
        crossref_dois=crossref,
        openalex_total_referenced_works=8,
        openalex_dois=openalex,
    )


def test_union_recovers_dois_missed_by_either_source_alone():
    gold = _make(crossref={"10.1/a", "10.1/b"}, openalex={"10.1/b", "10.1/c"})
    assert gold.union_dois == {"10.1/a", "10.1/b", "10.1/c"}
    assert gold.overlap_dois == {"10.1/b"}


def test_as_gold_references_uses_larger_total_and_union_dois():
    gold = _make(crossref={"10.1/a"}, openalex={"10.1/b"})
    adapted = gold.as_gold_references()
    assert adapted.total_reference_count == 10  # max(10, 8)
    assert adapted.dois_with_doi == {"10.1/a", "10.1/b"}


def test_empty_openalex_source_falls_back_to_crossref_only():
    gold = _make(crossref={"10.1/a", "10.1/b"}, openalex=set())
    assert gold.union_dois == {"10.1/a", "10.1/b"}
    assert gold.overlap_dois == set()
