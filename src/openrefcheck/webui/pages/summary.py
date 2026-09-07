"""Summary screen — charts only (metric cards live on References).

Port of the PySide6 SummaryScreen (openrefcheck.gui.screens.summary).
"""

from __future__ import annotations

from nicegui import ui

from openrefcheck.gui.metric_cards import compute_metrics
from openrefcheck.gui.models import ReferenceResult
from openrefcheck.gui.report_data import (
    DEFAULT_OUTLET_THRESHOLD,
    age_bin_counts,
    citation_bin_counts,
    outlet_breakdown,
    topic_breakdown,
)
from openrefcheck.webui import theme
from openrefcheck.webui.state import AppState

CHART_BLUE = "#7b93b8"
CHART_BLUE_BORDER = "#5c78a1"
CHART_GREEN = "#8a9c7d"
PLOT_TEXT_SIZE = 9  # 12 CSS px, matching the summary panel text at 96 dpi.
PLOT_FONT_FAMILY = "Segoe UI"

# Every chart panel is the same half-width cell, so the four read as one grid rather than
# as four differently-weighted claims. `min-width` is what makes them stack on a narrow
# window instead of squeezing four unreadable axes onto one line.
_PANEL = "flex:1 1 380px; min-width:min(380px, 100%); padding:13px; gap:8px;"
_PANEL_TITLE = f"font-size:12px; font-weight:600; color:{theme.TEXT_STRONG};"


def render(state: AppState, actions) -> None:
    with ui.column().style("padding:24px 30px 30px; gap:16px; width:100%;"):
        with ui.column().style("gap:0;"):
            ui.label("Summary").style(f"font-size:20px; font-weight:600; color:{theme.TEXT};")
            ui.label(state.subline()).classes("rc-mono").style(f"color:{theme.TEXT_FAINT}; font-size:11.5px;")

        if not state.results:
            ui.label("No check has been run yet.").style(f"color:{theme.TEXT_FAINT}; padding:26px; text-align:center;")
            return

        metrics = compute_metrics(state.results)
        if metrics.n_unchecked > 0:
            ui.label(
                f"API — {metrics.n_unchecked} reference(s) could not be checked and are counted as "
                "unverified, not as clean."
            ).style(
                "border:1px solid #d8a83c; background:#fdf4e2; color:#4a4843; "
                "border-radius:5px; padding:9px 13px; font-size:12px; width:100%;"
            )

        # Four half-width panels in two rows, paired by what they answer rather than by
        # the order they were built in. The top row is the shape of the literature cited —
        # both histograms, both read bands-across / references-up, so they belong side by
        # side. The bottom row is where that literature comes from — two categorical
        # breakdowns, both horizontal bars. The outlet chart used to be full width at the
        # top, which gave the least summarisable panel the most room.
        with ui.row().style("gap:14px; width:100%; align-items:stretch; flex-wrap:wrap;"):
            with ui.column().classes("rc-panel").style(_PANEL):
                ui.label("Publication age").style(_PANEL_TITLE)
                labels, counts = age_bin_counts(state.results)
                if any(counts):
                    with ui.pyplot(figsize=(4.2, 2.1), close=True) as plot:
                        ax = plot.fig.gca()
                        _strip_axes(ax)
                        ax.bar(labels, counts, color=CHART_BLUE, edgecolor=CHART_BLUE_BORDER, width=0.6)
                        ax.set_xlabel("years since publication", fontsize=PLOT_TEXT_SIZE, color=theme.TEXT_MUTED)
                        ax.set_ylabel("references", fontsize=PLOT_TEXT_SIZE, color=theme.TEXT_MUTED)
                        ax.yaxis.get_major_locator().set_params(integer=True)
                        plot.fig.tight_layout()
                else:
                    _empty_chart("No publication-year data", "No reference included a usable year.")

            with ui.column().classes("rc-panel").style(_PANEL):
                ui.label("How often the cited sources are themselves cited").style(_PANEL_TITLE)
                # It used to plot one bar per reference on a symlog axis, which answered a
                # question nobody had ("how tall is reference 14?") and became unreadable
                # past about thirty entries.
                labels, counts = citation_bin_counts(state.results)
                if any(counts):
                    with ui.pyplot(figsize=(4.2, 2.1), close=True) as plot:
                        ax = plot.fig.gca()
                        _strip_axes(ax)
                        ax.bar(labels, counts, color=CHART_BLUE, edgecolor=CHART_BLUE_BORDER, width=0.6)
                        ax.set_xlabel("times cited", fontsize=PLOT_TEXT_SIZE, color=theme.TEXT_MUTED)
                        ax.set_ylabel("references", fontsize=PLOT_TEXT_SIZE, color=theme.TEXT_MUTED)
                        ax.yaxis.get_major_locator().set_params(integer=True)
                        plot.fig.tight_layout()
                else:
                    _empty_chart(
                        "No citation-frequency data",
                        "No matched source came back with a citation count.",
                    )

        with ui.row().style("gap:14px; width:100%; align-items:stretch; flex-wrap:wrap;"):
            with ui.column().classes("rc-panel").style(_PANEL):
                threshold = DEFAULT_OUTLET_THRESHOLD

                with ui.row().style(
                    "width:100%; align-items:center; justify-content:space-between; "
                    "gap:10px; flex-wrap:wrap;"
                ):
                    ui.label("Articles cited per journal / outlet").style(_PANEL_TITLE)
                    with ui.row().style("align-items:center; gap:6px;"):
                        ui.label("More than").style(f"font-size:11px; color:{theme.TEXT_MUTED};")
                        threshold_input = ui.number(
                            value=threshold, min=0, step=1, format="%.0f"
                        ).props('dense outlined aria-label="Minimum unique citations"').classes("rc-compact-number")

                @ui.refreshable
                def outlet_chart() -> None:
                    outlet_labels, outlet_counts = outlet_breakdown(state.results, threshold)
                    if outlet_labels:
                        height = max(2.1, min(7.0, 0.32 * len(outlet_labels) + 0.8))
                        with ui.pyplot(figsize=(4.2, height), close=True) as plot:
                            ax = plot.fig.gca()
                            _strip_axes(ax)
                            ax.barh(outlet_labels, outlet_counts, color=CHART_GREEN, edgecolor="#6f8060")
                            ax.set_xlabel("unique citations", fontsize=PLOT_TEXT_SIZE, color=theme.TEXT_MUTED)
                            ax.xaxis.get_major_locator().set_params(integer=True)
                            plot.fig.tight_layout()
                    else:
                        _empty_chart(
                            "No outlets above this threshold",
                            f"No journal or outlet has more than {threshold} unique citations.",
                        )

                def update_threshold(event) -> None:
                    nonlocal threshold
                    threshold = max(0, int(event.value or 0))
                    outlet_chart.refresh()

                threshold_input.on_value_change(update_threshold)
                outlet_chart()

            with ui.column().classes("rc-panel").style(_PANEL):
                ui.label("Topic breadth").style(_PANEL_TITLE)
                t_labels, t_values = topic_breakdown(state.results)
                if t_labels and any(t_values):
                    height = max(2.1, min(7.0, 0.32 * len(t_labels) + 0.8))
                    with ui.pyplot(figsize=(4.2, height), close=True) as plot:
                        ax = plot.fig.gca()
                        _strip_axes(ax)
                        ax.barh(t_labels, t_values, color=CHART_GREEN, edgecolor="#6f8060")
                        # A work sits under up to three topics and is counted in each, so
                        # the axis is "references", not a partition of them.
                        ax.set_xlabel("references", fontsize=PLOT_TEXT_SIZE, color=theme.TEXT_MUTED)
                        ax.xaxis.get_major_locator().set_params(integer=True)
                        plot.fig.tight_layout()
                else:
                    _empty_chart(
                        "No topic data",
                        "No matched reference came back with an OpenAlex subject area.",
                    )


def _empty_chart(title: str, detail: str) -> None:
    with ui.column().style(
        f"min-height:180px; width:100%; align-items:center; justify-content:center; "
        f"gap:4px; border:1px dashed {theme.BORDER}; border-radius:4px; background:#faf9f7; "
        "padding:18px; text-align:center;"
    ):
        ui.label(title).style(f"color:{theme.TEXT_MUTED}; font-size:12px; font-weight:600;")
        ui.label(detail).style(f"color:{theme.TEXT_FAINT}; font-size:11px; max-width:340px;")


def _strip_axes(ax) -> None:
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("bottom", "left"):
        ax.spines[spine].set_color(theme.TEXT_MUTED)
    ax.tick_params(labelsize=PLOT_TEXT_SIZE, colors=theme.TEXT_MUTED)
    for label in (*ax.get_xticklabels(), *ax.get_yticklabels()):
        label.set_fontfamily(PLOT_FONT_FAMILY)
    ax.xaxis.label.set_fontfamily(PLOT_FONT_FAMILY)
    ax.yaxis.label.set_fontfamily(PLOT_FONT_FAMILY)
