from refcheck.gui.models import ReferenceResult
from refcheck.gui.report_data import citation_bin_counts, outlet_breakdown, topic_breakdown


def _result(n: int, doi: str, outlet: str, status: str = "verified") -> ReferenceResult:
    return ReferenceResult(n=n, raw="", title="", doi=doi, status=status, confidence=1.0, outlet=outlet)


def test_outlet_breakdown_counts_articles_and_deduplicates_dois():
    results = [
        _result(1, "10.1/a", "Journal A"),
        _result(2, "10.1/b", "Journal A"),
        _result(3, "10.1/A", "Journal A", status="dup"),
        _result(4, "10.1/c", "arXiv"),
        _result(5, "no match", "", status="halluc"),
    ]

    # Explicit 0: this test is about counting and DOI dedup, not about the default floor,
    # which is 1 and would hide the single-article outlet the dedup case needs.
    assert outlet_breakdown(results, 0) == (["arXiv", "Journal A"], [1, 2])
    assert outlet_breakdown(results, min_unique_citations=1) == (["Journal A"], [2])
    assert outlet_breakdown(results, min_unique_citations=2) == ([], [])


def _cited(n: int, citations, doi: str | None = None, status: str = "verified") -> ReferenceResult:
    return ReferenceResult(
        n=n, raw=f"ref {n}", title=f"t{n}", doi=doi or f"10.1/{n}", status=status,
        confidence=1.0, citations=citations,
    )


def test_citation_bins_count_references_not_citations():
    """The y-axis is references, read like the publication-age histogram beside it. The
    chart this replaced plotted one bar per reference on a symlog axis, which answered
    "how tall is reference 14?" and became unreadable past about thirty entries."""
    labels, counts = citation_bin_counts(
        [_cited(1, 0), _cited(2, 5), _cited(3, 7), _cited(4, 4200)]
    )

    assert labels == ["0", "1–9", "10–49", "50–199", "200–999", "1000+"]
    assert counts == [1, 2, 0, 0, 0, 1]


def test_the_bands_are_order_of_magnitude_rather_than_equal_width():
    """Citation counts are heavily skewed — a reference list holds a dozen works under 50
    and one over 10,000 — so equal-width bins would put everything in the first bar."""
    labels, counts = citation_bin_counts([_cited(n, value) for n, value in enumerate([9, 10, 49, 50], start=1)])

    assert dict(zip(labels, counts))["1–9"] == 1
    assert dict(zip(labels, counts))["10–49"] == 2
    assert dict(zip(labels, counts))["50–199"] == 1


def test_a_reference_with_no_reported_count_is_not_banked_as_a_zero():
    """"Nobody told us" is not "cited by nobody", and the "0" band is a real finding."""
    _labels, counts = citation_bin_counts([_cited(1, None), _cited(2, 0)])

    assert sum(counts) == 1
    assert counts[0] == 1


def test_the_same_work_cited_twice_is_counted_once():
    """Deduped by DOI, like the values helper it is built on — a duplicated reference
    should not make its band look twice as populated."""
    _labels, counts = citation_bin_counts(
        [_cited(1, 5, doi="10.1/same"), _cited(2, 5, doi="10.1/same", status="dup")]
    )

    assert sum(counts) == 1


def test_the_outlet_chart_defaults_to_outlets_cited_more_than_once():
    """A reference list is mostly outlets appearing exactly once, and fifty one-tall bars
    say nothing about where the manuscript's literature concentrates. The floor is strict,
    matching the screen's "More than N" wording."""
    results = [
        _result(1, "10.1/a", "Journal A"),
        _result(2, "10.1/b", "Journal A"),
        _result(3, "10.1/c", "Journal B"),
    ]

    assert outlet_breakdown(results) == (["Journal A"], [2])
    assert outlet_breakdown(results, 0) == (["Journal B", "Journal A"], [1, 2])


def _topical(n: int, topics: tuple[str, ...], doi: str | None = None) -> ReferenceResult:
    return ReferenceResult(
        n=n, raw=f"ref {n}", title=f"t{n}", doi=doi or f"10.1/{n}", status="verified",
        confidence=1.0, topics=topics,
    )


def test_topic_breakdown_reads_openalex_topics():
    """It used to read a singular `topic` field against a hard-coded list of five subject
    names, and nothing in the real pipeline ever set that field — so the panel showed its
    empty state on every check ever run."""
    labels, counts = topic_breakdown(
        [
            _topical(1, ("Network analysis", "Psychometrics")),
            _topical(2, ("Network analysis",)),
        ]
    )

    assert labels[-1] == "Network analysis"
    assert dict(zip(labels, counts)) == {"Psychometrics": 1, "Network analysis": 2}


def test_a_work_is_counted_under_every_topic_it_carries():
    """The bars sum to more than the reference count, and that is the honest shape for
    breadth: a paper sitting across three areas belongs in all three."""
    _labels, counts = topic_breakdown([_topical(1, ("A", "B", "C"))])

    assert sum(counts) == 3


def test_topic_breakdown_dedupes_by_doi():
    """A reference the list prints twice should not make its subject area look twice as
    central."""
    _labels, counts = topic_breakdown(
        [_topical(1, ("A",), doi="10.1/same"), _topical(2, ("A",), doi="10.1/same")]
    )

    assert counts == [1]


def test_topic_breakdown_keeps_only_the_leading_topics():
    """Three topics per work means a thirty-entry bibliography can name sixty; past a
    handful the panel stops showing breadth and starts being a list."""
    results = [_topical(n, (f"Topic {n}",)) for n in range(20)]
    results.append(_topical(99, ("Topic 0",)))

    labels, counts = topic_breakdown(results)

    assert len(labels) == 8
    assert labels[-1] == "Topic 0"
    assert counts[-1] == 2


def test_a_reference_with_no_topics_contributes_nothing():
    assert topic_breakdown([_topical(1, ())]) == ([], [])
