"""Shared top-row metric cards row, used by the References screen (Summary keeps only
the charts, per the reconciled PySide6 spec). Port of openrefcheck.gui.metric_cards'
Qt widgets, now plain divs."""

from __future__ import annotations

from collections.abc import Callable

from nicegui import ui

from openrefcheck.gui.metric_cards import CARD_SPECS, FILTER_CARD_KEYS, ResultMetrics, card_value_note
from openrefcheck.webui import theme


def build_cards_row(metrics: ResultMetrics | None, selected_key: str, on_click: Callable[[str], None] | None = None) -> None:
    with ui.element("div").style(
        "display:grid; grid-template-columns:repeat(auto-fit, minmax(min(210px, 100%), 1fr)); "
        "gap:6px; width:100%;"
    ):
        for key, label, accent in CARD_SPECS:
            clickable = key in FILTER_CARD_KEYS and on_click is not None
            selected = clickable and key == selected_key
            border_width = 3 if selected else 2
            bg = "#f3f7fb" if selected else "#fff"
            border = accent if selected else "#cdcac3"
            value, _note = card_value_note(key, metrics) if metrics else ("—", "")

            # A retraction on this list is the one number here that is never routine, and
            # a card styled like its five neighbours is a card nobody reads. When the count
            # is non-zero it stops matching them: filled, outlined and captioned as a
            # warning. At zero it stays quiet — an alarm that is always lit is not an alarm.
            alarming = key == "retracted" and metrics is not None and metrics.n_retracted > 0
            if alarming:
                accent = theme.BLOCKER_BORDER
                border = theme.BLOCKER_BORDER
                bg = theme.BLOCKER_BG
                label = f"⚠ {label}"

            card = ui.row().style(
                f"border:1px solid {border}; border-top:{border_width}px solid {accent}; "
                f"border-radius:4px; background:{bg}; padding:10px 11px; gap:9px; min-width:0; "
                "align-items:center; flex-wrap:nowrap;"
                + ("cursor:pointer;" if clickable else "")
            )
            if not metrics:
                card.set_visibility(False)
            with card:
                ui.label(value).style(
                    f"font-size:15px; font-weight:{'700' if alarming else '600'}; "
                    f"color:{theme.BLOCKER_FG if alarming else theme.TEXT}; "
                    "white-space:nowrap; line-height:1.2;"
                )
                ui.label(label).style(
                    f"font-size:12px; color:{theme.BLOCKER_FG if alarming else theme.TEXT_MUTED}; "
                    f"font-weight:{'600' if alarming else '400'}; min-width:0; line-height:1.25;"
                )
            if clickable:
                card.on("click", lambda _e, k=key: on_click(k))
