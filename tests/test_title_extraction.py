from refcheck.extraction.title import extract_title


def test_apa_style_year_parenthetical():
    raw = (
        "Kahneman, D., & Tversky, A. (1979). Prospect theory: An analysis of decision "
        "under risk. Econometrica, 47(2), 263-291."
    )
    assert extract_title(raw) == "Prospect theory: An analysis of decision under risk"


def test_apa_style_disambiguated_year_suffix():
    raw = "Ricoeur, P. (1969a). The symbolism of evil. Beacon Press."
    assert extract_title(raw) == "The symbolism of evil"


def test_ieee_style_quoted_title():
    raw = (
        'A. Vaswani et al., "Attention is all you need," in Advances in Neural '
        "Information Processing Systems, vol. 30, 2017."
    )
    assert extract_title(raw) == "Attention is all you need"


def test_vancouver_style_author_initials():
    raw = "Doll R, Hill AB. Smoking and carcinoma of the lung. Br Med J. 1950;2(4682):739-748."
    assert extract_title(raw) == "Smoking and carcinoma of the lung"


def test_vancouver_style_truncated_with_et_al():
    raw = "Reed W, Carroll J, Agramonte A, et al. The etiology of yellow fever. Public Health Pap Rep. 1900;26:37-53."
    assert extract_title(raw) == "The etiology of yellow fever"


def test_vancouver_style_with_lowercase_surname_particle():
    raw = "Galbiati R, van der Weele J. Sanctions that signal: An experiment. Journal. 2013;94:34-51."

    assert extract_title(raw) == "Sanctions that signal: An experiment"


def test_elsevier_style_comma_year():
    raw = "Aitchison, J., Greenacre, M. J., 2002. Biplots for compositional data. Journal, 51, 375-392."

    assert extract_title(raw) == "Biplots for compositional data"


def test_elsevier_style_comma_year_with_corporate_author():
    raw = "World Health Organization, 2020. Global tuberculosis report 2020. WHO, Geneva."

    assert extract_title(raw) == "Global tuberculosis report 2020"


def test_comma_year_ending_a_title_is_not_mistaken_for_an_author_year_block():
    # "369 diseases, 2019." is the end of the title, not an Elsevier author-year block,
    # so what follows is journal metadata. Returning None lets the caller fall back to
    # the raw text instead of reporting "Lancet 396, 1204-1222." as the title.
    raw = "GBD 2019 Collaborators. Global burden of 369 diseases, 2019. Lancet 396, 1204-1222."

    assert extract_title(raw) is None


def test_apa_style_title_with_embedded_quotes_not_mistaken_for_ieee():
    raw = 'Smith, J. (2010). The "Hawthorne effect" revisited. Journal of Applied Psychology, 5(1), 1-10.'
    assert extract_title(raw) == 'The "Hawthorne effect" revisited'


def test_comma_year_rule_ignores_article_id_after_the_real_title_sentence():
    # Before the fix, this returned "doi:10.4137/cin.s30747." — the comma-year rule
    # matched "S30747, 2015." (an article-id token that looks like "Word, YYYY.") deep
    # in the journal/volume metadata, well after the real title had already ended its
    # own period-terminated sentence ("...research."). Confirmed against the pre-fix
    # extract_title on this exact string.
    raw = (
        "Boulesteix, A.-L., Stierle, V., and Hapfelmeier, A. Publication bias in "
        "methodological computational research. Cancer Informatics , 14s5:CIN.S30747, "
        "2015. doi:10.4137/cin.s30747."
    )
    assert extract_title(raw) is None


def test_comma_year_rule_ignores_publisher_name_after_the_real_title_sentence():
    # Before the fix, this returned "ISBN 9781107664647" — "Sons, 2018."-shaped tokens
    # (here "Press, 2018.") false-matched the same way. Confirmed against the pre-fix
    # extract_title on this exact string.
    raw = (
        "Mayo, D. G. Statistical Inference as Severe Testing: How to Get Beyond the "
        "Statistics Wars . Cambridge University Press, 2018. ISBN 9781107664647. "
        "doi:10.1017/9781107286184."
    )
    assert extract_title(raw) is None


def test_comma_year_rule_survives_an_abbreviated_corporate_author():
    # Before the "no earlier real sentence break" guard was refined, this returned
    # None instead of the title: the guard's forward-only check ("is the next word a
    # real word?") false-flagged "U.S. Department" as a genuine sentence break, since
    # "Department" passes that check on its own — even though "U.S." is an
    # abbreviation, not a sentence end, and the real author-year block ("Health,
    # 2020.") comes later. Flagged in PR #45 review. Confirmed against the
    # unrefined guard on this exact string.
    raw = "U.S. Department of Health, 2020. Public health report. Government Press."
    assert extract_title(raw) == "Public health report"


def test_unrecognized_style_returns_none():
    raw = "some unstructured text that matches none of the known citation patterns"
    assert extract_title(raw) is None
