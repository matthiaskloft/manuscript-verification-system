"""The one place raw manuscript text renders on screen.

(The other place it can render at all is the exported report, behind an opt-in that is
off by default — see `report_data.citation_rows`. Showing a sentence inside a session and
writing it into a file that outlives the session are not the same act, and only the second
one still has a gate in front of it.)

Phase 5, steps 3 and 4 of docs/plans/plan-in-text-citation-parsing.md. Every other part of
the citation feature deals in structured status — a number, a flag, a marker's own text.
This component is the exception: it quotes the manuscript's sentences back at the reviewer.

**These passages are shown by default.** That reverses the plan's original
context-visibility decision (Design Decisions, 2026-08-04), which hid them behind a
`show_citation_context` switch even in-session; the switch was removed on request
2026-08-11. The reasoning that stands either way: the manuscript is the reviewer's own
upload and it is already on their screen in the row above. The reasoning that was given up:
a shared screen or a live demo now shows the document's sentences without anyone choosing
to. Session-scoping is unaffected and does the real work here — passages are read from the
artifact at the moment of drawing and are never stored. `CitationMatch` carries an anchor
and no text, `AppState` carries the artifact and no passages, and this module keeps
nothing. There is one copy of the manuscript in the session, it is the artifact, and it
dies with the session.

What the reviewer gets, and why each part is here rather than being simpler:

* **The marker is marked** inside the sentence. Every passage contains the citation
  somewhere in a hundred-odd characters of prose, and a reviewer who has to find it again
  by eye is doing the work the anchor already did. The offsets are exact, so the passage is
  cut into before/marker/after rather than searched for the marker's text — which would
  find the wrong occurrence whenever the same citation appears twice in one sentence.
* **The collapsed depth is the sentence**, the expanded one the paragraph, and clicking the
  passage moves between them. A fixed character window came first and was wrong: it cut
  mid-word at both ends, so the reviewer was asked to judge whether a citation belonged
  from a fragment that started in the middle of one. Both depths are bounded by
  `artifact.context_bounds`, so a marker straddling a block boundary is shown whole rather
  than cut at the boundary — and the depth label is derived from those bounds rather than
  fixed, since "full paragraph" understates an expansion covering two of them.
* **Three passages at most**, with the rest one click away. A reference cited a dozen times
  otherwise turns a table row into a page of prose, and the twelfth passage is not what
  anyone opened the row for.
"""

from __future__ import annotations

import html

from nicegui import ui

from refcheck.extraction.document_artifact import SourceAnchor
from refcheck.gui import citation_display
from refcheck.webui import theme
from refcheck.webui.state import AppState

# How many passages a reference shows before the rest are folded behind one click.
VISIBLE_PLACES = 3


def render_citation_context(state: AppState, actions, reference_n: int) -> None:
    """Where in the manuscript this reference is cited from."""
    places = citation_display.places_for(reference_n, state.citation_matches)
    if not places:
        return

    if state.document_artifact is None:
        # Kept, but no longer claimed to be reachable — it was, and the claim outlived the
        # code. `real_pipeline._match_citations` returns no matches at all when the artifact
        # is None, so `places_for` is empty and this function has already returned above;
        # `state.document_artifact` and `state.citation_matches` are set from the same
        # result and cannot disagree. The guard stays because a caller that filled the
        # matches from somewhere else would otherwise render an empty space where the
        # passages should be, and saying so beats saying nothing.
        ui.label("The manuscript text is not available in this session.").style(
            f"color:{theme.TEXT_FAINT}; font-size:11px;"
        )
        return

    showing_all = reference_n in state.expanded_place_lists
    visible = places if showing_all else places[:VISIBLE_PLACES]
    # A rule above the passages: they are quoted manuscript prose sitting under a block of
    # structured fields, and the two read very differently. The divider is what stops the
    # first passage looking like another field's value.
    with ui.column().style(
        f"gap:9px; width:100%; min-width:0; box-sizing:border-box; padding-top:9px; "
        f"border-top:1px solid {theme.BORDER_SOFT};"
    ):
        for place in visible:
            _render_place(state, actions, reference_n, place)
        if len(places) > len(visible):
            ui.button(
                f"Show {len(places) - len(visible)} more",
                on_click=lambda: _show_all(state, actions, reference_n),
            ).props("flat no-caps dense").style(
                f"color:{theme.ACCENT}; font-size:10.5px; padding:0; min-height:0; "
                "width:fit-content;"
            )


def _render_place(
    state: AppState, actions, reference_n: int, place: citation_display.CitationPlace
) -> None:
    anchor = place.match.anchor
    artifact = state.document_artifact
    key = (reference_n, anchor.start)
    expanded = key in state.expanded_contexts

    with ui.column().style(
        f"border-left:2px solid {theme.BORDER}; padding:1px 0 1px 10px; gap:3px; "
        "width:100%; min-width:0; box-sizing:border-box;"
    ):
        with ui.row().style("align-items:baseline; gap:7px; flex-wrap:wrap;"):
            ui.label(place.note).style(f"color:{theme.TEXT_FAINT}; font-size:10.5px;")
            if anchor.source_line is not None:
                # The line in the document as uploaded, not in the normalized body — a
                # reviewer checks this against the file in front of them.
                ui.label(f"line {anchor.source_line + 1}").classes("rc-mono").style(
                    f"color:{theme.TEXT_QUIET}; font-size:10.5px;"
                )
            depth = ui.label(_depth_label(artifact, anchor, expanded)).style(
                f"color:{theme.TEXT_QUIET}; font-size:10px;"
            )
        passage = ui.html(_passage_html(artifact, anchor, expanded), tag="div").style(
            f"color:{theme.TEXT_MUTED}; font-size:11.5px; line-height:1.55; cursor:pointer; "
            "width:100%; min-width:0; overflow-wrap:anywhere;"
        )
        # The passage is its own control. Updating it in place rather than refreshing the
        # screen keeps the scroll position — a rebuild sends the reader back to the top of
        # the reference list, so the sentence they asked to see more of leaves the screen
        # as they ask for it.
        passage.on(
            "click", lambda: _toggle(state, key, artifact, anchor, passage, depth)
        )


def _paragraphs_spanned(artifact, anchor: SourceAnchor) -> int:
    """How many paragraphs the expanded passage will cover.

    One, for every marker that sits inside a paragraph. More only where the marker itself
    straddles a block boundary, which is when `context_bounds` widens to hold it.
    """
    return max(
        1,
        sum(
            1
            for paragraph in artifact.paragraphs
            if anchor.start < paragraph.end and paragraph.start < anchor.end
        ),
    )


def _depth_label(artifact, anchor: SourceAnchor, expanded: bool) -> str:
    """What the reader is looking at, and what clicking will do.

    Derived from the passage rather than fixed, because a straddling marker's expansion
    covers every paragraph it runs into: "full paragraph" would then understate what is on
    screen, and "click for the paragraph" would promise the wrong thing. Deriving keeps the
    specific word for the case that is almost always the real one — a reader is better told
    "paragraph" than "context" when a paragraph is exactly what they will get — and tells
    the truth in the case this component was just fixed for.
    """
    spanned = _paragraphs_spanned(artifact, anchor)
    whole = "full paragraph" if spanned == 1 else f"all {spanned} paragraphs"
    if expanded:
        return f"{whole} · click to collapse"
    return f"sentence · click for {'the paragraph' if spanned == 1 else whole}"


def _passage_slice(artifact, anchor: SourceAnchor, expanded: bool) -> tuple[int, int]:
    """The passage's bounds in `body_text` — the sentence, or the whole paragraph.

    Bounds rather than text, because the marker has to be highlighted at a known offset
    inside the result. The collapsed depth is a *sentence*: a fixed character window was
    what this replaced, and it cut mid-word at both ends, leaving a reviewer to judge a
    citation from a fragment.

    Expanded takes `context_bounds` rather than the anchor's paragraph directly, for the
    same reason `paragraph_text` does: a marker straddling a block boundary belongs to more
    than one paragraph, and the expand view is where a reviewer goes when the collapsed one
    looked wrong. Reading the paragraph here also made expanding *shrink* the passage once
    `sentence_bounds` learned to cover both halves.
    """
    if expanded:
        return artifact.context_bounds(anchor)
    return artifact.sentence_bounds(anchor)


def _passage_html(artifact, anchor: SourceAnchor, expanded: bool) -> str:
    """The passage with its citation marked, and an ellipsis where text was cut.

    Every part is escaped: this is manuscript text, it is untrusted, and it is being handed
    to an HTML sink. The ellipsis goes only where something was actually removed — a
    snippet that happens to start at its paragraph's own beginning is not truncated, and
    saying it is would be a small lie about the document.
    """
    start, end = _passage_slice(artifact, anchor, expanded)
    # Measured against the same bounds the passage is cut from, so the ellipsis says
    # whether *this* passage was truncated. Compared against the anchor's own paragraph,
    # a straddling marker's sentence looked truncated at one end and un-truncated at the
    # other, both wrongly.
    low, high = artifact.context_bounds(anchor)
    body = artifact.body_text
    before = html.escape(body[start : anchor.start])
    marker = html.escape(body[anchor.start : anchor.end])
    after = html.escape(body[anchor.end : end])
    lead = "… " if start > low else ""
    tail = " …" if end < high else ""
    highlighted = (
        f'<span style="background:#fbf1dd; border-bottom:1px solid #dcbb78; '
        f'font-weight:600; padding:0 1px;">{marker}</span>'
    )
    return f"{lead}{before}{highlighted}{after}{tail}"


def _show_all(state: AppState, actions, reference_n: int) -> None:
    state.expanded_place_lists.add(reference_n)
    actions.refresh_content()


def _toggle(state: AppState, key, artifact, anchor, passage, depth) -> None:
    expanded = key not in state.expanded_contexts
    state.expanded_contexts.symmetric_difference_update({key})
    passage.set_content(_passage_html(artifact, anchor, expanded))
    depth.set_text(_depth_label(artifact, anchor, expanded))
