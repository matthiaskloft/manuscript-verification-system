"""What a reviewer may be told about how complete the reference list is.

The companion to `citation_display`, and separate from it for the same two reasons that
one exists: the References screen and the exported report must say this identically, and a
judgement made inside a NiceGUI `render()` is untested by construction.

Separate *from* it because the subject is different. `citation_display` withholds claims
about which references a manuscript cites; this module withholds claims about whether the
list being counted is the list the manuscript printed. That distinction is the point — the
note produced here qualifies every figure the other module produces, so it must not read
as one of them.

The wording rule throughout: name what was observed, not what it implies about the author.
A merged entry, a fragment and a missing entry are all this project's extraction falling
short of the page, and none of them is something the manuscript did wrong. `refcheck`'s
whole argument is that a finding needs evidence; a reference list this project could not
read is evidence about the reading.
"""

from __future__ import annotations

from dataclasses import dataclass

from refcheck.extraction.reference_list_audit import ReferenceListAudit

# Longest run of entry numbers written out before the note stops listing them. A reviewer
# can act on "references 4, 9 and 17"; past that the list stops being a pointer and starts
# being the paragraph, and the count is the part that still means something.
_MAX_NUMBERS_LISTED = 6


@dataclass(frozen=True)
class ReferenceListNote:
    """One statement about the extracted list's completeness, or nothing to say.

    `complete` is True only where the list was checked and matched. It is not the negation
    of `headline` being set: a list nothing could check produces no note at all, and the
    screen showing nothing there means "not checked", never "checked and fine". That is
    the same distinction `ReferenceListAudit.read` draws, carried as far as the wording so
    a caller cannot collapse it by accident.
    """

    headline: str = ""
    detail: str = ""
    complete: bool = False

    def __bool__(self) -> bool:
        return bool(self.headline)


def reference_list_note(audit: ReferenceListAudit, extracted_count: int) -> ReferenceListNote:
    """What to say about a reference list, given how it compared to the printed one.

    Returns an empty note where the comparison did not happen — a DOCX, a document with no
    locatable bibliography, a check that read no body. Saying "could not verify the
    reference list" on every one of those would train a reviewer to ignore the line by the
    time it means something, and the absence of a note is not a claim.

    `extracted_count` is passed rather than read off the audit, which deliberately holds no
    count of its own: the number of references is a property of the list the caller is
    displaying, and two sources for it is one too many.
    """
    if not audit.read:
        return ReferenceListNote()
    if audit.complete:
        return ReferenceListNote(
            headline=f"All {extracted_count} references match the list this document prints.",
            complete=True,
        )

    findings = [
        text
        for text in (
            _missing(audit),
            _merged(audit),
            _unmatched(audit),
        )
        if text
    ]
    return ReferenceListNote(
        headline=_headline(audit, extracted_count),
        detail="; ".join(findings) + ".",
    )


def _headline(audit: ReferenceListAudit, extracted_count: int) -> str:
    """The one line that has to carry, and it says the list may be wrong before why.

    A number appears only where the list numbers itself, because only there was the total
    read off the page rather than counted by a heuristic that is itself wrong by one on
    this project's own Chicago fixture. Elsewhere the honest headline has no total in it.
    """
    if audit.printed_count is not None and audit.printed_count != extracted_count:
        return (
            f"This document's reference list numbers {audit.printed_count} entries, "
            f"but {extracted_count} were extracted."
        )
    return "The extracted reference list does not match the list this document prints."


def _missing(audit: ReferenceListAudit) -> str:
    if not audit.missing:
        return ""
    count = len(audit.missing)
    entries = "entry" if count == 1 else "entries"
    where = _numbers(audit.missing) if audit.numbered else ""
    tail = f" ({where})" if where else ""
    return f"{count} printed {entries} did not turn up in the extracted list{tail}"


def _merged(audit: ReferenceListAudit) -> str:
    if not audit.merged:
        return ""
    which = _numbers(audit.merged)
    verb = "covers" if len(audit.merged) == 1 else "cover"
    return f"reference {which} {verb} more than one printed entry, so its citation counts are combined"


def _unmatched(audit: ReferenceListAudit) -> str:
    if not audit.unmatched:
        return ""
    which = _numbers(audit.unmatched)
    verb = "matches" if len(audit.unmatched) == 1 else "match"
    return f"reference {which} {verb} no printed entry, and may be a fragment of the one above"


def _numbers(numbers: tuple[int, ...]) -> str:
    """A short, readable run of entry numbers, truncated rather than wrapped.

    Truncation keeps the count honest by stating it: "4, 9, 17 and 5 more" is still a true
    sentence about a list the reader is not being shown all of.
    """
    shown = [str(number) for number in numbers[:_MAX_NUMBERS_LISTED]]
    rest = len(numbers) - len(shown)
    if rest > 0:
        shown.append(f"{rest} more")
    if len(shown) == 1:
        return shown[0]
    return ", ".join(shown[:-1]) + " and " + shown[-1]
