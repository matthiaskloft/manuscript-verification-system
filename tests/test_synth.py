from refcheck.synth.bib_writer import format_bib_entry
from refcheck.synth.corruptions import DEFECT_CATALOGUE
from refcheck.synth.entries import BROAD_FIELDS, CURATED_ENTRIES, Author, SynthReferenceEntry


def test_defect_catalogue_has_unique_names_and_valid_stages():
    names = [d.name for d in DEFECT_CATALOGUE]
    assert len(names) == len(set(names))
    assert all(d.stage in {"split", "extract", "text", "merge", "content"} for d in DEFECT_CATALOGUE)
    assert all(d.status in {"implemented", "planned"} for d in DEFECT_CATALOGUE)


def test_curated_entries_have_unique_keys():
    keys = [e.key for e in CURATED_ENTRIES]
    assert len(keys) == len(set(keys))


def test_curated_entries_span_multiple_fields():
    fields = {e.field_of_study for e in CURATED_ENTRIES}
    assert len(fields) >= 5  # cross-field coverage, not just one discipline


def test_each_broad_field_has_at_least_thirty_entries():
    for broad_field in BROAD_FIELDS:
        count = sum(1 for e in CURATED_ENTRIES if e.broad_field == broad_field)
        assert count >= 30, f"{broad_field} only has {count} entries"


def test_format_bib_entry_article():
    entry = SynthReferenceEntry(
        key="doe2020test",
        entry_type="article",
        authors=[Author("Jane", "Doe")],
        year="2020",
        title="A test article",
        journal="Journal of Testing",
        volume="1",
        doi="10.1/test",
    )
    bib = format_bib_entry(entry)
    assert bib.startswith("@article{doe2020test,")
    assert "author = {Doe, Jane}," in bib
    assert "title = {A test article}," in bib
    assert "doi = {10.1/test}," in bib
    assert bib.endswith("}")


def test_format_bib_entry_escapes_special_characters():
    entry = SynthReferenceEntry(
        key="doe2020ampersand",
        entry_type="misc",
        authors=[Author("Jane", "Doe")],
        year="2020",
        title="Cause & effect in some_field",
    )
    bib = format_bib_entry(entry)
    assert r"Cause \& effect in some\_field" in bib
