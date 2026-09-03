"""Qualitative regression tests for compute_style_profile.

Reuses the same per-style fixture corpus as test_citation_styles.py (see
citation_style_corpus.py for the loader) rather than writing new fixtures, so this
module's expectations stay grounded in the same real citation-style text everything
else in the corpus is checked against.

compute_style_profile is pure signal aggregation with no classification, so these
tests only assert the qualitative direction each fixture file's name implies (e.g.
"apa7.json's cases show a nonzero paren_year_matches count") rather than exact counts,
which would be brittle and beside the point of an evidence-gathering module.
"""

from __future__ import annotations

from citation_style_corpus import load_styles
from openrefcheck.extraction.style_profile import StyleProfile, compute_style_profile

STYLES = load_styles()


def _case_text(case: dict) -> str:
    """The raw text a case carries, whichever layer it belongs to.

    Split/section/normalize-layer cases carry "text"; title-layer cases carry "raw".
    """
    return case["text"] if "text" in case else case["raw"]


def _style_text(style_key: str) -> str:
    """Concatenate every case's raw text for one style file into one block."""
    return "\n\n".join(_case_text(case) for case in STYLES[style_key]["cases"])


def test_apa7_shows_parenthesised_years():
    profile = compute_style_profile(_style_text("apa7"))
    assert profile.paren_year_matches > 0


def test_apa7_bare_year_density_stays_low():
    # Regression guard: bare_year_density must not just re-count every YEAR_PAREN_RE
    # year a second time. Before excluding parenthesised/comma-slotted years, this
    # fixture's density was 1.0 -- indistinguishable from ieee.json's own 1.0, which
    # defeats the point of a signal meant to separate APA from Vancouver/IEEE.
    profile = compute_style_profile(_style_text("apa7"))
    assert profile.bare_year_density < 0.6


def test_german_apa_bare_year_density_stays_low():
    profile = compute_style_profile(_style_text("german_apa"))
    assert profile.bare_year_density < 0.6


def test_elsevier_bare_year_density_stays_low():
    # Before the fix this fixture's density was 1.5 -- denser than vancouver.json's
    # own 1.22, i.e. worse than useless as a distinguishing signal.
    profile = compute_style_profile(_style_text("elsevier"))
    assert profile.bare_year_density < 0.6


def test_german_apa_shows_german_markers():
    profile = compute_style_profile(_style_text("german_apa"))
    assert profile.german_markers > 0


def test_vancouver_shows_no_parenthesised_years_but_bare_years():
    profile = compute_style_profile(_style_text("vancouver"))
    assert profile.paren_year_matches == 0
    assert profile.bare_year_density > 0


def test_ieee_shows_no_parenthesised_years_but_bare_years():
    profile = compute_style_profile(_style_text("ieee"))
    assert profile.paren_year_matches == 0
    assert profile.bare_year_density > 0


def test_ieee_shows_quoted_titles():
    profile = compute_style_profile(_style_text("ieee"))
    assert profile.quoted_titles > 0


def test_jss_shows_jss_author_lines():
    profile = compute_style_profile(_style_text("jss"))
    assert profile.jss_author_lines > 0


def test_elsevier_shows_comma_year_matches():
    profile = compute_style_profile(_style_text("elsevier"))
    assert profile.comma_year_matches > 0


def test_numbered_shows_no_parenthesised_years_but_bare_years():
    # numbered.json's one case is a flattened numbered list (markers sit mid-line,
    # not at a true line start, since the fixture text has no newlines at all), so
    # bracket/dot_numbered_lines can't fire here — the qualitative signal this style
    # does carry is the same one as Vancouver/IEEE: bare years, no parenthesised ones.
    profile = compute_style_profile(_style_text("numbered"))
    assert profile.paren_year_matches == 0
    assert profile.bare_year_density > 0


def test_document_structure_runs_without_error():
    # This style file exercises section-boundary/normalize behaviour, not a
    # particular citation style's markers, so there is no qualitative signal to
    # assert here beyond "the profile can be computed over its text at all".
    profile = compute_style_profile(_style_text("document_structure"))
    assert isinstance(profile, StyleProfile)


def test_empty_text_gives_all_zero_fields_with_no_division_by_zero():
    profile = compute_style_profile("")

    assert profile == StyleProfile(
        paren_year_matches=0,
        comma_year_matches=0,
        bare_year_density=0.0,
        bracket_numbered_lines=0,
        dot_numbered_lines=0,
        quoted_titles=0,
        jss_author_lines=0,
        german_markers=0,
    )
