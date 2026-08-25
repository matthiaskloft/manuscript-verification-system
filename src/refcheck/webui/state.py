"""Per-browser-tab application state — the NiceGUI analogue of MainWindow's instance
attributes in the old PySide6 app. One AppState is created per connected client.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field

from refcheck.extraction.citation_matching import CitationMatch
from refcheck.extraction.document_artifact import DocumentArtifact
from refcheck.extraction.reference_list_audit import NOT_AUDITED, ReferenceListAudit
from refcheck.extraction.engine_status import ENGINE_AUTO
from refcheck.gui.file_info import LoadedFile
from refcheck.gui.models import ReferenceResult
from refcheck.gui.real_pipeline import CITATIONS_NOT_RUN
from refcheck.gui.report_builder import DEFAULT_EXPORT_INCLUDED
from refcheck.gui.sidebar_copy import configured_mode

SCREEN_ORDER = ["upload", "refs", "review", "summary", "export"]


@dataclass
class AppState:
    mode: str = field(default_factory=configured_mode)
    screen: str = "upload"

    # Upload / processing
    loaded: LoadedFile | None = None
    engine_preference: str = ENGINE_AUTO
    running: bool = False
    stage_index: int = 0
    done: int = 0
    total: int = 0
    cancel_requested: bool = False

    # Results
    results: list[ReferenceResult] = field(default_factory=list)
    decisions: dict[int, dict[str, str]] = field(default_factory=dict)
    review_originals: dict[int, ReferenceResult] = field(default_factory=dict)

    # In-text citations (docs/plans/plan-in-text-citation-parsing.md). All three are
    # session-scoped and cleared on every new upload, like the results above.
    # citation_run_status keeps "found nothing" and "did not run / failed" apart, which
    # the plan requires never to be conflated; document_artifact is the only place a raw
    # context passage can be read from, since a CitationMatch carries none.
    citation_matches: tuple[CitationMatch, ...] = ()
    citation_run_status: str = CITATIONS_NOT_RUN
    document_artifact: DocumentArtifact | None = None

    # Whether `results` is the reference list the document printed. Cleared with the rest
    # on a new upload, and back to NOT_AUDITED rather than to "complete": a fresh session
    # has not checked this manuscript's list, which is not the same as having found it
    # whole, and the note the screen draws from it distinguishes the two.
    audit: ReferenceListAudit = NOT_AUDITED

    # Citation passages are shown by default; the `show_citation_context` gate that used to
    # guard them was removed on request 2026-08-11 (see citation_context.py). The export
    # side keeps its own opt-in, off by default, because a file outlives the session.
    #
    # Which passages are expanded from snippet to full paragraph, as
    # (reference number, anchor start). Independent of each other, so expanding one does
    # not silently close another the reviewer was comparing it against — and so the
    # toggle can update its own label in place instead of asking for a content refresh
    # that would scroll the list back to the top.
    expanded_contexts: set[tuple[int, int]] = field(default_factory=set)
    # Reference numbers whose passage list has been unfolded past the first few. Per
    # reference, because "show me all twelve" is a decision about one entry and should not
    # turn every other row into a wall of prose.
    expanded_place_lists: set[int] = field(default_factory=set)

    # References screen UI state
    ref_tab: str = "all"
    ref_sort_key: str = "n"
    ref_sort_dir: int = 1
    ref_expanded_n: int | None = None
    # Keep long result sets manageable in the fixed-height desktop content pane.
    ref_page: int = 0
    ref_page_size: int = 20

    # Manual review screen UI state
    review_page: int = 0
    review_expanded_n: int | None = None

    # Report export screen UI state
    export_included: dict[str, bool] = field(
        default_factory=lambda: dict(DEFAULT_EXPORT_INCLUDED)
    )
    export_path: str = ""
    export_status: str = "Not exported yet."

    def subline(self) -> str:
        if not self.results:
            return ""
        if self.loaded:
            return f"{self.loaded.name} · {len(self.results)} references"
        return f"{len(self.results)} references"

    def watermark(self) -> bool:
        from refcheck.gui.file_info import DEMO_MANUSCRIPT_ORIGIN

        return self.mode == "demo" and bool(self.loaded) and self.loaded.origin == DEMO_MANUSCRIPT_ORIGIN

    def stamp_decision(self, n: int, label: str) -> None:
        self.decisions[n] = {"label": label, "stamp": _dt.datetime.now().strftime("%Y-%m-%d %H:%M")}

    def open_review_refs(self) -> list[ReferenceResult]:
        return [r for r in self.results if r.status in ("review", "unchecked") and r.n not in self.decisions]

    def review_refs(self) -> list[ReferenceResult]:
        """All references routed to manual review, including resolved entries."""
        return [
            r
            for r in self.results
            if r.status in ("review", "unchecked") or r.n in self.decisions
        ]
