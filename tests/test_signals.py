"""The shared vocabulary in extraction/signals.py.

These are definition tests, not behaviour tests, and deliberately so. The defect they
cover — tier0 and title.py each defining `_YEAR_PAREN_RE`, same name, different
meaning — has no observable consequence today: tier0's looser version reads Vancouver's
"1954;2(4682):1451" as carrying a publication year, but every path that opens on that
signal is then closed again by a downstream guard, so the corpus cannot see it. That
makes it a trap rather than a bug, and the thing worth pinning is the definition.
"""

import pytest

from openrefcheck.extraction.signals import BARE_YEAR_RE, YEAR_PAREN_RE, entry_is_complete


@pytest.mark.parametrize(
    "text",
    [
        "Smith, J. (2020). A title.",
        "Roe, R. (2024a). A title.",
        "Doe, J. (2021, October 19). A title.",
    ],
)
def test_year_paren_matches_a_publication_year(text):
    assert YEAR_PAREN_RE.search(text)


@pytest.mark.parametrize(
    "text",
    [
        "Doll R, Hill AB. Smoking. BMJ. 1954;2(4682):1451-1455.",  # volume(issue)
        "Journal of Examples, 31(4682), 400-415.",
        "A report (1234) with no plausible year.",
    ],
)
def test_year_paren_rejects_a_number_that_is_not_a_year(text):
    assert not YEAR_PAREN_RE.search(text)


def test_bare_year_does_not_match_inside_a_longer_number():
    assert not BARE_YEAR_RE.search("10.1136/bmj.20200101")
    assert BARE_YEAR_RE.search("Retrieved 2019 from somewhere")


@pytest.mark.parametrize(
    "text",
    [
        "A title. Journal of Examples, 1(1), 1-10.",
        'A quoted ending."',
        "Smith, J. (2020). A title. https://doi.org/10.1000/xyz123",
        "Roe, R. (2019). A title. doi:10.1000/abc",
    ],
)
def test_entry_is_complete_accepts_both_endings(text):
    """Sentence-terminal punctuation and a trailing DOI/URL are both real endings.

    Treating only the first as an ending is what let a DOI-final entry be merged into
    the reference after it, deleting one; the two are not alternatives a caller may
    pick between.
    """
    assert entry_is_complete(text)


@pytest.mark.parametrize(
    "text",
    [
        "Smith, A. B., Jones, C. D., & Brown,",
        "requirements for accurate estimation of",
        "Vol. 1. Theoretical models and",
    ],
)
def test_entry_is_complete_rejects_a_cut_off_line(text):
    assert not entry_is_complete(text)
