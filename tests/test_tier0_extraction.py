from refcheck.extraction.tier0 import (
    Flattening,
    _conservative_gates,
    _flattening_evidence,
    _numbered_gates,
    split_bibliography_block,
)


def test_numbered_gates_are_declared_non_recoverable():
    # The three numbered-marker heuristics must return immediately on a match,
    # skipping flattening-evidence/recovery entirely -- split_bibliography_block's
    # traversal branches on this field, so a gate misdeclaring it would silently
    # change which entries win a real split.
    assert [gate.recoverable for gate in _numbered_gates()] == [False, False, False]


def test_conservative_gates_are_declared_recoverable():
    # Blank-line and APA/JSS author-start gates must only produce a baseline that
    # flattening-evidence/recovery still gets to examine and possibly replace.
    assert [gate.recoverable for gate in _conservative_gates("irrelevant")] == [True, True, True]


def test_bracket_numbered_style():
    text = (
        "[1] Doe, J. (2020). A title. Journal, 1(1), 1-10.\n"
        "[2] Roe, R. (2019). Another title. Journal, 2(2), 11-20."
    )
    entries = split_bibliography_block(text)
    assert len(entries) == 2
    assert entries[0].raw_text.startswith("Doe, J.")
    assert entries[1].raw_text.startswith("Roe, R.")


def test_dot_numbered_marker_alone_on_its_own_line():
    # PDF text extraction commonly wraps right after a numbered marker, landing it
    # alone on its own line with no trailing whitespace character at all.
    text = "1.\nDoe, J. (2020). A title. Journal, 1(1), 1-10.\n2.\nRoe, R. (2019). Another title."
    entries = split_bibliography_block(text)
    assert len(entries) == 2
    assert entries[0].raw_text.startswith("Doe, J.")
    assert entries[1].raw_text.startswith("Roe, R.")


def test_doi_fragment_is_not_mistaken_for_a_dot_numbered_marker():
    # A loose \s* lookahead would match "10.1136/bmj..." as a false "marker 10.",
    # hijacking priority away from the APA fallback heuristic below.
    text = (
        "Doe, J. (2020). A title. https://doi.org/10.1136/bmj.b2535\n"
        "Roe, R. (2019). Another title. https://doi.org/10.1001/jama.2019.1234"
    )
    entries = split_bibliography_block(text)
    assert len(entries) == 2
    assert entries[0].raw_text.startswith("Doe, J.")
    assert entries[1].raw_text.startswith("Roe, R.")


def test_dot_numbered_style():
    text = (
        "1. Doe, J. (2020). A title. Journal, 1(1), 1-10.\n"
        "2. Roe, R. (2019). Another title. Journal, 2(2), 11-20."
    )
    entries = split_bibliography_block(text)
    assert len(entries) == 2
    assert entries[0].raw_text.startswith("Doe, J.")


def test_blank_line_separated_entries():
    text = (
        "Doe, J. (2020). A title.\nJournal, 1(1), 1-10.\n"
        "\n"
        "Roe, R. (2019). Another title.\nJournal, 2(2), 11-20."
    )
    entries = split_bibliography_block(text)
    assert len(entries) == 2
    assert entries[0].raw_text == "Doe, J. (2020). A title. Journal, 1(1), 1-10."


def test_apa_style_fallback_no_numbering_or_blank_lines():
    text = (
        "Doe, J. (2020). A title. Journal, 1(1), 1-10.\n"
        "Roe, R. (2019). Another title. Journal, 2(2), 11-20."
    )
    entries = split_bibliography_block(text)
    assert len(entries) == 2
    assert entries[0].raw_text.startswith("Doe, J.")
    assert entries[1].raw_text.startswith("Roe, R.")


def test_bare_number_style_no_punctuation():
    text = (
        "1 Hogan JW, Laird NM. Intention-to-treat analyses for distributed lag models. Biometrics 2009.\n"
        "2 Smith AB, Jones CD. Another paper on causal inference. Stats 2010."
    )
    entries = split_bibliography_block(text)
    assert len(entries) == 2
    assert entries[0].raw_text.startswith("Hogan JW")
    assert entries[1].raw_text.startswith("Smith AB")


def test_numbered_marker_with_wrapped_page_range_does_not_hijack_split():
    # A justified APA bibliography's page range wraps onto its own line ("238-\n246."),
    # producing a bare "246." that looks like a "1." numbered marker. require_sequential
    # must reject it (246 != the expected next number) rather than let two coincidental
    # "marker" hits corrupt the whole split.
    text = (
        "1. Doe, J. (2020). A title. Psychological Bulletin, 107, 238-\n"
        "246.\n"
        "2. Roe, R. (2019). Another title. Journal, 2(2), 11-20.\n"
        "3. Lee, K. (2018). Third title. Journal, 3(3), 21-30."
    )
    entries = split_bibliography_block(text)
    assert len(entries) == 3
    assert entries[0].raw_text == "Doe, J. (2020). A title. Psychological Bulletin, 107, 238-\n246."
    assert entries[1].raw_text.startswith("Roe, R.")
    assert entries[2].raw_text.startswith("Lee, K.")


def test_sequential_nonreference_numbers_do_not_hijack_apa_split():
    text = (
        "Doe, J. (2020). A title.\n\n"
        "10 https://example.org/software-a\n\n"
        "11 https://example.org/software-b\n\n"
        "Roe, R. (2019). Another title."
    )

    entries = split_bibliography_block(text)

    assert len(entries) == 4
    assert entries[0].raw_text.startswith("Doe, J.")
    assert entries[-1].raw_text.startswith("Roe, R.")


def test_dot_numbered_entries_flattened_on_one_line():
    text = (
        "1. Doe AB. First title. Journal. 2020. "
        "2. Roe CD. Second title. Journal. 2021. "
        "3. Moe EF. Third title. Journal. 2022."
    )

    entries = split_bibliography_block(text)

    assert len(entries) == 3
    assert entries[0].raw_text.startswith("Doe AB.")
    assert entries[2].raw_text.startswith("Moe EF.")


def test_apa_fallback_with_lowercase_surname_particle():
    text = (
        "van der Veen, D., & Erp, S. (2021). A title about network models. Journal, 1(1), 1-10.\n"
        "de Vries, A. (2019). Another title about statistics. Journal, 2(2), 11-20."
    )
    entries = split_bibliography_block(text)
    assert len(entries) == 2
    assert entries[0].raw_text.startswith("van der Veen")
    assert entries[1].raw_text.startswith("de Vries")


def test_apa_fallback_with_capitalized_surname_particle():
    text = (
        "De Mario, T. J. (2020). A title about psychology. Journal, 1(1), 1-10.\n"
        "Smith, A. B. (2019). Another title. Journal, 2(2), 11-20."
    )
    entries = split_bibliography_block(text)
    assert len(entries) == 2
    assert entries[0].raw_text.startswith("De Mario")
    assert entries[1].raw_text.startswith("Smith, A. B.")


def test_apa_fallback_does_not_split_on_wrapped_co_author_line():
    # A long author list wraps mid-entry so a co-author's name ("McNally, R. J.,")
    # opens its own line. Without year-gating this would look like a new entry start
    # and truncate the real (still-incomplete) entry above it.
    text = (
        "Borsboom, D., Cramer, A. O. J., van der Maas, H. L. J.,\n"
        "McNally, R. J., & Robinaugh, D. J. (2021). Network theory. Journal, 1(1), 1-10.\n"
        "Smith, A. B. (2019). Another title. Journal, 2(2), 11-20."
    )
    entries = split_bibliography_block(text)
    assert len(entries) == 2
    assert "McNally" in entries[0].raw_text
    assert entries[0].raw_text.startswith("Borsboom")
    assert entries[1].raw_text.startswith("Smith, A. B.")


def test_apa_entries_joined_on_one_line_are_split_after_completed_year():
    text = (
        "Doe, J., Smith, A. B., & Roe, C. (2020). A first title. Journal, 1, 1-10. "
        "Moe, D. (2021). A second title. Journal, 2, 11-20."
    )

    entries = split_bibliography_block(text)

    assert len(entries) == 2
    assert entries[0].raw_text.startswith("Doe, J.")
    assert "Smith, A. B." in entries[0].raw_text
    assert entries[1].raw_text.startswith("Moe, D.")


def test_inline_apa_split_leaves_edited_book_chapter_intact():
    # The chapter's editors ("In Smith, A. B., & Jones, C. D. (Eds.), ...") match the
    # inline author pattern mid-entry. Splitting there both truncates the chapter and
    # — since the fragment left behind carries no year — blocks the year gate from
    # accepting the next real entry, losing two references to one editor list.
    text = (
        "Doe, J. (2020). A first article title. Journal of Examples, 1(1), 1-10.\n\n"
        "Roe, R. (2019). A chapter about things. In Smith, A. B., & Jones, C. D. (Eds.), "
        "The handbook of examples (pp. 30-55). Academic Press.\n\n"
        "Young, Y. (2021). A third article. Journal of Methods, 3(2), 100-120."
    )

    entries = split_bibliography_block(text)

    assert len(entries) == 3
    assert entries[1].raw_text.startswith("Roe, R.")
    assert "Academic Press." in entries[1].raw_text
    assert entries[2].raw_text.startswith("Young, Y.")


def test_partly_flattened_german_list_splits_at_entries_not_at_editions():
    # One stuck block means the recovery pass legitimately runs. The edition numbers
    # "(1. Aufl.)" ... "(5. Aufl.)" are an ascending inline run of five, so without an
    # entry-boundary requirement the numbered recovery beats the correct split and
    # shreds every entry at its edition instead.
    text = (
        "Müller, K. (2019). Einführung in die Statistik (1. Aufl.). Springer.\n\n"
        "Schmidt, H. (2020). Grundlagen der Psychologie (2. Aufl.). Beltz. "
        "Weber, L. (2021). Methoden der Forschung (3. Aufl.). Hogrefe.\n\n"
        "Fischer, M. (2022). Angewandte Statistik (4. Aufl.). Springer.\n\n"
        "Becker, T. (2023). Empirische Sozialforschung (5. Aufl.). Beltz."
    )

    entries = split_bibliography_block(text)

    assert len(entries) == 5
    assert entries[1].raw_text.startswith("Schmidt, H.")
    assert entries[2].raw_text.startswith("Weber, L.")
    assert entries[4].raw_text.startswith("Becker, T.")


def test_flattened_vancouver_entries_recovered_across_a_surviving_blank_line():
    # Vancouver writes the year as "1954;228:1451-5", never "(1954)". If flattening
    # evidence were parenthesised years only, one surviving blank line would split
    # this into two blocks that each look like a complete entry, and the recovery
    # would never run.
    text = (
        "1. Doll R, Hill AB. The mortality of doctors. BMJ. 1954;228:1451-5. "
        "2. Wynder EL. Tobacco and health. NEJM. 1961;264:1235-40. "
        "3. Peto R. Smoking and death. BMJ. 1994;309:937-9.\n\n"
        "4. Able A. A fourth study. Lancet. 2001;357:1191-4. "
        "5. Baker B. A fifth study. JAMA. 2005;293:2362-6. "
        "6. Chen C. A sixth study. BMJ. 2010;341:c4444."
    )

    entries = split_bibliography_block(text)

    assert len(entries) == 6
    assert entries[0].raw_text.startswith("Doll R")
    assert entries[5].raw_text.startswith("Chen C")


def test_inline_apa_splits_entries_that_end_in_a_bare_doi():
    # APA closes a DOI with no period, so requiring sentence-terminal punctuation
    # before an entry start would glue every DOI-final entry to the next one.
    text = (
        "Doe, J. (2020). A first article. Journal, 1(1), 1-10. https://doi.org/10.1000/abc123 "
        "Roe, R. (2019). A second article. Journal, 2(2), 20-30. https://doi.org/10.1000/def456 "
        "Young, Y. (2021). A third article. Journal, 3(2), 100-120. https://doi.org/10.1000/ghi789"
    )

    entries = split_bibliography_block(text)

    assert len(entries) == 3
    assert entries[1].raw_text.startswith("Roe, R.")


def test_inline_recovery_drops_a_leftover_heading_before_the_first_entry():
    # Text before the first start is kept (it's usually a corporate author), but a
    # leftover "References" heading is not a reference and must not reach the checker.
    text = "References 1. Doll R. First. BMJ. 1954. 2. Wynder EL. Second. NEJM. 1961. 3. Peto R. Third. BMJ. 1994."

    entries = split_bibliography_block(text)

    assert len(entries) == 3
    assert entries[0].raw_text.startswith("Doll R.")


def test_two_entry_numbered_fragment_is_recovered_when_the_lines_carry_words():
    # The tail of a numbered list whose earlier page was lost. What separates it from
    # the stray digit lines of a non-numbered bibliography is content, not run length.
    text = "14. Doll R. The mortality of doctors. BMJ. 1954.\n15. Wynder EL. Tobacco and health. NEJM. 1961."

    entries = split_bibliography_block(text)

    assert len(entries) == 2
    assert entries[1].raw_text.startswith("Wynder EL.")


def test_german_edition_numbers_do_not_trigger_inline_number_splitting():
    # "(1. Aufl.)" / "(2. Aufl.)" are ascending inline numbers in ordinary German
    # reference text. The blank-line structure is intact, so nothing should re-split
    # it — the project targets a German deployment, so this is a mainstream case.
    text = (
        "Müller, K. (2019). Einführung in die Statistik (1. Aufl.). Springer.\n\n"
        "Schmidt, H. (2020). Grundlagen der Psychologie (2. Aufl.). Beltz.\n\n"
        "Weber, L. (2021). Methoden der Forschung. Hogrefe."
    )

    entries = split_bibliography_block(text)

    assert len(entries) == 3
    assert entries[0].raw_text.startswith("Müller, K.")
    assert entries[2].raw_text.startswith("Weber, L.")


def test_line_numbered_bibliography_is_not_overridden_by_an_in_title_number():
    # Entry 4 contains "Chapter 5." — an inline continuation of the 1..4 run. The
    # line-based markers already split this correctly, so a heuristic that finds one
    # more "entry" must not win on count alone.
    text = (
        "1. Able A. First title. Journal. 2018.\n"
        "2. Baker B. Second title. Journal. 2019.\n"
        "3. Chen C. Third title. Journal. 2020.\n"
        "4. Rothman KJ. Modern Epidemiology, Chapter 5. Precision and statistics. Lippincott; 2008."
    )

    entries = split_bibliography_block(text)

    assert len(entries) == 4
    assert entries[3].raw_text.startswith("Rothman KJ.")
    assert "Precision and statistics" in entries[3].raw_text


def test_inline_apa_keeps_a_three_editor_list_inside_its_entry():
    # The middle editor ("Jones, C. D.") follows a comma, not "In"/"&", so neither the
    # connector guard nor the year gate rejects it — only the entry-boundary rule does.
    text = (
        "Baker, S. U. (2020). A chapter on sleep. In Smith, A. B., Jones, C. D., & Brown, E. F. (Eds.), "
        "The handbook (pp. 1-20). Press. "
        "Carter, V. W. (2021). Another article. Journal, 2, 20-30. "
        "Young, Y. (2022). A third. Journal, 3, 3-9."
    )

    entries = split_bibliography_block(text)

    assert len(entries) == 3
    assert "Jones, C. D." in entries[0].raw_text
    assert entries[1].raw_text.startswith("Carter, V. W.")


def test_inline_apa_does_not_split_at_a_publisher_location():
    # "Hillsdale, N.J.:" has the "Surname, I." shape and sits after the entry's year,
    # so the year gate accepts it; the initial running into a colon is what marks it
    # as a state abbreviation.
    text = (
        "Cohen, J. (1988). Statistical power analysis (2nd ed.). Hillsdale, N.J.: Lawrence Erlbaum Associates. "
        "Carter, V. W. (2021). Another article. Journal, 2, 20-30. "
        "Young, Y. (2022). A third. Journal, 3, 3-9."
    )

    entries = split_bibliography_block(text)

    assert len(entries) == 3
    assert "Lawrence Erlbaum" in entries[0].raw_text


def test_inline_apa_recovery_keeps_a_leading_corporate_author_entry():
    # A corporate author opens with neither "Surname, I." nor a number, so it precedes
    # every candidate start. Dropping that slice loses a reference outright.
    text = (
        "World Health Organization. (2020). Global report on health. WHO. "
        "Doe, J. (2019). An article title. Journal, 1, 1-10. "
        "Roe, R. (2021). Another article title. Journal, 2, 11-20."
    )

    entries = split_bibliography_block(text)

    assert len(entries) == 3
    assert entries[0].raw_text.startswith("World Health Organization.")


def test_dot_numbered_entries_recovered_when_first_marker_is_missing():
    # A page-break merge upstream can absorb the "1." marker. The remaining run is
    # still an unambiguous numbered bibliography, so it must not fall through to the
    # weaker heuristics just because it no longer starts at 1.
    text = (
        "2. Roe R. Second title. Journal. 2019.\n"
        "3. Young Y. Third title. Journal. 2020.\n"
        "4. Able A. Fourth title. Journal. 2021."
    )

    entries = split_bibliography_block(text)

    assert len(entries) == 3
    assert entries[0].raw_text.startswith("Roe R.")


def test_short_unanchored_number_run_is_not_treated_as_a_numbered_bibliography():
    # Two consecutive digit lines in the middle of an APA bibliography (wrapped page
    # ranges/years) are the case the start-at-1 requirement exists to reject.
    text = "Doe, J. (2020). A title. Journal, 1, 1-10.\n7. 2019.\n8. 2020."

    assert len(split_bibliography_block(text)) == 1


def test_sparse_inline_apa_matches_do_not_override_more_complete_blank_blocks():
    text = (
        "Doe, J. (2020). A first title.\n\n"
        "unusual but complete second reference\n\n"
        "unusual but complete third reference\n\n"
        "unusual but complete fourth reference\n\n"
        "Roe, D. (2021). A fifth title."
    )

    entries = split_bibliography_block(text)

    assert len(entries) == 5


def test_jss_style_fallback_all_caps_initials_no_comma():
    text = (
        "Alexandrov T, Decker J, Bischoff FR (2009). Metabolomic and proteomic\n"
        "compass for plant metabolism. Bioinformatics.\n"
        "Cook R (1977). Detection of influential observation in linear regression. Technometrics 19, 15-18."
    )
    entries = split_bibliography_block(text)
    assert len(entries) == 2
    assert entries[0].raw_text.startswith("Alexandrov T")
    assert entries[1].raw_text.startswith("Cook R")


def test_unsplittable_block_returns_single_entry():
    text = "this is not a recognisable reference list format at all"
    entries = split_bibliography_block(text)
    assert len(entries) == 1
    assert entries[0].raw_text == text


def test_empty_input_returns_no_entries():
    assert split_bibliography_block("") == []


# --- flattening evidence -------------------------------------------------------
#
# Each recovery heuristic is licensed by named evidence rather than by a single
# boolean. These tests pin which signals a given text shows, because the pairing is
# the whole point: a removal experiment found that the bare-year signal was licensing
# inline-APA recovery on text where that recovery can only be wrong, and downstream
# guards were closing a gate that should never have opened. That was invisible while
# all three signals sat in one any().


def test_flattening_evidence_names_paren_years_for_a_flattened_apa_list():
    entry = (
        "Doe, J. (2020). A first article title. Journal of Examples, 1(1), 1-10. "
        "Roe, R. (2019). A second article title. Journal of Methods, 2(1), 20-30."
    )

    assert _flattening_evidence([entry]) == {Flattening.PAREN_YEARS}


def test_flattening_evidence_names_the_number_run_for_a_flattened_numbered_list():
    entry = "1. Doll R. First title. BMJ. 2. Hill AB. Second title. BMJ. 3. Wynder EL. Third title. JAMA."

    assert Flattening.INLINE_NUMBER_RUN in _flattening_evidence([entry])


def test_a_reprint_note_shows_only_bare_years_so_it_cannot_license_apa_recovery():
    """The case that made the shadowing visible.

    An intact entry quoting several years — a reprint note — trips the bare-year
    signal and nothing else. Bare years are dense in numbered and comma-year styles
    and say nothing about APA anchors, so this must not open the inline-APA gate; that
    it currently produces no over-split is the downstream guards' doing, not this
    signal's.
    """
    entry = "Doe, J. (2020). A title. Journal, 1, 1-10. (Original work published 1890; reprinted 1954, 1971.)"

    assert _flattening_evidence([entry]) == {Flattening.BARE_YEARS}


def test_an_intact_entry_shows_no_evidence_at_all():
    entries = [
        "Doe, J. (2020). A first article title. Journal of Examples, 1(1), 1-10.",
        "Roe, R. (2019). A chapter about things. In Smith, A. B. (Ed.), The handbook (pp. 30-55). Academic Press.",
    ]

    assert _flattening_evidence(entries) == set()
