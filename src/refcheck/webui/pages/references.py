"""References screen — metric cards (as status filter) + sortable table of all
checked references, each row expandable for lookup detail.

Port of the PySide6 ReferencesScreen (refcheck.gui.screens.references).
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
from collections.abc import Callable

from nicegui import ui

from refcheck.gui import citation_display
from refcheck.gui.metric_cards import FILTER_CARD_KEYS, compute_metrics
from refcheck.gui.models import STATUS_KEYS, STATUS_LABELS, STATUS_LABELS_SHORT, ReferenceResult
from refcheck.gui.reference_list_display import reference_list_note
from refcheck.verification.openalex_crossref import openalex_refusal
from refcheck.gui.real_pipeline import MAX_VERIFIED_REFERENCES
from refcheck.webui import theme
from refcheck.webui.components.citation_context import render_citation_context
from refcheck.webui.components import work_details
from refcheck.webui.components.metric_cards import build_cards_row
from refcheck.webui.state import AppState

CONFIDENCE_TOOLTIP = (
    "Text similarity between this raw citation and its closest OpenAlex/Crossref match "
    "(0-1). Not a probability of correctness — a high score means the matched record's "
    "title looks like this citation, a low score means no close match was found."
)

CITED_TOOLTIP = (
    "How many in-text citations in this manuscript were resolved to this reference. The "
    "opposite direction from 'Cited by' above, which is how often the wider literature "
    "cites the matched work. '—' means the in-text search could not answer."
)

CITED_BY_TOOLTIP = (
    "How often the wider literature cites the matched work, as each source reported it at "
    "the time shown. The two differ because each counts only the citing works it indexes — "
    "neither is the complete figure. '—' means no source reported one, which is not the "
    "same as a work nobody has cited."
)


def render(state: AppState, actions) -> None:
    with ui.column().style(
        "padding:16px 24px 4px; gap:9px; width:100%; height:100%; min-height:0; overflow:hidden;"
    ):
        with ui.row().style("width:100%; align-items:baseline; gap:10px; flex-wrap:wrap;"):
            ui.label("Reference list").style(f"font-size:20px; font-weight:600; color:{theme.TEXT};")
            ui.label(state.subline()).classes("rc-mono").style(
                f"color:{theme.TEXT_FAINT}; font-size:11.5px;"
            )

        if not state.results:
            ui.label("No check has been run yet.").style(f"color:{theme.TEXT_FAINT}; padding:26px; text-align:center;")
            return

        metrics = compute_metrics(state.results)
        build_cards_row(metrics, state.ref_tab, on_click=lambda k: _set_tab(state, actions, k))

        # A source that stopped answering leaves fields blank, and a blank abstract looks
        # exactly like a work that has none. Said once, at the top, rather than left for a
        # reviewer to infer from what is missing.
        refusal = openalex_refusal()
        if refusal:
            ui.label(refusal).style(
                "border:1px solid #d8a83c; background:#fdf4e2; color:#4a4843; "
                "border-radius:5px; padding:8px 12px; font-size:11.5px; width:100%;"
            )

        _render_truncation_note(state)
        _render_reference_list_note(state)

        citations = citation_display.document_summary(
            [r.n for r in state.results], state.citation_matches, state.citation_run_status
        )
        _render_citation_headline(state, actions, citations)

        with ui.element("div").style(
            "display:grid; grid-template-columns:34px minmax(0, 1fr) 104px 38px; "
            "column-gap:7px; align-items:center; padding:0 10px; width:100%;"
        ):
            _render_sort_button(state, actions, "n", "#", "start")
            _render_sort_button(state, actions, "raw", "Raw citation", "start")
            _render_sort_button(state, actions, "status", "Status", "center")
            _render_sort_button(state, actions, "conf", "Conf.", "center")

        rows = _filtered_sorted(state)
        page_count = max(1, -(-len(rows) // state.ref_page_size))
        state.ref_page = min(state.ref_page, page_count - 1)
        page_rows = rows[
            state.ref_page * state.ref_page_size : (state.ref_page + 1) * state.ref_page_size
        ]

        with ui.column().classes("rc-scroll").style(
            "border:1px solid #cdcac3; border-radius:5px; background:#fff; width:100%; "
            "flex:1 1 0; min-height:0; overflow-y:auto; overflow-x:hidden; gap:0;"
        ):
            records = citation_display.per_reference(
                [r.n for r in state.results], state.citation_matches, state.citation_run_status
            )
            # Each row registers how to redraw just itself. Expanding a reference used to
            # call refresh_content(), which rebuilds this whole scroll pane and sends the
            # reader back to the top — so the row they clicked jumped off the screen as
            # they opened it.
            rows_by_n: dict[int, _RowHandle] = {}
            for ref in page_rows:
                _render_row(state, actions, ref, records[ref.n], rows_by_n)

        _render_pager(state, actions, page_count)


def _render_pager(state: AppState, actions, page_count: int) -> None:
    with ui.element("div").style(
        "display:grid; grid-template-columns:1fr auto 1fr; align-items:center; width:100%;"
    ):
        with ui.row().style("align-items:center; gap:3px; flex-wrap:nowrap; justify-self:start;"):
            ui.label("Rows").style(f"color:{theme.TEXT_FAINT}; font-size:10.5px;")
            ui.select(
                options={10: "10", 20: "20", 30: "30", 50: "50", 100: "100"},
                value=state.ref_page_size,
                on_change=lambda e: _set_page_size(state, actions, int(e.value)),
            ).props("dense borderless options-dense").style("width:54px; font-size:10.5px;")
        with ui.row().style("align-items:center; gap:10px; flex-wrap:nowrap;"):
            ui.button("◂ Prev", on_click=lambda: _set_page(state, actions, state.ref_page - 1)).props(
                "flat no-caps"
            ).style(f"color:{theme.ACCENT}; font-size:11px;").set_enabled(state.ref_page > 0)
            ui.label(f"Page {state.ref_page + 1} of {page_count}").classes("rc-mono").style(
                f"color:{theme.TEXT_FAINT}; font-size:11px;"
            )
            ui.button("Next ▸", on_click=lambda: _set_page(state, actions, state.ref_page + 1)).props(
                "flat no-caps"
            ).style(f"color:{theme.ACCENT}; font-size:11px;").set_enabled(
                state.ref_page < page_count - 1
            )
        ui.element("div")


def _render_sort_button(state: AppState, actions, key: str, label: str, alignment: str) -> None:
    mark = ""
    if key == state.ref_sort_key:
        mark = " ▲" if state.ref_sort_dir == 1 else " ▼"
    ui.button(label + mark, on_click=lambda: _set_sort(state, actions, key)).props(
        "flat no-caps"
    ).style(
        f"color:{theme.TEXT_MUTED}; font-size:11px; font-weight:600; "
        f"padding:4px 0; min-height:0; justify-self:{alignment};"
    )


def _set_page(state: AppState, actions, page: int) -> None:
    state.ref_page = page
    actions.refresh_content()


def _set_page_size(state: AppState, actions, page_size: int) -> None:
    state.ref_page_size = page_size
    state.ref_page = 0
    actions.refresh_content()


def _set_tab(state: AppState, actions, key: str) -> None:
    state.ref_tab = key
    state.ref_page = 0
    actions.refresh_content()


def _set_sort(state: AppState, actions, key: str) -> None:
    state.ref_sort_dir = -state.ref_sort_dir if state.ref_sort_key == key else 1
    state.ref_sort_key = key
    state.ref_page = 0
    actions.refresh_content()


def _toggle_row(state: AppState, rows_by_n: dict[int, _RowHandle], n: int) -> None:
    """Open one reference and close whichever was open, redrawing only those two rows.

    Not a content refresh: rebuilding the scroll pane resets its scroll position, so the
    row a reviewer clicked jumped out of view at the moment they opened it.
    """
    previously = state.ref_expanded_n
    state.ref_expanded_n = None if previously == n else n
    for number in {previously, n} - {None}:
        row = rows_by_n.get(number)
        if row is None:
            continue
        row.refresh()
        row.chevron.set_text(_chevron(state.ref_expanded_n == number, number))


def _filtered_sorted(state: AppState) -> list[ReferenceResult]:
    if state.ref_tab == "all":
        rows = list(state.results)
    elif state.ref_tab == "review":
        rows = [r for r in state.results if r.status in ("review", "unchecked")]
    elif state.ref_tab == "retracted":
        # Cuts across the statuses rather than being one of them: a retracted work is
        # usually also a *verified* one, since verification is what found the retraction.
        rows = [r for r in state.results if r.retracted is True]
    else:
        rows = [r for r in state.results if r.status == state.ref_tab]

    key_fn = {
        "n": lambda r: r.n,
        "raw": lambda r: r.raw.lower(),
        "status": lambda r: r.status,
        "conf": lambda r: r.confidence,
    }[state.ref_sort_key]
    rows.sort(key=key_fn, reverse=state.ref_sort_dir < 0)
    return rows


def _render_truncation_note(state: AppState) -> None:
    """Say so when the check stopped short of the document's full reference list.

    Drawn above the audit note and in the same loud style, because it qualifies every
    figure below it even harder: those entries were not checked and found fine, they were
    not checked at all. A reader who sees "500 references, 3 unresolved" without this line
    is being told something false about a manuscript that had more.
    """
    if state.truncated_from is None:
        return
    with ui.column().style(
        "border:1px solid #d8a83c; background:#fdf4e2; color:#4a4843; border-radius:5px; "
        "padding:8px 12px; width:100%; gap:3px; box-sizing:border-box;"
    ):
        ui.label(
            f"Only the first {len(state.results)} of {state.truncated_from} references were checked."
        ).style("font-size:11.5px; font-weight:600;")
        ui.label(
            "One check verifies at most "
            f"{MAX_VERIFIED_REFERENCES} references against OpenAlex and Crossref. The "
            "remaining entries were extracted but not looked up, and the figures below "
            "describe only the ones that were."
        ).style("font-size:11.5px;")


def _render_reference_list_note(state: AppState) -> None:
    """Whether the list below is the list the document printed — above everything it qualifies.

    Placed over the counts rather than beside them because that is what it is about: the
    metric cards, the citation headline and every per-row figure are all statements about a
    reference list, and this is the line saying whether that list is the right one. A
    reviewer who reads "29 references, 2 uncited" and only afterwards learns two entries
    were merged has already drawn the conclusion.

    Draws nothing where the comparison did not happen, which `reference_list_note` returns
    as an empty note. A confirmation that the list is whole is drawn quietly and a
    discrepancy loudly, since only one of them changes what a reviewer should do next.
    """
    note = reference_list_note(state.audit, len(state.results))
    if not note:
        return
    if note.complete:
        ui.label(note.headline).style(
            f"color:{theme.TEXT_FAINT}; font-size:11.5px; padding:0 10px; width:100%;"
        )
        return
    with ui.column().style(
        "border:1px solid #d8a83c; background:#fdf4e2; color:#4a4843; border-radius:5px; "
        "padding:8px 12px; width:100%; gap:3px; box-sizing:border-box;"
    ):
        ui.label(note.headline).style("font-size:11.5px; font-weight:600;")
        if note.detail:
            ui.label(note.detail).style("font-size:11.5px;")


def _render_citation_headline(
    state: AppState, actions, citations: citation_display.DocumentCitations
) -> None:
    """One line above the table, saying what the in-text search established.

    Rendered whatever the run status, including the states where it says only that the
    search did not run. A screen that goes blank in those states leaves a reviewer to read
    the absence of citation information as an absence of citation problems, which is the
    reading the run statuses exist to prevent.

    Carries the way back out of the context setting. It is switched on from inside a
    reference's detail panel, where the passages are, but a reviewer who wants the
    manuscript's text off the screen should not have to find the row they turned it on
    from — so the "off" control lives somewhere always visible.
    """
    findings = bool(citations.orphaned or citations.uncited_references)
    colour = theme.BLOCKER_FG if findings else theme.TEXT_FAINT
    with ui.row().style(
        "align-items:center; gap:14px; padding:0 10px; width:100%; flex-wrap:wrap;"
    ):
        ui.label(citations.headline).style(f"color:{colour}; font-size:11.5px;")


@dataclasses.dataclass
class _RowHandle:
    """What a row needs in order to redraw itself without the screen being rebuilt: its
    detail panel's refresh, and the chevron whose direction has to follow it."""

    refresh: Callable[[], None]
    chevron: object


def _render_row(
    state: AppState,
    actions,
    ref: ReferenceResult,
    cited: citation_display.ReferenceCitations,
    rows_by_n: dict[int, _RowHandle],
) -> None:
    expanded = ref.n == state.ref_expanded_n
    retracted = ref.retracted is True
    row_bg = theme.BLOCKER_BG if retracted else ("#fefaf8" if ref.status == "halluc" else "#fff")
    # A retracted reference is marked on the row itself, not only inside the fold-out.
    # The status badge cannot carry it — a retracted work is normally *verified*, which is
    # the badge it will be wearing — so the alarm has to be something a reviewer scanning
    # a hundred collapsed rows cannot read past: the row changes colour, gains a red bar
    # down its left edge, and says the word.
    edge = f"border-left:4px solid {theme.BLOCKER_BORDER};" if retracted else ""
    with ui.column().style(
        f"background:{row_bg}; {edge} border-bottom:1px solid {theme.BORDER_SOFT}; "
        "width:100%; gap:0;"
    ):
        with ui.element("div").style(
            "display:grid; grid-template-columns:34px minmax(0, 1fr) 104px 38px; "
            "column-gap:7px; align-items:start; padding:9px 10px; width:100%; cursor:pointer;"
        ).on("click", lambda: _toggle_row(state, rows_by_n, ref.n)):
            chevron = ui.label(_chevron(expanded, ref.n)).classes("rc-mono").style(
                f"color:{theme.TEXT_QUIET}; font-size:11px; white-space:nowrap;"
            )
            with ui.column().style("min-width:0; gap:2px;"):
                if retracted:
                    ui.html(
                        theme.status_badge_html(
                            "⚠ RETRACTED",
                            theme.RETRACTED_PALETTE,
                            "font-size:10px; font-weight:700; letter-spacing:0.06em;",
                        ),
                        tag="div",
                    )
                ui.label(ref.raw).style(
                    f"color:{theme.TEXT_STRONG}; font-size:12px; min-width:0; overflow-wrap:anywhere;"
                )
                # Only the flag is worth a collapsed row's space. The citation count is a
                # fact about a reference the reviewer is not currently asking about; a
                # reference nothing in the manuscript cites is the finding this screen
                # exists to put in front of them.
                if cited.uncited:
                    ui.label("no in-text citation found").style(
                        f"color:{theme.BLOCKER_FG}; font-size:10.5px;"
                    )
            pal = theme.STATUS[ref.status]
            ui.html(
                theme.status_badge_html(
                    STATUS_LABELS_SHORT[ref.status],
                    pal,
                    "width:104px; justify-content:center; box-sizing:border-box;",
                ),
                tag="div",
            ).style("justify-self:center; align-self:center;").tooltip(STATUS_LABELS[ref.status])
            ui.label(f"{ref.confidence:.2f}" if ref.confidence else "—").classes("rc-mono").style(
                f"color:{theme.TEXT_STRONG}; font-size:11px; font-weight:600; "
                "justify-self:center; align-self:center; white-space:nowrap;"
            ).tooltip(CONFIDENCE_TOOLTIP)

        @ui.refreshable
        def detail() -> None:
            if state.ref_expanded_n == ref.n:
                _render_detail(state, actions, ref, cited)

        detail()
        rows_by_n[ref.n] = _RowHandle(refresh=detail.refresh, chevron=chevron)


def _chevron(expanded: bool, n: int) -> str:
    return ("▾ " if expanded else "▸ ") + f"{n:02d}"


def _doi_url(doi: str) -> str | None:
    """A resolvable link, or None for the placeholder strings the DOI column also carries
    ("no match", "not checked (rate limit)", "—"), which must not become links."""
    return f"https://doi.org/{doi}" if doi.startswith("10.") else None


def _cited_by(ref: ReferenceResult) -> str:
    """How often the wider literature cites the matched work, per source.

    Both figures, attributed, because they disagree substantially — measured, 8,121
    (Crossref) against 10,653 (OpenAlex) for the same DOI. Each counts only the citing
    works it indexes, so neither is wrong and neither is the truth; showing one number
    would make the reader's answer depend on which source happened to win the match,
    with nothing on screen to say so.

    "—" for an unmatched reference and for a match whose lookups reported no count at all:
    a work nobody has cited yet and a figure nobody gave us are different facts, and
    printing the second as "0" is how this card told a reviewer that a heavily-cited paper
    had never been cited.
    """
    if ref.status not in ("verified", "dup"):
        return "—"
    text = work_details.cited_by_text(ref.citations_crossref, ref.citations_openalex)
    if text != "—":
        return text
    # A source that answered without a per-source figure. The merged number is still
    # better than a dash.
    return f"{ref.citations:,}" if ref.citations is not None else "—"


def _lookup_note(ref: ReferenceResult) -> str:
    """Which source answered, and when — one row, because neither is worth its own.

    The time is what makes the rest of the card provisional: these counts and titles are
    live API answers that move, and the reviewer reading this in an hour should be able to
    see how old it is.
    """
    parts = [part for part in (ref.source, ref.queried) if part]
    return " · ".join(parts) if parts else "—"


def _render_retraction_banner(ref: ReferenceResult) -> None:
    """The loudest thing this application says, and the only thing above the title.

    Design rules it follows, all of them about not being ignorable and not being wrong:

    * It is a banner, not a field. A retraction is not one attribute of a work among six;
      it is the answer to whether the work should be cited at all, and a grid row reading
      "Retraction: retracted" is read at the same speed as "Cited by: 12".
    * It carries its evidence. A retraction is an accusation about someone's published
      work, so the notice's own DOI is a link — a reviewer must be able to go and read it
      rather than take this screen's word for it. Where the source gave only the boolean
      (OpenAlex does), the banner says which source, so the claim is still traceable.
    * It appears only for True. `retracted` is tri-state and None means no lookup
      answered; rendering that as an all-clear is the failure this whole design is against,
      so silence here means "no retraction was reported", never "this work is fine".
    """
    if ref.retracted is not True:
        return
    with ui.row().style(
        f"background:{theme.RETRACTED_PALETTE['bg']}; "
        f"border:1px solid {theme.RETRACTED_PALETTE['border']}; "
        f"border-left:4px solid {theme.RETRACTED_PALETTE['border']}; border-radius:4px; "
        "padding:8px 11px; gap:8px; width:100%; align-items:baseline; flex-wrap:wrap; "
        "box-sizing:border-box;"
    ):
        ui.label("⚠ RETRACTED").style(
            f"color:{theme.RETRACTED_PALETTE['fg']}; font-size:11.5px; font-weight:700; "
            "letter-spacing:0.06em; white-space:nowrap;"
        )
        ui.label("This work has been retracted and should not be cited as evidence.").style(
            f"color:{theme.RETRACTED_PALETTE['fg']}; font-size:11.5px;"
        )
        if work_details.retraction_url(ref.retraction_doi):
            ui.link(
                "read the retraction notice",
                work_details.retraction_url(ref.retraction_doi),
                new_tab=True,
            ).style(f"color:{theme.RETRACTED_PALETTE['fg']}; font-size:11.5px; font-weight:600;")
        else:
            ui.label(f"reported by {ref.source or 'the lookup'}").style(
                f"color:{theme.RETRACTED_PALETTE['fg']}; font-size:10.5px;"
            )


def _render_matched_work(ref: ReferenceResult) -> None:
    """The record the lookup actually matched, above the fields describing it.

    Year and outlet were being carried through the whole pipeline and never shown, which
    left the card unable to answer the question a reviewer opens it for: is *this* the work
    the manuscript meant? A title alone does not settle that — the same title appears as a
    preprint, a chapter and an article in three different years.
    """
    # Its own column: title, imprint and abstract describe one thing and belong tight
    # together, at a closer spacing than the panel's blocks are from each other.
    with ui.column().style("gap:3px; width:100%; min-width:0;"):
        ui.label("No match" if ref.title == "—" else ref.title).style(
            f"font-size:12px; font-weight:500; color:{theme.TEXT}; overflow-wrap:anywhere;"
        )
        detail = " · ".join(str(part) for part in (ref.year, ref.outlet) if part)
        if detail:
            ui.label(detail).style(f"color:{theme.TEXT_FAINT}; font-size:11px;")
        _render_abstract(ref)


def _render_terms(label: str, terms: tuple[str, ...], accent: str) -> None:
    """One labelled row of chips, aligned to the same two-column grid as the fields below.

    Named rather than left as a bare row of pills, and the two vocabularies kept apart:
    topics are the labelled end of OpenAlex's own hierarchy ("Meta-analysis and systematic
    reviews") while keywords are finer and noisier ("MEDLINE", "Affect (linguistics)"), so
    a reader who cannot see which list a term came from cannot judge it. Nothing renders
    when the lookup reported none, on the same rule as the retraction banner — a row that
    is usually empty is a row a reviewer learns to skip, taking the occupied one with it.
    """
    if not terms:
        return
    ui.label(label).style(f"color:{theme.TEXT_FAINT}; font-size:11px;")
    with ui.row().style("gap:4px; flex-wrap:wrap;"):
        for term in terms:
            ui.label(term).style(
                f"background:{accent}; border:1px solid #dcdfe4; color:{theme.TEXT_MUTED}; "
                "border-radius:9px; padding:1px 7px; font-size:10px; white-space:nowrap;"
            )


def _render_abstract(ref: ReferenceResult) -> None:
    """The matched work's abstract, clamped to two lines and expanded by clicking it.

    Clamped rather than truncated in Python: the full text is in the DOM and CSS decides
    how much of it shows, so expanding is instant and no server round-trip scrolls the
    list. Two lines is the budget — this is a scanning screen, and an abstract is the
    largest thing on the card by an order of magnitude.

    Public metadata about a published work, so no gate: it is the citation *context* that
    quotes the manuscript under review, and only that is behind an opt-in.
    """
    if not ref.abstract:
        return
    base = (
        f"color:{theme.TEXT_MUTED}; font-size:10.5px; line-height:1.45; cursor:pointer; "
        "max-width:760px;"
    )
    clamped = (
        "display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; "
        "overflow:hidden;"
    )
    label = ui.label(ref.abstract).style(base + clamped)
    expanded = {"on": False}

    def toggle() -> None:
        expanded["on"] = not expanded["on"]
        # `replace=`, not the default merge. `.style("…")` *adds* declarations to what the
        # element already has, so re-styling without the clamp left every clamp property
        # exactly where it was and the abstract never opened.
        label.style(replace=base + ("" if expanded["on"] else clamped))

    label.on("click", toggle)


def _render_detail(
    state: AppState, actions, ref: ReferenceResult, cited: citation_display.ReferenceCitations
) -> None:
    # box-sizing matters here rather than being tidiness: `width:100%` with 48px of
    # horizontal padding on a content-box element makes the panel wider than the row it
    # sits in, and the scroll container above clips overflow-x — so the right-hand end of
    # a citation passage was being cut off the screen entirely.
    #
    # One gap for the whole panel, so its blocks (retraction, matched work, fields,
    # passages, actions) are separated by one rhythm instead of each one bringing its own
    # margin. The tighter spacing inside each block is that block's own business.
    with ui.column().style(
        f"background:#f6f7f9; border-top:1px solid {theme.BORDER_SOFT}; "
        "padding:11px 16px 14px 34px; gap:10px; width:100%; box-sizing:border-box;"
    ):
        _render_retraction_banner(ref)
        _render_matched_work(ref)

        rows = [
            ("DOI", ref.doi),
            ("Looked up", _lookup_note(ref)),
            ("Cited by", _cited_by(ref)),
            (citation_display.CITED_FIELD, cited.figure),
        ]

        # What the "Duplicate" badge actually means: which earlier reference shares this
        # DOI. Without this, a reviewer sees the badge but has to hunt through the rest of
        # the list to find the reference it's paired with.
        if ref.status == "dup":
            by_n = {r.n: r for r in state.results}
            earlier = by_n.get(ref.dup_of) if ref.dup_of else None
            if earlier is not None:
                pairing = f"#{earlier.n:02d} — {earlier.title if earlier.title != '—' else earlier.raw}"
            elif ref.manual_note:
                # Manually recategorized to "Duplicate" rather than detected by the same-DOI
                # check, so there's no earlier reference on record to point at — distinct from
                # the pairing having gone missing, which would be a real problem.
                pairing = "manually flagged — no automatic match on record"
            else:
                pairing = "unknown (earlier reference not found)"
            rows.insert(0, ("Duplicate of", pairing))

        with ui.grid(columns=2).style(
            "grid-template-columns:88px minmax(0, 1fr); column-gap:14px; row-gap:5px; "
            "width:100%; min-width:0; align-items:center;"
        ):
            # In the same grid as the fields, so the labels line up in one column instead
            # of the chips floating in their own band above it.
            _render_terms("Topics", ref.topics, work_details.TOPIC_TINT)
            _render_terms("Keywords", ref.keywords, work_details.KEYWORD_TINT)
            for key, value in rows:
                ui.label(key).style(f"color:{theme.TEXT_FAINT}; font-size:11px;")
                highlight = key == citation_display.CITED_FIELD and cited.uncited
                fg = theme.BLOCKER_FG if highlight else theme.TEXT_MUTED
                if key == "DOI" and _doi_url(ref.doi):
                    ui.link(value, _doi_url(ref.doi), new_tab=True).classes("rc-mono").style(
                        f"color:{theme.ACCENT}; font-size:11px;"
                    )
                    continue
                label = ui.label(value).classes("rc-mono").style(f"color:{fg}; font-size:11px;")
                if key == citation_display.CITED_FIELD:
                    label.tooltip(CITED_TOOLTIP)
                elif key == "Cited by":
                    label.tooltip(CITED_BY_TOOLTIP)

        render_citation_context(state, actions, ref.n)

        # The actions are their own band, set off from the evidence above them. Without the
        # separation a solid button sits immediately under a quoted sentence and reads as
        # part of it.
        with ui.column().style(
            f"gap:5px; width:100%; min-width:0; padding-top:9px; "
            f"border-top:1px solid {theme.BORDER_SOFT};"
        ):
            with ui.row().style("gap:7px; align-items:center; flex-wrap:wrap;"):
                if ref.status == "unchecked":
                    ui.button("Retry lookup").props("disable no-caps").style(
                        theme.SECONDARY_BUTTON + "padding:5px 10px; font-size:11.5px;"
                    )

                with ui.button("Recategorize ▾").props("no-caps").style(
                    theme.SECONDARY_BUTTON
                    + "padding:5px 10px; font-size:11.5px; width:fit-content;"
                ):
                    with ui.menu().style("padding-top:3px;"):
                        for key in STATUS_KEYS:
                            if key == ref.status:
                                continue
                            ui.menu_item(
                                STATUS_LABELS[key],
                                on_click=lambda _e, k=key: _recategorize(state, actions, ref.n, k),
                            ).props("dense").style("font-size:11.5px;")

            if ref.manual_note:
                ui.label(ref.manual_note).style(
                    f"color:{theme.TEXT_FAINT}; font-size:10.5px; font-style:italic;"
                )


def _recategorize(state: AppState, actions, n: int, new_status: str) -> None:
    stamp = _dt.datetime.now().strftime("%H:%M")
    for i, ref in enumerate(state.results):
        if ref.n != n:
            continue
        note = f'Recategorized from "{STATUS_LABELS[ref.status]}" to "{STATUS_LABELS[new_status]}" at {stamp}.'
        overrides: dict = {"status": new_status, "manual_note": note}
        if new_status == "dup":
            overrides["dup_of"] = ref.dup_of
        else:
            overrides["dup_of"] = None
            if new_status not in ("verified",):
                # Moving off a real match (verified/dup) — the DOI, citation count, source,
                # and query timestamp all describe that old match, and would otherwise sit
                # next to a "No match found"/"Needs review" badge as if still confirmed.
                overrides.update(
                    title="—",
                    doi="not checked (rate limit)" if new_status == "unchecked" else "no match",
                    citations=None,
                    retracted=None,
                    retraction_doi="",
                    source="",
                    queried="",
                )
        state.results[i] = dataclasses.replace(ref, **overrides)
        break
    actions.refresh_content()
