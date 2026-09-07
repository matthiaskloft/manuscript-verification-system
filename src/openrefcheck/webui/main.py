"""App shell: sidebar navigation + content area.

Port of the PySide6 MainWindow (openrefcheck.gui.main_window) to a NiceGUI page.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from nicegui import ui

from openrefcheck.gui.sidebar_copy import configured_mode, dev_mode_enabled
from openrefcheck.webui import theme
from openrefcheck.webui.components.sidebar import build_sidebar
from openrefcheck.webui.pages import manual_review, references, report_export, summary, upload
from openrefcheck.webui.state import AppState

SCREENS = {
    "upload": upload,
    "refs": references,
    "review": manual_review,
    "summary": summary,
    "export": report_export,
}


def _show_internal_errors() -> bool:
    """Whether a render traceback may be drawn on the page.

    True only where the person looking at the screen is the person running the process:
    the local desktop/`local` deployment, or an explicit OPENREFCHECK_DEV opt-in. A `demo` or
    `prod` deployment serves strangers, and a stack trace is server internals.
    """
    return dev_mode_enabled() or configured_mode() == "local"


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
                #
                # The traceback goes to the log unconditionally, and onto the page only
                # where the reader is the operator. On the desktop app they are the same
                # person and the trace is the whole point. On a hosted instance they are
                # not: an anonymous visitor would otherwise be handed absolute server
                # paths, the package layout, dependency versions, and whatever the
                # exception text happens to carry — from any render bug at all.
                try:
                    SCREENS[state.screen].render(state, actions)
                except Exception as exc:  # noqa: BLE001 - intentionally broad, see above
                    import traceback

                    logging.getLogger(__name__).exception(
                        "Error rendering %r screen", state.screen
                    )
                    # `str(exc)` is not neutral either: the exceptions this app actually
                    # raises carry absolute paths — FileNotFoundError on a staging path,
                    # ImportError naming a site-packages location, the staging directory's
                    # own refusal messages. Gate the text on the same signal as the trace.
                    detail = f": {exc}" if _show_internal_errors() else ""
                    ui.label(f"Error rendering '{state.screen}' screen{detail}").style(
                        "color:#8c2f10; font-weight:600; padding:16px;"
                    )
                    if not _show_internal_errors():
                        ui.label(
                            "The details are in the server log."
                        ).style("color:#8c2f10; font-size:12px; padding:0 16px 16px;")
                    if _show_internal_errors():
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
