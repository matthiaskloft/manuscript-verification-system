"""Manual review queue — unresolved references.

Port of the PySide6 ManualReviewScreen (openrefcheck.gui.screens.manual_review).
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
from urllib.parse import quote_plus

from nicegui import ui

from openrefcheck.gui import citation_display
from openrefcheck.gui.models import STATUS_LABELS_SHORT, Candidate, ReferenceResult
from openrefcheck.verification.openalex_crossref import MATCH_THRESHOLD
from openrefcheck.webui import theme
from openrefcheck.webui.components import work_details
from openrefcheck.webui.components.citation_context import render_citation_context
from openrefcheck.webui.pages.references import CONFIDENCE_TOOLTIP
from openrefcheck.webui.state import AppState

_GOOGLE_SEARCH_URL = "https://www.google.com/search?q={query}"

# Smaller than references.py's page because each row here (candidates, action
# buttons, manual-correction form) is much taller.
PAGE_SIZE = 5


def _reason_for(ref: ReferenceResult) -> str:
    if ref.status == "unchecked":
        return "Crossref rate limit — no verification attempt completed."
    if len(ref.candidates) >= 2:
        top, second = ref.candidates[0].similarity, ref.candidates[1].similarity
        if abs(top - second) <= 0.05:
            return f"Two candidates within {top - second:.2f} similarity — ambiguous, not auto-resolved."
    if ref.candidates:
        return f"Best candidate {ref.candidates[0].similarity:.2f}, below the {MATCH_THRESHOLD:.2f} confidence threshold."
    return f"Confidence {ref.confidence:.2f}, below the {MATCH_THRESHOLD:.2f} confidence threshold — no strong candidate found."


def render(state: AppState, actions) -> None:
    with ui.column().style("padding:24px 30px 30px; gap:14px; width:100%;"):
        ui.label("Manual review queue").style(f"font-size:20px; font-weight:600; color:{theme.TEXT};")
        ui.label(
            "References with no automated match, several plausible candidates, or "
            "confidence below the threshold. Automated and manual status are reported "
            "separately, each with a timestamp."
        ).style(f"color:{theme.TEXT_MUTED}; font-size:13px; max-width:760px;")

        review_refs = state.review_refs()
        if not state.results:
            _empty(state, "No check has been run yet.")
            return
        if not review_refs:
            _empty(state, "No references require manual review.")
            return

        page_count = max(1, -(-len(review_refs) // PAGE_SIZE))
        state.review_page = min(state.review_page, page_count - 1)
        page_refs = review_refs[state.review_page * PAGE_SIZE : (state.review_page + 1) * PAGE_SIZE]
        page_numbers = {ref.n for ref in page_refs}
        unresolved_page_refs = [ref for ref in page_refs if ref.n not in state.decisions]
        if (
            state.review_expanded_n not in page_numbers
            or state.review_expanded_n in state.decisions
        ):
            state.review_expanded_n = unresolved_page_refs[0].n if unresolved_page_refs else None

        records = citation_display.per_reference(
            [r.n for r in state.results], state.citation_matches, state.citation_run_status
        )
        with ui.column().classes("rc-scroll").style("gap:11px; width:100%;"):
            for ref in page_refs:
                _render_row(state, actions, ref, records[ref.n])

        if page_count > 1:
            _render_pager(state, actions, page_count)


def _render_pager(state: AppState, actions, page_count: int) -> None:
    with ui.row().style("width:100%; justify-content:center; align-items:center; gap:10px;"):
        ui.button("◂ Prev", on_click=lambda: _set_page(state, actions, state.review_page - 1)).props(
            "flat no-caps"
        ).style(f"color:{theme.ACCENT}; font-size:11px;").set_enabled(state.review_page > 0)
        ui.label(f"Page {state.review_page + 1} of {page_count}").classes("rc-mono").style(
            f"color:{theme.TEXT_FAINT}; font-size:11px;"
        )
        ui.button("Next ▸", on_click=lambda: _set_page(state, actions, state.review_page + 1)).props(
            "flat no-caps"
        ).style(f"color:{theme.ACCENT}; font-size:11px;").set_enabled(state.review_page < page_count - 1)


def _set_page(state: AppState, actions, page: int) -> None:
    state.review_page = page
    state.review_expanded_n = None
    actions.refresh_content()


def _expand_review(state: AppState, actions, n: int) -> None:
    if state.review_expanded_n != n:
        state.review_expanded_n = n
        actions.refresh_content()


_FLAT = "white-space:normal; text-align:left;"


def _render_candidate(cand: Candidate) -> None:
    """One candidate, described the way the References screen describes a matched work.

    It used to be a title, a source, a year and a similarity score. Choosing between these
    *is* the identification the automated match could not make, so it was the one decision
    on this screen being asked for on less evidence than the app shows about matches nobody
    has to decide. Year and venue separate a preprint from the article from the chapter;
    the citation counts say whether a candidate is a work anybody reads; the retraction
    warning is the one that cannot be left out, because confirming a candidate writes it
    into the reference list.
    """
    with ui.column().style("gap:3px; align-items:flex-start; width:100%; min-width:0;"):
        if cand.retracted is True:
            # Above the title, like the reference card's banner, and for the same reason:
            # it is not one attribute of this work among several, it is the answer to
            # whether it should be picked at all.
            ui.label("⚠ RETRACTED — do not confirm without reading the notice").style(
                f"background:{theme.RETRACTED_PALETTE['bg']}; color:{theme.RETRACTED_PALETTE['fg']}; "
                f"border:1px solid {theme.RETRACTED_PALETTE['border']}; border-radius:3px; "
                f"padding:2px 6px; font-size:10px; font-weight:700; {_FLAT}"
            )
        ui.label(cand.title).style(
            f"font-size:12px; font-weight:600; color:{theme.TEXT_STRONG}; "
            f"line-height:1.35; {_FLAT}"
        )
        meta = [part for part in (cand.source, work_details.imprint_text(cand.year, cand.outlet)) if part]
        meta.append(cand.doi)
        ui.label(" · ".join(meta)).classes("rc-mono").style(
            f"color:{theme.TEXT_FAINT}; font-size:10.5px; {_FLAT}"
        )
        if cand.topics or cand.keywords:
            with ui.row().style("gap:3px; flex-wrap:wrap; padding-top:1px;"):
                for term, tint in [
                    *((t, work_details.TOPIC_TINT) for t in cand.topics),
                    *((k, work_details.KEYWORD_TINT) for k in cand.keywords),
                ]:
                    ui.label(term).style(
                        f"background:{tint}; border:1px solid #dcdfe4; color:{theme.TEXT_MUTED}; "
                        f"border-radius:9px; padding:1px 7px; font-size:10px; {_FLAT}"
                    )
        cited_by = work_details.cited_by_text(cand.citations_crossref, cand.citations_openalex)
        facts = [f"Title similarity to this citation: {cand.similarity:.2f}"]
        if cited_by != "—":
            facts.append(f"cited by {cited_by}")
        ui.label(" · ".join(facts)).style(
            f"color:{theme.TEXT_MUTED}; font-size:10.5px; {_FLAT}"
        )
        if cand.abstract:
            # Two lines, like the reference card. A candidate list is a scanning surface
            # and an abstract is the largest thing that can go on it.
            ui.label(cand.abstract).style(
                f"color:{theme.TEXT_FAINT}; font-size:10.5px; line-height:1.45; {_FLAT} "
                "display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; "
                "overflow:hidden;"
            )


def _empty(state: AppState, text: str) -> None:
    ui.label(text).style(
        f"border:1px solid #cdcac3; border-radius:5px; background:#fff; "
        f"color:{theme.TEXT_MUTED}; padding:26px; font-size:13px; text-align:center; width:100%;"
    )


def _render_row(
    state: AppState, actions, ref: ReferenceResult, cited: citation_display.ReferenceCitations
) -> None:
    pal = theme.STATUS[ref.status]
    picked = {"doi": None}
    decision = state.decisions.get(ref.n)
    solved = decision is not None
    expanded = not solved and state.review_expanded_n == ref.n
    row_border = pal["border"] if solved else "#cdcac3"
    row_accent = pal["dot"]
    row_bg = pal["bg"] if solved else "#fff"

    with ui.column().style(
        f"border:1px solid {row_border}; border-left:3px solid {row_accent}; "
        f"border-radius:5px; background:{row_bg}; gap:0; width:100%;"
    ):
        with ui.row().style(
            f"padding:{'12px 15px' if expanded else '9px 15px'}; gap:10px; width:100%; "
            f"align-items:flex-start; cursor:{'default' if expanded or solved else 'pointer'};"
        ).on("click", lambda: None if solved else _expand_review(state, actions, ref.n)):
            marker = "✓ " if solved else ("▾ " if expanded else "▸ ")
            ui.label(marker + f"{ref.n:02d}").classes("rc-mono").style(
                f"color:{theme.TEXT_QUIET}; font-size:11px; white-space:nowrap;"
            )
            with ui.column().style("flex:1 1 auto; gap:4px; min-width:0;"):
                ui.label(ref.raw).style(f"color:{theme.TEXT_STRONG}; font-size:12.5px;")
                if solved:
                    ui.label(f"{decision['label']} · {decision['stamp']}").classes(
                        "rc-mono"
                    ).style("color:#4f7658; font-size:10.5px;")
                elif expanded:
                    ui.label(_reason_for(ref)).classes("rc-mono").style(
                        f"color:{theme.TEXT_FAINT}; font-size:10.5px;"
                    )
                    # Evidence for the decision this screen exists to take. A reference no
                    # automated match could confirm reads differently depending on whether
                    # the manuscript leans on it repeatedly or never mentions it at all,
                    # and neither reading is available anywhere else in the queue.
                    ui.label(cited.label).classes("rc-mono").style(
                        f"color:{theme.BLOCKER_FG if cited.uncited else theme.TEXT_FAINT}; "
                        "font-size:10.5px;"
                    )
                    render_citation_context(state, actions, ref.n)
                    with ui.row().style("gap:10px; align-items:center;"):
                        ui.button(
                            "Copy reference",
                            on_click=lambda: (ui.clipboard.write(ref.raw), ui.notify("Copied")),
                        ).props("flat no-caps").style(
                            f"color:{theme.ACCENT}; text-decoration:underline; font-size:11px; padding:0;"
                        )
                        ui.link(
                            "Search on the web",
                            _GOOGLE_SEARCH_URL.format(query=quote_plus(ref.raw)),
                            new_tab=True,
                        ).style(f"color:{theme.ACCENT}; font-size:11px;")
            with ui.column().style("gap:5px; align-items:flex-end;"):
                if solved:
                    resolved_status = decision.get("status", ref.status)
                    with ui.row().style("align-items:center; gap:8px; flex-wrap:nowrap;"):
                        ui.button(
                            "↶ Reopen", on_click=lambda: _reopen(state, actions, ref.n)
                        ).props("flat no-caps").style(
                            f"color:{theme.ACCENT}; font-size:11px; font-weight:600; "
                            "text-decoration:underline; padding:1px 3px; min-height:0;"
                        )
                        ui.html(
                            theme.status_badge_html(
                                STATUS_LABELS_SHORT[resolved_status],
                                theme.STATUS[resolved_status],
                                "font-size:11px;",
                            ),
                            tag="div",
                        )
                else:
                    ui.html(
                        theme.status_badge_html(
                            STATUS_LABELS_SHORT[ref.status], pal, "font-size:11px;"
                        ),
                        tag="div",
                    )
                ui.label(f"conf {ref.confidence:.2f}" if ref.confidence else "conf —").classes("rc-mono").style(
                    f"color:{theme.TEXT_MUTED}; font-size:11px;"
                ).tooltip(CONFIDENCE_TOOLTIP)

        if not expanded:
            return

        # Candidates
        with ui.column().style(
            "background:#fbfaf8; border-top:1px solid #f0eeea; "
            "padding:10px 15px; gap:6px; width:100%;"
        ):
            ui.label("BEST CANDIDATES").classes("rc-mono").style(
                f"color:{theme.TEXT_FAINT}; font-size:10px; font-weight:600; letter-spacing:1px;"
            )
            if not ref.candidates:
                ui.label("No candidates above the similarity floor.").style(f"color:{theme.TEXT_FAINT}; font-size:12px;")
            else:
                candidate_buttons: dict[str, ui.button] = {}

                def style_for(selected: bool) -> str:
                    border = "#33578a" if selected else "#e4e1db"
                    bg = "#eef2f8" if selected else "#fff"
                    return (
                        f"text-align:left; padding:8px 10px; border-radius:4px; border:1px solid {border}; "
                        f"background:{bg}; width:100%; justify-content:flex-start;"
                    )

                def pick(doi: str) -> None:
                    picked["doi"] = doi
                    for cand_doi, btn in candidate_buttons.items():
                        btn.style(style_for(cand_doi == doi))
                    confirm_btn.props(remove="disable")
                    confirm_btn.style(
                        theme.PRIMARY_BUTTON + "padding:6px 12px; font-size:11.5px; cursor:pointer;"
                    )

                for cand in ref.candidates:
                    btn = ui.button(on_click=lambda _e, d=cand.doi: pick(d)).props("no-caps flat align=left").style(
                        style_for(False)
                    )
                    candidate_buttons[cand.doi] = btn
                    with btn:
                        _render_candidate(cand)

        # Actions
        with ui.row().style(
            f"padding:11px 15px; gap:8px; width:100%; align-items:center; flex-wrap:wrap; "
            f"background:#f6f5f2; border-top:1px solid {theme.BORDER};"
        ):
            confirm_btn = ui.button(
                "Confirm candidate",
                on_click=lambda: _confirm(state, actions, ref, picked),
            ).props("disable no-caps").style(
                theme.PRIMARY_BUTTON_DISABLED
                + "padding:6px 12px; font-size:11.5px; opacity:1; cursor:not-allowed;"
            )

            correct_btn = ui.button("Correct manually").props("no-caps").style(
                theme.SECONDARY_BUTTON + "padding:6px 12px; font-size:11.5px;"
            )

            comment_btn = ui.button("Add comment").props("flat no-caps").style(
                f"color:{theme.TEXT_MUTED}; padding:6px 8px; font-size:11.5px; font-weight:500;"
            )

            ui.button(
                "Mark not findable",
                on_click=lambda: _decide(
                    state,
                    actions,
                    ref,
                    "halluc",
                    "marked not findable",
                    comment_box,
                    title="—",
                    doi="no match",
                    citations=None,
                    retracted=None,
                    retraction_doi="",
                    source="Manual review",
                    queried=_dt.datetime.now().strftime("%H:%M"),
                    dup_of=None,
                ),
            ).props("no-caps").style(
                "border:1px solid #c98a7c; background:#fbeee9; color:#95311d; "
                "padding:6px 12px; border-radius:4px; font-size:11.5px; font-weight:600; "
                "margin-left:auto;"
            )

        with ui.column().style("padding:0 15px 13px; width:100%; gap:9px;"):
            comment_box = ui.textarea(placeholder="Reason for the manual decision (optional)").style(
                f"border:1px solid #cdcac3; border-radius:4px; color:{theme.TEXT}; background:#fff; "
                "font-size:12px; width:100%;"
            )
            comment_box.set_visibility(False)
            comment_btn.on_click(lambda: comment_box.set_visibility(not comment_box.visible))

            form_wrap = ui.column().style(
                f"width:100%; gap:9px; padding:10px; border:1px solid {theme.BORDER_SOFT}; "
                "border-radius:4px; background:#faf9f7;"
            )
            correct_btn.on_click(lambda: form_wrap.set_visibility(not form_wrap.visible))

        with form_wrap:
            ui.label("MANUAL METADATA").classes("rc-mono").style(
                f"color:{theme.TEXT_FAINT}; font-size:10px; font-weight:600; letter-spacing:1px;"
            )
            inputs: dict[str, ui.input] = {}
            with ui.element("div").style(
                "display:grid; grid-template-columns:minmax(0, 1.2fr) minmax(0, 1fr) 110px; "
                "column-gap:12px; row-gap:8px; width:100%; min-width:0;"
            ):
                field_layout = [
                    ("Title", "grid-column:1 / -1;"),
                    ("DOI", "grid-column:1;"),
                    ("Author", "grid-column:2;"),
                    ("Year", "grid-column:3;"),
                ]
                for field_name, placement in field_layout:
                    with ui.column().style(
                        f"gap:3px; width:100%; min-width:0; {placement}"
                    ):
                        ui.label(field_name).style(
                            f"color:{theme.TEXT_MUTED}; font-size:11px;"
                        )
                        edit = ui.input().props("dense outlined").style(
                            f"color:{theme.TEXT}; background:#fff; font-size:11.5px; "
                            "width:100%; min-width:0;"
                        )
                        inputs[field_name] = edit
            with ui.row().style("gap:8px; align-items:center;"):
                ui.button(
                    "Save correction", on_click=lambda: _save_form(state, actions, ref, inputs, comment_box)
                ).props("no-caps").style(
                    theme.PRIMARY_BUTTON + "padding:6px 13px; font-size:11.5px;"
                )
                ui.button("Cancel", on_click=lambda: form_wrap.set_visibility(False)).props(
                    "no-caps"
                ).style(
                    theme.SECONDARY_BUTTON + "padding:6px 13px; font-size:11.5px;"
                )
        form_wrap.set_visibility(False)


def _confirm(state: AppState, actions, ref: ReferenceResult, picked: dict) -> None:
    if picked["doi"]:
        candidate = next(candidate for candidate in ref.candidates if candidate.doi == picked["doi"])
        _decide(
            state,
            actions,
            ref,
            "verified",
            f"manually confirmed (DOI {candidate.doi})",
            None,
            title=candidate.title,
            doi=candidate.doi,
            confidence=candidate.similarity,
            year=candidate.year,
            source=candidate.source or "Manual review",
            outlet=candidate.outlet,
            queried=_dt.datetime.now().strftime("%H:%M"),
            dup_of=None,
        )


def _save_form(state: AppState, actions, ref: ReferenceResult, inputs: dict, comment_box) -> None:
    filled = [f"{name}: {edit.value}" for name, edit in inputs.items() if (edit.value or "").strip()]
    detail = f" ({', '.join(filled)})" if filled else ""
    overrides: dict = {
        "source": "Manual review",
        "queried": _dt.datetime.now().strftime("%H:%M"),
        "dup_of": None,
    }
    if (inputs["Title"].value or "").strip():
        overrides["title"] = inputs["Title"].value.strip()
    if (inputs["DOI"].value or "").strip():
        overrides["doi"] = inputs["DOI"].value.strip()
    if (inputs["Year"].value or "").strip().isdigit():
        overrides["year"] = int(inputs["Year"].value.strip())
    _decide(
        state,
        actions,
        ref,
        "verified",
        f"manually corrected{detail}",
        comment_box,
        **overrides,
    )


def _decide(
    state: AppState,
    actions,
    ref: ReferenceResult,
    status: str,
    label: str,
    comment_box,
    **overrides,
) -> None:
    comment = (comment_box.value or "").strip() if comment_box is not None else ""
    full_label = f"{label} — {comment}" if comment else label
    state.review_originals.setdefault(ref.n, ref)
    updated = dataclasses.replace(
        ref,
        status=status,
        manual_note=full_label,
        **overrides,
    )
    state.results = [updated if item.n == ref.n else item for item in state.results]
    state.stamp_decision(ref.n, full_label)
    state.decisions[ref.n]["status"] = status
    review_refs = state.review_refs()
    remaining = [candidate for candidate in review_refs if candidate.n not in state.decisions]
    later = [candidate for candidate in remaining if candidate.n > ref.n]
    next_ref = (later or remaining)[0] if remaining else None
    if next_ref is not None:
        state.review_expanded_n = next_ref.n
        state.review_page = next(
            index for index, candidate in enumerate(review_refs) if candidate.n == next_ref.n
        ) // PAGE_SIZE
    else:
        state.review_expanded_n = None
    actions.refresh_content()


def _reopen(state: AppState, actions, n: int) -> None:
    original = state.review_originals.pop(n, None)
    if original is not None:
        state.results = [original if item.n == n else item for item in state.results]
    state.decisions.pop(n, None)
    state.review_expanded_n = n
    actions.refresh_content()
