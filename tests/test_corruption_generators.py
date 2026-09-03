from openrefcheck.benchmark.ensemble import merge_extracted
from openrefcheck.benchmark.grobid_client import ExtractedReference
from openrefcheck.extraction.tier0 import split_bibliography_block
from openrefcheck.synth import corruption_generators as cg
from openrefcheck.synth.entries import Author, SynthReferenceEntry

_CLEAN_TEXT = (
    "Ainsworth, M. D. S. (1978). Patterns of attachment. Erlbaum.\n\n"
    "Ariely, D. (2008). Predictably irrational. HarperCollins.\n\n"
    "Asch, S. E. (1956). Studies of independence and conformity. Psych. Monographs.\n\n"
    "Bandura, A. (1977). Self-efficacy. Psychological Review, 84(2), 191-215."
)

_ENTRY = SynthReferenceEntry(
    key="test2020example",
    entry_type="article",
    authors=[Author("Jane", "Doe"), Author("John", "Roe")],
    year="2020",
    title="An example study of something",
    journal="Journal of Examples",
    volume="10",
    number="2",
    pages="1--20",
    doi="10.1234/example.5678",
)


def test_merge_all_entries_recovered_by_inline_apa_split():
    baseline = split_bibliography_block(_CLEAN_TEXT)
    assert len(baseline) >= 2
    merged_text = cg.merge_all_entries(_CLEAN_TEXT)
    corrupted = split_bibliography_block(merged_text)
    assert len(corrupted) == len(baseline)


def test_mixed_numbering_recovers_all_entries_via_sequential_check_and_blank_line_fallback():
    entries = ["First entry text.", "Second entry text.", "Third entry text.", "Fourth entry text."]
    mixed = cg.mixed_numbering(entries)
    result = split_bibliography_block(mixed)
    # Previously the real defect here: entries at i=0 and i=3 (i % 3 == 0) get a "[n]"
    # bracket marker ([1], [4]), entry at i=1 gets a dot marker (2.), entry at i=2 gets
    # none. split_bibliography_block() tried the bracket heuristic first and found
    # exactly 2 matches - enough to trust it before the require_sequential guard was
    # added - so it silently absorbed the dot-numbered and unmarked entries into
    # whichever bracket-numbered block preceded them. Now the bracket numbers [1], [4]
    # aren't consecutive, so require_sequential correctly rejects that heuristic and
    # falls through to the blank-line-separated-blocks heuristic, which recovers all 4.
    assert len(result) == 4
    assert [e.raw_text for e in result] == [
        "[1] First entry text.",
        "2. Second entry text.",
        "Third entry text.",
        "[4] Fourth entry text.",
    ]


def test_typo_in_author_name_breaks_title_match_is_false_but_title_should_still_match():
    corrupted = cg.typo_in_author_name(_ENTRY)
    assert corrupted.authors[0].family != _ENTRY.authors[0].family
    result = cg.score_content_corruption(_ENTRY, corrupted)
    # title text itself wasn't touched, so title-based matching should still succeed
    assert result["title_match"] is True


def test_typo_doi_digit_breaks_doi_match():
    corrupted = cg.typo_doi_digit(_ENTRY)
    assert corrupted.doi != _ENTRY.doi
    result = cg.score_content_corruption(_ENTRY, corrupted)
    assert result["doi_match"] is False


def test_typo_in_author_name_does_not_crash_on_two_character_surname():
    short_name_entry = SynthReferenceEntry(
        key="wu2020", entry_type="article", authors=[Author("X", "Wu")],
        year="2020", title="Some title",
    )
    corrupted = cg.typo_in_author_name(short_name_entry)
    assert corrupted.authors[0].family == "Wu"  # unchanged: too short to safely transpose


def test_transpose_year_digits_changes_year():
    corrupted = cg.transpose_year_digits(_ENTRY)
    assert corrupted.year != _ENTRY.year
    assert len(corrupted.year) == 4


def test_swap_page_ranges():
    other = SynthReferenceEntry(
        key="other2021", entry_type="article", authors=[Author("A", "B")],
        year="2021", title="Other", pages="99--110",
    )
    a, b = cg.swap_page_ranges(_ENTRY, other)
    assert a.pages == "99--110"
    assert b.pages == "1--20"


def test_swap_author_order():
    corrupted = cg.swap_author_order(_ENTRY)
    assert corrupted.authors[0].family == "Roe"
    assert corrupted.authors[1].family == "Doe"


def test_drop_required_field_removes_volume_and_number():
    corrupted = cg.drop_required_field(_ENTRY)
    assert corrupted.volume is None
    assert corrupted.number is None
    assert corrupted.title == _ENTRY.title  # unaffected fields stay intact


def test_corrupt_diacritics_strips_accents():
    accented = SynthReferenceEntry(
        key="mueller2020", entry_type="article",
        authors=[Author("Anna", "Müller")], year="2020", title="Some title",
    )
    corrupted = cg.corrupt_diacritics(accented)
    assert corrupted.authors[0].family == "Muller"


def test_duplicate_doi_makes_two_entries_share_an_identifier():
    other = SynthReferenceEntry(
        key="other2021", entry_type="article", authors=[Author("A", "B")],
        year="2021", title="Genuinely different work", doi="10.9999/different",
    )
    corrupted = cg.duplicate_doi(_ENTRY, other)
    assert corrupted.doi == _ENTRY.doi
    assert corrupted.title == other.title  # still a different work, just wrong DOI


def test_duplicate_reference_scenario_produces_two_copies():
    ref = ExtractedReference(index="a", doi="10.1/x", title="Some paper")
    tier_output = cg.duplicate_reference_scenario(ref)
    assert len(tier_output) == 2
    merged = merge_extracted(tier_output)
    assert len(merged) == 1  # DOI-keyed dedup correctly collapses a true duplicate


def test_duplicate_doi_different_works_silently_collapses_in_merge():
    ref_a = ExtractedReference(index="a", doi="10.1/x", title="Paper A")
    ref_b = ExtractedReference(index="b", doi="10.1/y", title="Paper B, unrelated")
    corrupted_tier_output = cg.duplicate_doi_different_works_scenario(ref_a, ref_b)
    merged = merge_extracted(corrupted_tier_output)
    # This is the failure mode itself, not a desired outcome: DOI-keyed dedup cannot
    # tell these apart from a true duplicate once they share a DOI, so it wrongly
    # collapses two distinct works into one.
    assert len(merged) == 1
    assert merged[0].title == "Paper A"  # first-seen wins, "Paper B" silently dropped


def test_smart_quotes_and_dashes_transforms_text():
    text = 'Some "quoted title" and pages 123-145.'
    transformed = cg.smart_quotes_and_dashes(text)
    assert "“" in transformed and "”" in transformed
    assert "123–145" in transformed


def test_sparse_split_corruption_merged_with_next_is_recovered():
    baseline = split_bibliography_block(_CLEAN_TEXT)
    entries_text = [e.raw_text for e in baseline]
    corrupted_text = cg.sparse_split_corruption(entries_text, corrupt_index=1, defect_name="merged_with_next")
    corrupted = split_bibliography_block(corrupted_text)
    assert len(corrupted) == len(baseline)


def test_sparse_split_corruption_smart_quotes_has_no_effect_on_count():
    baseline = split_bibliography_block(_CLEAN_TEXT)
    entries_text = [e.raw_text for e in baseline]
    corrupted_text = cg.sparse_split_corruption(entries_text, corrupt_index=1, defect_name="smart_quotes")
    corrupted = split_bibliography_block(corrupted_text)
    assert len(corrupted) == len(baseline)


def test_sparse_split_corruption_rejects_unknown_defect_name():
    entries_text = [e.raw_text for e in split_bibliography_block(_CLEAN_TEXT)]
    try:
        cg.sparse_split_corruption(entries_text, corrupt_index=0, defect_name="nonsense")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_sparse_content_corruption_isolates_a_single_bad_entry():
    other = SynthReferenceEntry(
        key="other2021", entry_type="article", authors=[Author("A", "B")],
        year="2021", title="A genuinely different title", doi="10.9999/other",
    )
    entries = [_ENTRY, other]
    extracted, gold = cg.sparse_content_corruption(entries, corrupt_index=0, mutator=cg.typo_doi_digit)
    assert len(extracted) == 2 and len(gold) == 2
    # only entries[0]'s DOI should differ from the clean gold DOI
    assert extracted[0].doi != gold[0].doi
    assert extracted[1].doi == gold[1].doi
