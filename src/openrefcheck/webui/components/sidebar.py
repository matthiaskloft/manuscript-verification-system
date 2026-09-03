"""Left navigation rail: screen switcher + deployment-mode disclaimer.

Port of the PySide6 Sidebar widget (openrefcheck.gui.sidebar).
"""

from __future__ import annotations

from collections.abc import Callable

from nicegui import ui

from openrefcheck.gui.deployment import MODES, RETENTION_NOTICE
from openrefcheck.gui.sidebar_copy import NAV_ITEMS, dev_mode_enabled, privacy_stripe_text
from openrefcheck.webui import theme
from openrefcheck.webui.state import AppState


def build_sidebar(state: AppState, on_navigate: Callable[[str], None], on_mode_change: Callable[[str], None]) -> None:
    with ui.column().classes("rc-sidebar").style(
        "width:196px; min-width:196px; height:100%; padding:14px 0; gap:2px;"
    ):
        ui.label("WORKFLOW").style(
            f"color:{theme.TEXT_FAINT}; font-size:10px; font-weight:600; letter-spacing:1px; padding:0 14px 10px;"
        )

        @ui.refreshable
        def nav_buttons() -> None:
            for key, label in NAV_ITEMS:
                active = key == state.screen
                btn = ui.button(label, on_click=lambda _e, k=key: on_navigate(k)).props("flat no-caps").classes(
                    "rc-navbtn" + (" active" if active else "")
                )
                btn.style("justify-content:flex-start;")

        nav_buttons()
        state.sidebar_nav_refresh = nav_buttons.refresh  # type: ignore[attr-defined]

        ui.element("div").style("flex:1 1 auto;")

        @ui.refreshable
        def privacy_status() -> None:
            copy = MODES[state.mode]
            pal = theme.MODE_PALETTE[state.mode]
            compact_label = {
                "local": "Local processing",
                "demo": "Demo server",
                "prod": "University server",
            }[state.mode]

            with ui.button().props('flat no-caps aria-label="Privacy and services"').style(
                f"box-sizing:border-box; width:100%; padding:10px 14px; border-top:1px solid {theme.BORDER_SOFT}; "
                f"color:{theme.TEXT_MUTED}; min-height:0; justify-content:flex-start;"
            ):
                ui.html(
                    f'<span style="display:flex; align-items:center; gap:7px; width:100%; min-height:16px; '
                    f'line-height:1; white-space:nowrap;">'
                    f'<span style="flex:0 0 7px; width:7px; height:7px; border-radius:50%; '
                    f'background:{pal["dot"]};"></span>'
                    f'<span style="display:block; font-size:11.5px; font-weight:600; line-height:1.2;">'
                    f'{compact_label}</span>'
                    f'<span style="flex:0 0 6px; width:6px; height:6px; margin-left:auto; '
                    f'border-top:1.5px solid currentColor; border-right:1.5px solid currentColor; '
                    f'transform:rotate(45deg);"></span></span>'
                ).style("width:100%;")

                with ui.menu().props('anchor="top right" self="bottom left"').style(
                    "width:300px; max-width:calc(100vw - 212px); padding:0;"
                ):
                    with ui.column().style("padding:13px; gap:8px; width:100%;"):
                        ui.label("Privacy & services").style(
                            f"font-size:12px; font-weight:700; color:{theme.TEXT_STRONG};"
                        )
                        ui.label(copy.label).style(f"font-size:10.5px; color:{theme.TEXT_FAINT};")
                        ui.label(copy.body).style(
                            f"font-size:11px; line-height:1.45; color:{theme.TEXT_MUTED};"
                        )
                        ui.separator().style(f"background:{theme.BORDER_SOFT};")
                        ui.label(privacy_stripe_text(state.mode)).style(
                            f"font-size:10.5px; line-height:1.4; color:{theme.TEXT_MUTED};"
                        )
                        with ui.grid(columns=2).style("column-gap:10px; row-gap:4px; width:100%;"):
                            for label, value in (
                                ("Outbound fields", "Title, author, DOI"),
                                ("Services", "OpenAlex v1 · Crossref v1"),
                            ):
                                ui.label(label).style(f"font-size:10.5px; color:{theme.TEXT_FAINT};")
                                ui.label(value).style(f"font-size:10.5px; color:{theme.TEXT_MUTED};")
                        if state.mode == "demo":
                            ui.label(RETENTION_NOTICE).style(
                                f"font-size:10.5px; font-style:italic; color:{theme.TEXT_MUTED};"
                            )

                        if dev_mode_enabled():
                            ui.separator().style(f"background:{theme.BORDER_SOFT};")
                            ui.label("Preview deployment mode").style(
                                f"font-size:10px; font-weight:600; color:{theme.TEXT_FAINT};"
                            )
                            with ui.row().style("gap:5px; flex-wrap:nowrap;"):
                                for key, mode_copy in MODES.items():
                                    on = key == state.mode
                                    ui.button(
                                        mode_copy.short, on_click=lambda _e, k=key: on_mode_change(k)
                                    ).props("no-caps").style(
                                        f"border:1px solid {'#33578a' if on else '#c6c3bc'}; "
                                        f"background:{'#3f6ba8' if on else '#f3f2ef'}; "
                                        f"color:{'#fff' if on else '#5c594f'}; "
                                        "font-size:10px; padding:4px 6px; border-radius:3px; min-height:0;"
                                    )

        privacy_status()
        state.sidebar_privacy_refresh = privacy_status.refresh  # type: ignore[attr-defined]
