"""App shell: sidebar navigation + content area.

Port of the PySide6 MainWindow (refcheck.gui.main_window) to a NiceGUI page.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from nicegui import ui

from refcheck.webui import theme
from refcheck.webui.components.sidebar import build_sidebar
from refcheck.webui.pages import manual_review, references, report_export, summary, upload
from refcheck.webui.state import AppState

SCREENS = {
    "upload": upload,
    "refs": references,
    "review": manual_review,
    "summary": summary,
    "export": report_export,
}


@dataclass
class Actions:
    state: AppState
    navigate: Callable[[str], None]
    refresh_content: Callable[[], None]
    on_check_finished: Callable[[], None]


def build_page() -> None:
    ui.add_head_html(f"<style>{theme.GLOBAL_CSS}</style>")
    state = AppState()
    # Bound here rather than in the Upload screen's render: this runs once per connected
    # client, where render runs again on every navigation back to that screen.
    upload.register_session_cleanup(state)

    with ui.column().style("width:100%; height:100vh; margin:0; padding:0; gap:0;"):
        # Quasar rows wrap by default. Without explicitly disabling that here,
        # long citation text can make the content pane's minimum width exceed the
        # remaining space beside the sidebar. The two panes then become separate
        # full-height flex lines, and overflow:hidden clips one of them completely.
        with ui.row().style(
            "flex:1 1 auto; width:100%; margin:0; gap:0; overflow:hidden; flex-wrap:nowrap;"
        ):
            build_sidebar(state, on_navigate=lambda k: navigate(k), on_mode_change=lambda m: set_mode(m))

            content_area = ui.column().classes("rc-content").style(
                "flex:1 1 auto; min-width:0; height:100%; overflow-y:auto; padding:0; margin:0; gap:0;"
            )

            @ui.refreshable
            def render_content() -> None:
                # A screen render raising is otherwise silently swallowed by NiceGUI's
                # refreshable machinery, leaving the content area blank with no visible
                # signal of what broke (see reported "native window blank content area"
                # issue) — surface it as plain text instead, since ui.label is already
                # known to render fine (the sidebar uses it).
                try:
                    SCREENS[state.screen].render(state, actions)
                except Exception as exc:  # noqa: BLE001 - intentionally broad, see above
                    import traceback

                    ui.label(f"Error rendering '{state.screen}' screen: {exc}").style(
                        "color:#8c2f10; font-weight:600; padding:16px;"
                    )
                    ui.label(traceback.format_exc()).classes("rc-mono").style(
                        "color:#8c2f10; font-size:11px; white-space:pre-wrap; padding:0 16px 16px;"
                    )

            def navigate(key: str) -> None:
                state.screen = key
                if hasattr(state, "sidebar_nav_refresh"):
                    state.sidebar_nav_refresh()  # type: ignore[attr-defined]
                render_content.refresh()

            def set_mode(mode: str) -> None:
                state.mode = mode
                if hasattr(state, "sidebar_privacy_refresh"):
                    state.sidebar_privacy_refresh()  # type: ignore[attr-defined]
                if state.results:
                    render_content.refresh()

            def on_check_finished() -> None:
                navigate("refs")

            actions = Actions(
                state=state,
                navigate=navigate,
                refresh_content=render_content.refresh,
                on_check_finished=on_check_finished,
            )

            with content_area:
                render_content()


def create_app() -> None:
    """Register the single-page app route. Call once at process start."""
    # Anything still staged belongs to a run that is already over — this process has no
    # clients yet. A crash or a kill is the only way a file gets here, and it is the one
    # case no per-session handler can clean up after.
    upload.sweep_stale_uploads()

    @ui.page("/")
    def index() -> None:
        build_page()
