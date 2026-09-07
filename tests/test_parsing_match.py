from openrefcheck.benchmark.crossref_gold import GoldReferenceEntry
from openrefcheck.benchmark.grobid_client import ExtractedReference
from openrefcheck.benchmark.parsing_match import score_parsing


def test_score_parsing_matches_clean_titles():
    extracted = [
        ExtractedReference(index="b0", title="A Referenced Paper"),
        ExtractedReference(index="b1", title="Something Unrelated"),
    ]
    gold = [
        GoldReferenceEntry(title="A referenced paper", year="2020", first_author_surname="Smith", doi=None),
        GoldReferenceEntry(title="A completely different paper", year="2019", first_author_surname="Doe", doi=None),
    ]
    result = score_parsing(extracted, gold)
    assert result.matched == 1
    assert result.n_gold_with_title == 2
    assert result.n_extracted_with_title == 2
    assert result.parsing_recall == 0.5
    assert result.parsing_precision == 0.5


def test_score_parsing_matches_title_embedded_in_unstructured_citation():
    extracted = [ExtractedReference(index="b0", title="Standards for educational and psychological testing")]
    gold = [
        GoldReferenceEntry(
            title=(
                "American Educational Research Association (Ed.). (2011). "
                "Standards for educational and psychological testing. American Educational Research Association."
            ),
            year=None,
            first_author_surname=None,
            doi=None,
        )
    ]
    result = score_parsing(extracted, gold)
    assert result.matched == 1
    assert result.parsing_recall == 1.0


def test_score_parsing_no_gold_titles_is_nan():
    extracted = [ExtractedReference(index="b0", title="Some title")]
    gold = [GoldReferenceEntry(title=None, year=None, first_author_surname=None, doi=None)]
    result = score_parsing(extracted, gold)
    assert result.n_gold_with_title == 0
    assert result.parsing_recall != result.parsing_recall  # NaN != NaN
