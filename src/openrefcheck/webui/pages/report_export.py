"""Report Export screen — real HTML export (Jinja2 + embedded matplotlib), no live
preview in the app.

Port of the PySide6 ReportExportScreen (openrefcheck.gui.screens.report_export).
"""

from __future__ import annotations

import datetime as _dt
import os
from pathlib import Path

from nicegui import app, ui

from openrefcheck.gui.report_builder import (
    DEFAULT_EXPORT_INCLUDED,
    ReportMeta,
    build_html_report,
)
from openrefcheck.webui import theme
from openrefcheck.webui.state import AppState

EXPORT_ITEMS: list[tuple[str, str, str]] = [
    ("scores", "Category scores", "Verified share, duplicates, unresolved references"),
    ("confidence", "Confidence values per reference", "Automated score, 0.00–1.00"),
    ("audit_trail", "Manual review audit trail", "Decision, comment and timestamp per reference"),
    ("charts", "Charts", "Publication age, topic breadth, outlets, citation frequency (embedded PNG)"),
    ("citations", "In-text citations", "How often the manuscript cites each reference, and which it never cites"),
    (
        "citation_passages",
        "Quoted passages from the manuscript",
        "Writes the manuscript's own sentences into the report file. Off by default, and "
        "separate from showing them on screen — an exported file outlives this session.",
    ),
    ("metadata", "API and check metadata", "Check date and queried API version — results change over time"),
]


def _report_stem(state: AppState) -> str:
    return Path(state.loaded.name).stem if state.loaded else "openrefcheck-report"


def is_native_session() -> bool:
    """Whether this process is the native desktop app rather than a web server.

    Decides whether "save the report" means writing to a filesystem path or handing the
    browser a download, and the two are not interchangeable: the path is supplied by the
    client, so writing it server-side would be a remote arbitrary file write (see
    `_do_export`). Every failure mode therefore answers False — an unset
    `app.native.main_window`, a NiceGUI version without the attribute, anything raising —
    because guessing "native" wrongly opens that hole, while guessing "server" wrongly
    only offers a download to someone sitting at the machine.
    """
    try:
        return app.native.main_window is not None
    except Exception:  # noqa: BLE001 - any failure to answer means "not native"
        return False


def render(state: AppState, actions) -> None:
    # Only the native branch has somewhere to put this. On a server `Path.home()` is the
    # container's, which is not a place the person downloading the report can reach.
    if is_native_session() and not state.export_path:
        state.export_path = str(Path.home() / "Documents" / f"{_report_stem(state)}-report.html")

    with ui.column().style("padding:18px 24px 16px; gap:12px; width:100%;"):
        with ui.row().style("align-items:baseline; gap:10px; flex-wrap:wrap;"):
            ui.label("Report export").style(f"font-size:20px; font-weight:600; color:{theme.TEXT};")
            ui.label("Templated HTML report — no live preview inside the app.").style(
                f"color:{theme.TEXT_MUTED}; font-size:12px;"
            )

        with ui.row().style("gap:12px; width:100%; align-items:flex-start;"):
            with ui.column().classes("rc-panel").style("flex:1 1 0; padding:0; gap:0; min-width:0;"):
                ui.label("Included in the report").style(
                    f"padding:11px 15px; border-bottom:1px solid {theme.BORDER_SOFT}; "
                    f"font-weight:600; font-size:12px; color:{theme.TEXT_STRONG}; width:100%;"
                )
                with ui.column().style("padding:10px 15px; gap:6px; width:100%;"):
                    for key, label, note in EXPORT_ITEMS:
                        with ui.column().style("gap:0; width:100%;"):
                            box = ui.checkbox(
                                label,
                                value=state.export_included.get(
                                    key, DEFAULT_EXPORT_INCLUDED.get(key, True)
                                ),
                            ).props("dense").style(f"color:{theme.TEXT}; font-size:12px;")
                            box.on_value_change(
                                lambda e, k=key: state.export_included.__setitem__(k, e.value)
                            )
                            ui.label(note).style(
                                f"color:{theme.TEXT_FAINT}; font-size:10.5px; margin-left:26px;"
                            )

                with ui.column().style(
                    f"border-top:1px solid {theme.BORDER_SOFT}; padding:10px 15px; gap:7px; width:100%;"
                ):
                    if is_native_session():
                        _build_save_to_path(state)
                    else:
                        _build_download(state)

            with ui.column().classes("rc-panel").style(
                "width:380px; flex:0 0 380px; padding:0; gap:0;"
            ):
                ui.label("Report metadata").style(
                    f"padding:11px 15px; border-bottom:1px solid {theme.BORDER_SOFT}; "
                    f"font-weight:600; font-size:12px; color:{theme.TEXT_STRONG}; width:100%;"
                )
                with ui.column().style("padding:13px 15px; gap:7px; width:100%;"):
                    doc_name = state.loaded.name if state.loaded else "—"
                    meta_rows = [
                        ("Document", doc_name),
                        ("Check date", _dt.datetime.now().strftime("%Y-%m-%d %H:%M")),
                        ("API version", "OpenAlex v1 · Crossref v1"),
                        ("Format", "HTML (Jinja2 + matplotlib)"),
                    ]
                    with ui.element("div").style(
                        "display:grid; grid-template-columns:90px minmax(0, 1fr); "
                        "column-gap:12px; row-gap:7px; width:100%;"
                    ):
                        for key, value in meta_rows:
                            ui.label(key).style(f"color:{theme.TEXT_FAINT}; font-size:12px;")
                            ui.label(value).classes("rc-mono").style(
                                f"color:{theme.TEXT_MUTED}; font-size:11.5px; "
                                "min-width:0; overflow-wrap:anywhere;"
                            )

                if state.watermark():
                    with ui.column().style(
                        "border:1px dashed #b9976a; background:#fbf4e6; border-radius:4px; "
                        "padding:10px 11px; margin:0 15px 15px; gap:5px;"
                    ):
                        ui.label("SYNTHETIC EXAMPLE").classes("rc-mono").style(
                            f"color:{theme.BLOCKER_FG}; font-size:9.5px; font-weight:600; letter-spacing:1px;"
                        )
                        ui.label("Reports generated from the bundled synthetic manuscript are watermarked.").style(
                            f"color:{theme.TEXT_MUTED}; font-size:11.5px;"
                        )


def _build_save_to_path(state: AppState) -> None:
    """Native desktop: pick a filesystem path and write the report there.

    Only reachable when `is_native_session()` is true, i.e. the person choosing the path
    is the person sitting at the machine that would be written to. That equivalence is
    the whole basis on which `_do_export` is allowed to write an arbitrary path.
    """
    ui.label("Save to").style(f"color:{theme.TEXT_MUTED}; font-size:11px;")
    with ui.row().style("width:100%; gap:7px; align-items:center; flex-wrap:nowrap;"):
        path_input = ui.input(value=state.export_path).classes("rc-mono").style(
            f"border:1px solid #cdcac3; border-radius:4px; padding:3px 8px; "
            f"color:{theme.TEXT}; background:#fff; font-size:11.5px; "
            "flex:1 1 auto; min-width:0;"
        )
        ui.button(
            "Browse…",
            on_click=lambda: _browse_export_path(state, path_input),
        ).props("no-caps").style(
            theme.SECONDARY_BUTTON + "padding:7px 11px; font-size:11.5px; flex:0 0 auto;"
        )
    path_input.on_value_change(lambda e: setattr(state, "export_path", e.value))

    status_label = ui.label(state.export_status).classes("rc-mono").style(
        f"color:{theme.TEXT_FAINT}; font-size:11px;"
    )

    save_enabled = bool(state.results)
    ui.button(
        "Save report", on_click=lambda: _do_export(state, path_input, status_label)
    ).props("no-caps" + ("" if save_enabled else " disable")).style(
        (theme.PRIMARY_BUTTON if save_enabled else theme.PRIMARY_BUTTON_DISABLED)
        + "padding:7px 16px;"
    )


def _build_download(state: AppState) -> None:
    """Server deployments: hand the report to the browser, write nothing to disk.

    The path-based export cannot be offered here, for two independent reasons. It is a
    remote arbitrary file write — the path comes from the client, and on a public demo
    that client is any visitor, who could aim it at anything the server process can
    write. And it never worked for the user anyway: it wrote into the container's
    filesystem and reported success, while the person expecting a report received
    nothing and had no way to reach the file.
    """
    ui.label("Download").style(f"color:{theme.TEXT_MUTED}; font-size:11px;")
    ui.label(
        "The report is generated here and downloaded by your browser — nothing is "
        "stored on the server."
    ).style(f"color:{theme.TEXT_FAINT}; font-size:10.5px; line-height:1.4;")

    status_label = ui.label(state.export_status).classes("rc-mono").style(
        f"color:{theme.TEXT_FAINT}; font-size:11px;"
    )

    download_enabled = bool(state.results)
    ui.button(
        "Download report", on_click=lambda: _do_download(state, status_label)
    ).props("no-caps" + ("" if download_enabled else " disable")).style(
        (theme.PRIMARY_BUTTON if download_enabled else theme.PRIMARY_BUTTON_DISABLED)
        + "padding:7px 16px;"
    )


def _render_report(state: AppState) -> str:
    """The report HTML for the current results — the one place both exports build it."""
    meta = ReportMeta(
        document=(state.loaded.name if state.loaded else "(untitled)"),
        check_date=_dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        watermark=state.watermark(),
    )
    return build_html_report(
        state.results,
        state.decisions,
        meta,
        state.export_included,
        citation_matches=state.citation_matches,
        citation_run_status=state.citation_run_status,
        artifact=state.document_artifact,
        audit=state.audit,
    )


def _do_download(state: AppState, status_label) -> None:
    if not state.results:
        return
    html = _render_report(state)
    ui.download.content(
        html, f"{_report_stem(state)}-report.html", media_type="text/html"
    )
    message = "Report generated — check your browser's downloads."
    status_label.set_text(message)
    state.export_status = message


async def _browse_export_path(state: AppState, path_input) -> None:
    window = app.native.main_window
    if window is None:
        ui.notify("The Save As dialog is available in the native app.", type="warning")
        return

    # Deferred: only the native desktop app (the "native" extra) has pywebview
    # installed — the web-only image (docker/nicegui/Dockerfile) doesn't, and
    # app.native.main_window is always None there, so this line is never reached.
    # A top-level import crashed the whole process on startup in that image.
    import webview

    current = Path((path_input.value or state.export_path).strip())
    selected = await window.create_file_dialog(
        webview.FileDialog.SAVE,
        directory=str(current.parent),
        save_filename=current.name or "openrefcheck-report.html",
        file_types=("HTML report (*.html)", "All files (*.*)"),
    )
    if selected:
        selected_path = str(selected[0])
        state.export_path = selected_path
        path_input.set_value(selected_path)


def _do_export(state: AppState, path_input, status_label) -> None:
    # `path_str` below is written to verbatim, with no sandboxing. That is the same trust
    # boundary as a native "Save As" dialog — correct when the person choosing the path
    # is the person at the machine, and a remote arbitrary file write when they are not.
    # The screen only builds this control for a native session, and this guard repeats
    # the check at the point of the write: the render-time branch decides what to show,
    # and a UI decision is not a place to leave the only copy of a security invariant.
    if not is_native_session():
        return
    if not state.results:
        return
    path_str = (path_input.value or "").strip()
    export_path, error = _validated_export_path(path_str)
    if error:
        status_label.set_text(error)
        state.export_status = error
        ui.notify(error, type="warning")
        return
    assert export_path is not None
    normalized_path = str(export_path)
    if normalized_path != path_str:
        state.export_path = normalized_path
        path_input.set_value(normalized_path)

    try:
        export_path.write_text(_render_report(state), encoding="utf-8")
    except OSError as exc:
        message = f"Could not save: {exc}"
        status_label.set_text(message)
        state.export_status = message
        return
    message = f"Saved: report written to {export_path}"
    status_label.set_text(message)
    state.export_status = message
    ui.notify(message)


def _validated_export_path(path_str: str) -> tuple[Path | None, str | None]:
    if not path_str:
        return None, "Choose a save location first."

    try:
        path = Path(path_str).expanduser()
    except (OSError, RuntimeError, ValueError):
        return None, "The save path is not valid."

    if not path.is_absolute():
        return None, "Choose an absolute save path, or use Browse…"

    if not path.suffix:
        path = path.with_suffix(".html")
    elif path.suffix.lower() not in {".html", ".htm"}:
        return None, "The report filename must end in .html or .htm."

    if os.name == "nt":
        invalid_chars = set('<>:"/\\|?*')
        if any(char in invalid_chars for char in path.name) or path.name.rstrip(" .") != path.name:
            return None, "The report filename contains characters Windows cannot use."
        reserved = {"CON", "PRN", "AUX", "NUL"}
        reserved.update(f"COM{i}" for i in range(1, 10))
        reserved.update(f"LPT{i}" for i in range(1, 10))
        if path.stem.upper() in reserved:
            return None, "Choose a different filename; that name is reserved by Windows."

    try:
        if path.exists() and path.is_dir():
            return None, "Choose a filename, not a folder."
        if not path.parent.exists():
            return None, "The selected folder does not exist."
        if not path.parent.is_dir():
            return None, "The selected parent path is not a folder."
    except OSError:
        return None, "The save path cannot be accessed."

    return path, None
