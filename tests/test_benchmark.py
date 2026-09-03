from openrefcheck.benchmark.crossref_gold import GoldReferences
from openrefcheck.benchmark.doi_utils import normalize_doi
from openrefcheck.benchmark.grobid_client import parse_grobid_tei
from openrefcheck.benchmark.score import score_document

_SAMPLE_TEI = """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader>
    <fileDesc>
      <sourceDesc>
        <biblStruct>
          <analytic>
            <author><persName><surname>PaperAuthor</surname></persName></author>
          </analytic>
        </biblStruct>
      </sourceDesc>
    </fileDesc>
  </teiHeader>
  <text>
    <back>
      <div>
        <listBibl>
          <biblStruct xml:id="b0">
            <analytic>
              <title level="a" type="main">A referenced paper</title>
              <author><persName><surname>Smith</surname></persName></author>
              <author><persName><surname>Doe</surname></persName></author>
              <idno type="DOI">10.1000/AbC.123</idno>
            </analytic>
            <monogr>
              <imprint><date type="published" when="2020">2020</date></imprint>
            </monogr>
          </biblStruct>
          <biblStruct xml:id="b1">
            <analytic>
              <title level="a" type="main">No DOI here</title>
              <author><persName><surname>Roe</surname></persName></author>
            </analytic>
          </biblStruct>
        </listBibl>
      </div>
    </back>
  </text>
</TEI>
"""


def test_normalize_doi_strips_url_prefix_and_lowercases():
    assert normalize_doi("https://doi.org/10.1000/AbC.123") == "10.1000/abc.123"
    assert normalize_doi("10.1000/AbC.123") == "10.1000/abc.123"


def test_normalize_doi_strips_dx_doi_org_and_doi_colon_prefix():
    assert normalize_doi("http://dx.doi.org/10.1000/AbC.123") == "10.1000/abc.123"
    assert normalize_doi("doi:10.1000/AbC.123") == "10.1000/abc.123"
    assert normalize_doi("DOI:10.1000/AbC.123") == "10.1000/abc.123"


def test_parse_grobid_tei_excludes_header_biblstruct():
    refs = parse_grobid_tei(_SAMPLE_TEI)
    assert len(refs) == 2  # header biblStruct (no xml:id) is excluded


def test_parse_grobid_tei_extracts_fields():
    refs = parse_grobid_tei(_SAMPLE_TEI)
    first = refs[0]
    assert first.title == "A referenced paper"
    assert first.year == "2020"
    assert first.doi == "10.1000/abc.123"
    assert first.author_surnames == ["Smith", "Doe"]

    second = refs[1]
    assert second.doi is None


def test_score_document_recall_precision():
    refs = parse_grobid_tei(_SAMPLE_TEI)
    gold = GoldReferences(
        doi="10.9999/gold-doc",
        total_reference_count=3,
        dois_with_doi={"10.1000/abc.123", "10.2000/missed-one"},
    )
    result = score_document(refs, gold)
    assert result.n_extracted == 2
    assert result.n_extracted_with_doi == 1
    assert result.true_positives == 1
    assert result.doi_recall == 0.5  # found 1 of 2 gold DOIs
    assert result.doi_precision == 1.0  # the 1 DOI we extracted was correct
