"""The reference list checked against the list the document printed.

Every test here builds the extracted list by hand rather than by extracting anything,
because the failures being modelled are extractor failures: a dropped entry, a merge, a
split. Those are hard to provoke deliberately and easy to state directly, and stating them
directly is also what keeps this module's assertions about *this* project's behaviour
rather than about GROBID's, which moves with its version.

The live counterpart is tests/test_tier1_grobid_live.py, which runs the same audit over
output GROBID produced itself.
"""

from __future__ import annotations

import pytest

from openrefcheck.extraction.citation_matching import MatchStatus, match_citations
from openrefcheck.extraction.document_artifact import DocumentArtifact
from openrefcheck.extraction.reference_list_audit import NOT_AUDITED, audit_reference_list
from openrefcheck.extraction.tier0 import RawReferenceEntry

NUMBERED_BIBLIOGRAPHY = """\
[1] C. E. Shannon, "A mathematical theory of communication," Bell System Technical Journal, vol. 27, 1948.
[2] A. M. Turing, "Computing machinery and intelligence," Mind, vol. 59, no. 236, 1950.
[3] A. Vaswani et al., "Attention is all you need," in Advances in Neural Information Processing Systems, 2017.
[4] J. Pearl, Causality: Models, Reasoning and Inference. Cambridge University Press, 2009.
"""

AUTHOR_DATE_BIBLIOGRAPHY = """\
Arendt, Hannah. 1958. The Human Condition. Chicago, IL: University of Chicago Press.

Kuhn, Thomas S. 1962. The Structure of Scientific Revolutions. Chicago, IL: University of Chicago Press.

Ricoeur, Paul. 1969. The Symbolism of Evil. Boston, MA: Beacon Press.
"""


def _entries(*raw_texts: str) -> list[RawReferenceEntry]:
    return [RawReferenceEntry(i, text) for i, text in enumerate(raw_texts, start=1)]


def _numbered_entries(*numbers: int) -> list[RawReferenceEntry]:
    """The extracted list for `NUMBERED_BIBLIOGRAPHY`, keeping only the entries named.

    Built with the printed marker stripped, which is what makes this a fair model of the
    Tier 1 path: GROBID returns no printed number on either of its strings, so an entry
    that knows its own number is exactly what this fixture must not hand the audit.
    """
    printed = {
        number: text.split("] ", 1)[1]
        for number, text in enumerate(NUMBERED_BIBLIOGRAPHY.strip().splitlines(), start=1)
    }
    return [RawReferenceEntry(i, printed[n]) for i, n in enumerate(numbers, start=1)]


# --------------------------------------------------------------------------------------
# Reading the printed numbers back
# --------------------------------------------------------------------------------------


def test_a_whole_numbered_list_gets_its_own_numbers_back():
    references = _numbered_entries(1, 2, 3, 4)

    audit = audit_reference_list(references, NUMBERED_BIBLIOGRAPHY)

    assert audit.numbered and audit.printed_count == 4
    assert audit.complete
    assert audit.by_printed_number == {1: 1, 2: 2, 3: 3, 4: 4}


def test_a_dropped_entry_does_not_shift_the_numbers_after_it():
    """The positional off-by-one, which is the defect this whole module exists to remove.

    With the second entry gone, the entry sitting in position 2 is the one the page prints
    as [3]. Reading the numbers off the page rather than counting positions is what lets
    it say so — and the entry that vanished is named rather than silently absorbed.
    """
    references = _numbered_entries(1, 3, 4)

    audit = audit_reference_list(references, NUMBERED_BIBLIOGRAPHY)

    assert audit.by_printed_number == {1: 1, 3: 2, 4: 3}
    assert audit.missing == (2,)
    assert not audit.complete


def test_a_marker_resolves_to_the_entry_the_page_numbers_rather_than_the_one_in_that_position():
    """The same thing one layer up, where it is visible to a reviewer.

    Without the audit, "[3]" against a three-entry list resolves through position and lands
    on Vaswani — a citation silently attributed to the wrong work, which is the one failure
    this feature is least able to have a reviewer catch.
    """
    references = _numbered_entries(1, 3, 4)
    audit = audit_reference_list(references, NUMBERED_BIBLIOGRAPHY)
    artifact = DocumentArtifact.from_lines(["The result is well known [3]."], raw_text="", parser="test")

    (match,) = match_citations(artifact, references, audit=audit)

    assert match.status is MatchStatus.RESOLVED
    assert match.reference_n == 2
    # Read off the page, so it is not the hedged answer position would have earned.
    assert match.confidence == 1.0


def test_an_entry_that_absorbed_its_neighbour_answers_to_both_numbers():
    """A merge is not a hole. The entry does carry both works, so both markers name it —
    while the merge itself is still reported, so nothing rests on the counts being right."""
    references = _numbered_entries(1, 2, 4)
    references[1].raw_text += " " + NUMBERED_BIBLIOGRAPHY.splitlines()[2].split("] ", 1)[1]

    audit = audit_reference_list(references, NUMBERED_BIBLIOGRAPHY)

    assert audit.by_printed_number == {1: 1, 2: 2, 3: 2, 4: 3}
    assert audit.merged == (2,)
    assert audit.missing == ()


def test_a_split_entry_does_not_take_the_printed_map_down_with_it():
    """PR #58's review (Codex, GPT-5.6 Sol). The audit leaves a fragment matching no printed
    entry, and `_reference_index` used to read that empty slot as a hole and abandon the
    whole map — reintroducing the exact positional shift the audit exists to remove.

    Printed [1] Shannon, [2] Turing, [3] Vaswani; extraction splits Turing in two, so the
    fragment sits in position 3 and Vaswani in position 4. "[3]" must reach Vaswani. The
    fragment is a finding in `unmatched`, not a gap in the map: the map is built by walking
    the printed list, so every printed number is either in it or in `missing`.
    """
    references = _entries(
        'C. E. Shannon, "A mathematical theory of communication," Bell System Technical Journal, vol. 27, 1948.',
        'A. M. Turing, "Computing machinery and intelligence,"',
        "Mind, vol. 59, no. 236, 1950. Reprinted in Collected Works.",
        'A. Vaswani et al., "Attention is all you need," in Advances in Neural Information Processing Systems, 2017.',
    )
    printed = "\n".join(NUMBERED_BIBLIOGRAPHY.strip().splitlines()[:3]) + "\n"
    audit = audit_reference_list(references, printed)
    artifact = DocumentArtifact.from_lines(["Attention matters [3]."], raw_text="", parser="test")

    assert audit.unmatched == (3,)
    assert audit.by_printed_number == {1: 1, 2: 2, 3: 4}

    (match,) = match_citations(artifact, references, audit=audit)

    assert match.status is MatchStatus.RESOLVED
    assert match.reference_n == 4
    assert match.confidence == 1.0


def test_a_marker_citing_an_entry_extraction_lost_is_not_called_an_orphan():
    """Found while fixing the review's finding, and the same shape one step further on.

    Reading the numbers off the page makes the map authoritative about which entry each
    number means — but not about which numbers exist, because the audit also knows that
    printed [2] produced no entry. A marker citing it names a reference the document really
    does list, so ORPHANED would accuse the manuscript of this project's own miss.
    "Cannot tell" is the honest answer, and it is what `_ReferenceIndex.exhaustive` carries.
    """
    references = _numbered_entries(1, 3, 4)
    audit = audit_reference_list(references, NUMBERED_BIBLIOGRAPHY)
    artifact = DocumentArtifact.from_lines(["As shown before [2]."], raw_text="", parser="test")

    (match,) = match_citations(artifact, references, audit=audit)

    assert match.status is MatchStatus.UNRESOLVED
    assert match.reference_n is None


def test_a_whole_numbered_list_still_reports_a_number_it_does_not_carry_as_an_orphan():
    """The other side of that, which the fix must not flatten. Where nothing is missing, a
    marker past the end of the list is a real finding and stays one — otherwise closing the
    false accusation above would have cost the true one."""
    references = _numbered_entries(1, 2, 3, 4)
    audit = audit_reference_list(references, NUMBERED_BIBLIOGRAPHY)
    artifact = DocumentArtifact.from_lines(["See also [9]."], raw_text="", parser="test")

    (match,) = match_citations(artifact, references, audit=audit)

    assert match.status is MatchStatus.ORPHANED


def test_an_unnumbered_list_yields_no_numbers_and_no_total():
    """The Tier 0 splitter's count is an opinion, and this module does not report opinions
    as totals — on the project's own Chicago fixture that opinion is wrong by one."""
    references = _entries(
        "Arendt, Hannah. 1958. The Human Condition. Chicago, IL: University of Chicago Press.",
        "Kuhn, Thomas S. 1962. The Structure of Scientific Revolutions. Chicago, IL: University of Chicago Press.",
        "Ricoeur, Paul. 1969. The Symbolism of Evil. Boston, MA: Beacon Press.",
    )

    audit = audit_reference_list(references, AUTHOR_DATE_BIBLIOGRAPHY)

    assert audit.read and not audit.numbered
    assert audit.printed_count is None
    assert audit.by_printed_number == {}
    assert audit.complete


# --------------------------------------------------------------------------------------
# The three shapes of discrepancy
# --------------------------------------------------------------------------------------


def test_an_entry_covering_two_printed_entries_is_reported_as_merged():
    references = _entries(
        "Arendt, Hannah. 1958. The Human Condition. Chicago, IL: University of Chicago Press. "
        "Kuhn, Thomas S. 1962. The Structure of Scientific Revolutions. Chicago, IL: University of Chicago Press.",
        "Ricoeur, Paul. 1969. The Symbolism of Evil. Boston, MA: Beacon Press.",
    )

    audit = audit_reference_list(references, AUTHOR_DATE_BIBLIOGRAPHY)

    assert audit.merged == (1,)
    assert not audit.complete


def test_a_fragment_of_an_entry_is_reported_as_matching_nothing():
    """The other half of a split. The complete half keeps the printed entry, because ties
    go to the earlier entry — so what is left over is the fragment, which is the half worth
    telling a reviewer about."""
    references = _entries(
        "Arendt, Hannah. 1958. The Human Condition. Chicago, IL: University of Chicago Press.",
        "Kuhn, Thomas S. 1962. The Structure of Scientific Revolutions.",
        "Chicago, IL: University of Chicago Press. Reprinted with a new postscript.",
        "Ricoeur, Paul. 1969. The Symbolism of Evil. Boston, MA: Beacon Press.",
    )

    audit = audit_reference_list(references, AUTHOR_DATE_BIBLIOGRAPHY)

    assert audit.unmatched == (3,)


def test_a_printed_entry_nothing_covers_is_reported_as_missing():
    references = _entries(
        "Arendt, Hannah. 1958. The Human Condition. Chicago, IL: University of Chicago Press.",
        "Ricoeur, Paul. 1969. The Symbolism of Evil. Boston, MA: Beacon Press.",
    )

    audit = audit_reference_list(references, AUTHOR_DATE_BIBLIOGRAPHY)

    assert len(audit.missing) == 1
    assert not audit.complete


# --------------------------------------------------------------------------------------
# What it refuses to say
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("text", [None, "", "   \n  "])
def test_no_bibliography_text_is_no_evidence_rather_than_a_clean_bill(text):
    """`complete` is False on no evidence as well as on bad evidence, and `read` is what
    tells the two apart. A caller that only asks "is it complete?" must never be told yes
    because nothing was checked."""
    audit = audit_reference_list(_entries("Arendt, Hannah. 1958. The Human Condition."), text)

    assert audit is NOT_AUDITED
    assert not audit.read and not audit.complete


def test_a_single_numbered_entry_is_not_treated_as_a_numbered_list():
    """One "1." at the head of a section is as likely to be an enumerated note, and one
    entry cannot corroborate itself. Falling back to the unnumbered reading is what keeps
    the audit from reporting a printed total it read off a single line."""
    audit = audit_reference_list(
        _entries("Shannon, C. E. A mathematical theory of communication. Bell System Technical Journal, 1948."),
        '1. C. E. Shannon, "A mathematical theory of communication," Bell System Technical Journal, 1948.\n',
    )

    assert not audit.numbered
    assert audit.printed_count is None


def test_a_wrapped_page_range_does_not_make_an_author_date_list_look_numbered():
    """A justified bibliography whose page range wraps onto its own line leaves a bare
    "246." that is marker-shaped. One of those must not turn an unnumbered list into a
    numbered one, which would attach printed numbers nothing on the page means."""
    wrapped = (
        "Arendt, Hannah. 1958. The Human Condition. Chicago, IL: University of Chicago Press, 238-\n"
        "246.\n\n"
        "Kuhn, Thomas S. 1962. The Structure of Scientific Revolutions. Chicago, IL: University of Chicago Press.\n"
    )

    audit = audit_reference_list(
        _entries(
            "Arendt, Hannah. 1958. The Human Condition. Chicago, IL: University of Chicago Press, 238-246.",
            "Kuhn, Thomas S. 1962. The Structure of Scientific Revolutions. Chicago, IL: University of Chicago Press.",
        ),
        wrapped,
    )

    assert not audit.numbered


def test_a_word_the_two_readings_broke_differently_still_counts_as_present():
    """The measured false alarm this rescue exists for, in the direction it was measured.

    The corpus's "Röntgen" reaches GROBID intact and comes out of the PDF text layer as a
    bare diaeresis followed by the rest of the word, so the printed reading has "r" and
    "ontgen" where the extracted one has "rontgen". Four of nineteen tokens differ that
    way in the one entry, which is enough for a word-set comparison alone to call a
    correctly extracted entry missing.
    """
    printed = (
        "1. R¨ontgen WC. ¨Uber eine neue Art von Strahlen. "
        "Sitzungsberichte der W¨urzburger Physikalisch-Medicinischen Gesellschaft 1895:132-41.\n"
        "2. Doll R, Hill AB. Smoking and carcinoma of the lung. British Medical Journal 1950;2:739-48.\n"
    )
    references = _entries(
        "Röntgen WC. Über eine neue Art von Strahlen. "
        "Sitzungsberichte der Würzburger Physikalisch-Medicinischen Gesellschaft 1895:132-41.",
        "Doll R, Hill AB. Smoking and carcinoma of the lung. British Medical Journal 1950;2:739-48.",
    )

    audit = audit_reference_list(references, printed)

    assert audit.complete
    assert audit.by_printed_number == {1: 1, 2: 2}
