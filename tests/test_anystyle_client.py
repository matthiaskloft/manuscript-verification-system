from refcheck.benchmark.anystyle_client import parse_anystyle_references

_SAMPLE_RAW = [
    {
        "author": [{"family": "Smith", "given": "J."}, {"family": "Doe", "given": "A."}],
        "date": ["2020"],
        "title": ["A referenced paper"],
        "doi": ["10.1000/AbC.123"],
        "url": ["https://doi.org/10.1000/AbC.123"],
        "type": "article-journal",
    },
    {
        "author": [{"family": "Roe", "given": "B."}],
        "date": ["2019"],
        "title": ["No DOI extracted here"],
        "type": "book",
    },
]


def test_parse_anystyle_references_extracts_fields():
    refs = parse_anystyle_references(_SAMPLE_RAW)
    assert len(refs) == 2

    first = refs[0]
    assert first.title == "A referenced paper"
    assert first.year == "2020"
    assert first.doi == "10.1000/abc.123"
    assert first.author_surnames == ["Smith", "Doe"]

    second = refs[1]
    assert second.doi is None


def test_parse_anystyle_references_handles_empty_list():
    assert parse_anystyle_references([]) == []
