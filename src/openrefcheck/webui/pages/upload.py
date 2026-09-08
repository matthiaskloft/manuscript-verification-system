"""Upload / New Check screen — includes the Processing state in place.

Port of the PySide6 UploadScreen (openrefcheck.gui.screens.upload).
"""

from __future__ import annotations

import logging
import os
import stat
import tempfile
import time
from uuid import uuid4
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from pathlib import Path

from nicegui import background_tasks, context, events, run, ui

from openrefcheck.extraction.engine_status import ENGINE_PREFERENCE_LABELS, EngineStatus, current_engine_status
from openrefcheck.extraction.grobid import has_cold_start, wait_for_grobid
from openrefcheck.extraction.reference_list_audit import NOT_AUDITED
from openrefcheck.gui.file_info import DEMO_MANUSCRIPT_ORIGIN, SUPPORTED_SUFFIXES, load_file
from openrefcheck.gui.mock_pipeline import STAGES
from openrefcheck.gui.real_pipeline import CITATIONS_NOT_RUN, CheckResult
from openrefcheck.webui import theme
from openrefcheck.webui.check_runner import CheckRunner
from openrefcheck.webui.state import AppState

# Real, on-disk PDFs — let a demo run the actual extraction/verification pipeline
# end-to-end without the user having to find their own manuscript first. They're
# synthetic (LaTeX-generated) documents, not real published papers — see
# DEMO_MANUSCRIPT_ORIGIN's use in report_export.py for the resulting watermark.
# Bundled under the package (see pyproject.toml's package-data) rather than
# referenced from tests/fixtures, so they're still present in an installed
# (non-editable, non-repo-checkout) deployment.
#
# These used to *be* the test fixtures, byte for byte. They're now built separately by
# scripts/build_demo_assets.py and capped at a handful of references each: every entry
# in a demo document becomes a live Crossref/OpenAlex lookup, so a 30-entry demo made
# a first-time visitor wait for 30 round-trips. Test fixtures want the opposite
# (see tests/fixtures/citation_styles/meta.json), which is why the two are no longer
# the same files.
_ASSETS_DIR = Path(__file__).resolve().parents[2] / "assets"
DEMO_GROUPS = (
    (
        "Valid documents",
        {
            "Social & behavioral · APA 7": _ASSETS_DIR / "demo_social_apa7.pdf",
            "Humanities & theology · Chicago": _ASSETS_DIR / "demo_humanities_chicago.pdf",
            "Medicine & life sciences · Vancouver": _ASSETS_DIR / "demo_medicine_vancouver.pdf",
            "Computer science & engineering · IEEE": _ASSETS_DIR / "demo_cs_ieee.pdf",
            "Other disciplines · APA 7": _ASSETS_DIR / "demo_other_apa7.pdf",
        },
    ),
    (
        "Corrupted documents",
        {
            "Page-break reference": _ASSETS_DIR / "demo_page_break.pdf",
            "Running header": _ASSETS_DIR / "demo_running_header.pdf",
            "Two-column references": _ASSETS_DIR / "demo_two_column.pdf",
        },
    ),
)

_LOG = logging.getLogger(__name__)


def _user_facing_error(summary: str, detail: object) -> str:
    """`summary`, plus `detail` only where the reader is the operator.

    The detail here is `str(exc)`, which for this app's exceptions routinely carries
    absolute paths — a staging path from FileNotFoundError, a site-packages path from
    ImportError. On the desktop app the reader is the person running the process and
    withholding it just makes their own failure harder to diagnose; on a server they are
    a stranger. Same signal as the render handler in webui.main, so the two cannot drift.
    """
    from openrefcheck.webui.main import _show_internal_errors

    if _show_internal_errors():
        return f"{summary}: {detail}"
    return f"{summary}. The details are in the server log."

_UPLOAD_DIR = Path(tempfile.gettempdir()) / "openrefcheck-uploads"

# Where uploads were staged before the package was renamed. A machine that ran the old
# build can still have manuscripts sitting here, and nothing else will ever remove them:
# the sweep below only knows about the current directory. Swept too, so the rename does
# not quietly turn "deleted when the check finishes or the tab closes" into "left on
# disk forever". Delete this once no installation predating the rename remains.
_LEGACY_UPLOAD_DIR = Path(tempfile.gettempdir()) / "refcheck-uploads"

# Cloud Run's demo deployment has no auth in front of the upload endpoint (see
# docs/demo-deployment-decision.md), so an unbounded upload is a cheap way to burn
# the service's memory/CPU allowance. 50 MB comfortably covers any real manuscript
# PDF/DOCX while keeping a single bad upload from being expensive.
MAX_UPLOAD_BYTES = 50 * 1024 * 1024

# How long an upload nobody is using any more may sit on disk before the next process
# start removes it. Every normal path deletes its own file (see `_cleanup_upload`'s
# callers, including the per-client disconnect handler), so anything this catches is
# the residue of a crash or a kill — where no handler ran at all. An hour is far longer
# than any check takes and far shorter than "until the container is recycled", which is
# the only alternative and is not what the demo's retention notice describes.
_STALE_UPLOAD_SECONDS = 60 * 60


def _upload_dir() -> Path:
    """The temp directory uploads are staged in, created private to this user.

    0o700 because the parent is a world-writable shared temp directory and the contents
    are unpublished manuscripts: default permissions would leave one user's upload
    readable by every other account on the machine. `mkdir` does not widen an existing
    directory's mode, so a pre-existing looser one is corrected explicitly.
    """
    # Refuse a symlink rather than following it. The parent is a world-writable shared
    # temp directory, so on a multi-user host another account can pre-create this path as
    # a link and receive every upload written through it — and the chmod below would
    # follow the link too. Unreachable in the single-tenant container; the docs describe
    # running this on a university server as well.
    if _UPLOAD_DIR.is_symlink():
        raise RuntimeError(f"{_UPLOAD_DIR} is a symlink; refusing to stage uploads there.")
    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        _UPLOAD_DIR.chmod(0o700)
    except OSError:
        # Swallowing this used to let the function return a directory it had failed to
        # secure. `mkdir(exist_ok=True)` does not touch an existing directory's mode or
        # owner, so the path can already exist owned by another account — chmod then
        # raises EPERM and every subsequent unpublished manuscript would be written
        # somewhere that account can read. Verified below instead of assumed.
        pass
    # POSIX only, and not merely because `os.getuid` is absent on Windows (it is —
    # this raised AttributeError there, breaking uploads on the platform the README
    # documents for setup). The hazard itself is POSIX-shaped: it needs a temp directory
    # shared between accounts. Windows gives each user their own under
    # %LOCALAPPDATA%\Temp, so there is no other account to pre-create the path, and
    # st_uid/st_mode do not carry meaningful values to check anyway.
    if hasattr(os, "getuid"):
        info = _UPLOAD_DIR.lstat()
        if info.st_uid != os.getuid():
            raise RuntimeError(
                f"{_UPLOAD_DIR} is owned by uid {info.st_uid}, not {os.getuid()}; "
                "refusing to stage uploads there."
            )
        if stat.S_IMODE(info.st_mode) != 0o700:
            raise RuntimeError(
                f"{_UPLOAD_DIR} is mode {stat.S_IMODE(info.st_mode):o}, not 700, and "
                "could not be corrected; refusing to stage uploads there."
            )
    return _UPLOAD_DIR


def sweep_stale_uploads(now: float | None = None) -> int:
    """Delete uploads left behind by a previous run; returns how many were removed.

    Called once at process start (see `openrefcheck.webui.main.create_app`). Without it the
    only crash-safe cleanup would be whatever the OS does to the temp directory, which on
    a long-lived container is nothing — manuscripts would accumulate for the life of the
    instance, which is exactly what the demo's retention notice says does not happen.
    """
    reference = time.time() if now is None else now
    removed = 0
    entries: list[Path] = []
    for directory in (_UPLOAD_DIR, _LEGACY_UPLOAD_DIR):
        # The same refusal `_upload_dir` makes, and it matters more here: this runs at
        # process start, before `_upload_dir` has ever been called, so it is the first
        # thing to touch these paths. Following a planted link would make the sweep
        # delete someone else's files, under our uid — the legacy path especially, since
        # nothing defends a name the current build never creates.
        try:
            if directory.is_symlink():
                continue
            entries.extend(directory.iterdir())
        except OSError:
            continue
    for entry in entries:
        try:
            # follow_symlinks=False throughout: a symlink inside the directory is not a
            # file we staged, and its age is not the age of what it points at.
            if entry.is_symlink() or not entry.is_file():
                continue
            if reference - entry.lstat().st_mtime <= _STALE_UPLOAD_SECONDS:
                continue
            entry.unlink()
            removed += 1
        except OSError:
            continue
    return removed


@dataclass
class EngineStatusView:
    """What the engine status line shows, and which refresh is allowed to set it.

    A module-level class rather than three closure variables because the rule it enforces
    is a real one and needs a test. Waiting out a cold start made this refresh long — up
    to three minutes — and a click on the engine dropdown starts another one while the
    first is still in flight. Without a sequence number the older wait finishes last and
    assigns last, so choosing "Built-in parser" during a wait showed the built-in parser
    immediately and then, minutes later, silently replaced it with the GROBID answer the
    user had just navigated away from. The label and the button disagreed, and the label
    was wrong. (PR #66's review.)

    So every refresh takes a ticket, and commits only while its ticket is still the
    newest. `invalidate` lets a caller retire the current holder without starting a
    refresh of its own, which is what a preference change needs to do *synchronously* —
    the replacement refresh is a task that has not run yet, and the stale one can resume
    in between.

    `status` and `waking` are always assigned together, never one without the other. The
    ordering test caught the version that did not: a refresh landing on a reachable engine
    set the status and left `waking` as the abandoned wait had it, so the line went on
    saying "Starting GROBID…" over an answer that had already arrived.

    `probe` answers what the engine status is, given a preference and whether to wait for
    a cold start. It is injected so this can be tested without a network or an event loop;
    `render` is what redraws the line.
    """

    probe: Callable[[str, bool], Awaitable[EngineStatus]]
    render: Callable[[], None]
    status: EngineStatus | None = None
    waking: bool = False
    _ticket: int = 0

    def invalidate(self) -> None:
        """Retire whatever refresh is in flight; its result will be dropped."""
        self._ticket += 1

    async def refresh(self, preference: str) -> None:
        self._ticket += 1
        mine = self._ticket

        found = await self.probe(preference, False)
        if mine != self._ticket:
            return
        if found.reachable or not has_cold_start():
            self.status, self.waking = found, False
            self.render()
            return

        # A deployed GROBID at zero minimum instances is started *by* the probe that just
        # failed, so one attempt cannot tell "down" from "not up yet". Show that the
        # question is still open and give it the cold start's worth of time. The await
        # keeps the screen live throughout: the file picker, the demo menu and the engine
        # dropdown all keep working while this runs.
        self.status, self.waking = found, True
        self.render()

        found = await self.probe(preference, True)
        if mine != self._ticket:
            return
        self.status, self.waking = found, False
        self.render()


def render(state: AppState, actions) -> None:
    with ui.column().style(
        "box-sizing:border-box; width:100%; max-width:760px; margin:0 auto; "
        "padding:clamp(16px, 3vw, 24px) clamp(14px, 2.5vw, 22px) 28px; gap:16px;"
    ):
        with ui.column().style("gap:6px; width:100%;"):
            ui.label("New check").style(f"font-size:22px; font-weight:600; color:{theme.TEXT};")

        _build_dropzone(state, actions)
        _build_doc_panel(state, actions)


def _build_engine_panel(state: AppState) -> None:
    """PDF extraction engine section: which engine will run (Anchor vs. GROBID), and
    a control to pin one instead of the default auto-detect.

    Only reflects the PDF path (see engine_status.current_engine_status); DOCX
    always uses Anchor regardless of GROBID reachability or this preference.
    """
    with ui.column().style(
        f"padding:9px 12px; border-bottom:1px solid {theme.BORDER_SOFT}; gap:4px; width:100%;"
    ):
        ui.label("Parsing engine").style(f"font-weight:600; font-size:12px; color:{theme.TEXT_STRONG};")
        ui.label("Select how references are extracted from PDFs.").style(
            f"color:{theme.TEXT_FAINT}; font-size:11px; line-height:1.4;"
        )

        async def probe(preference: str, waiting: bool) -> EngineStatus:
            return await run.io_bound(
                current_engine_status,
                preference,
                probe=wait_for_grobid if waiting else None,
            )

        view = EngineStatusView(probe=probe, render=lambda: status_line.refresh())

        @ui.refreshable
        def status_line() -> None:
            status, waking = view.status, view.waking
            if waking:
                # Not "not reachable": the deployed GROBID scales to zero, so the probe
                # that just failed is the one that started it. Saying it is unreachable
                # here would settle a question that is still open, and a reader who acts
                # on it runs the whole check on the fallback parser for no reason.
                ui.label("Starting GROBID — a first check after an idle period can take a minute…").style(
                    f"color:{theme.TEXT_FAINT}; font-size:11px; line-height:1.4;"
                )
                return
            if status is None:
                ui.label("Checking…").style(f"color:{theme.TEXT_FAINT}; font-size:11px;")
                return
            dot_color = theme.ACCENT if status.reachable else theme.TEXT_FAINT
            ui.html(
                f'<span style="display:inline-flex; align-items:center; gap:6px; '
                f'color:{theme.TEXT_FAINT}; font-size:11px; line-height:1.4;">'
                f'<span style="display:inline-block; flex:0 0 6px; width:6px; height:6px; '
                f'border-radius:50%; background:{dot_color};"></span>'
                f'<span>{status.name} — {status.detail}</span></span>'
            ).style("width:100%;")

        async def refresh_status() -> None:
            # current_engine_status() -> is_grobid_available() makes a real, blocking
            # network call — run it off the event loop so it doesn't freeze the whole UI
            # on every visit to this screen (reported as general "laggy" navigation, not
            # specific to any one action).
            await view.refresh(state.engine_preference)

        def pick(value: str) -> None:
            # Invalidate before anything else, synchronously. A cold-start wait already in
            # flight can outlive this click by minutes, and it must not be the thing that
            # gets the last word about an engine the user has since changed.
            view.invalidate()
            state.engine_preference = value
            engine_btn.set_text(ENGINE_PREFERENCE_LABELS[value] + " ▾")
            view.status = None
            view.waking = False
            status_line.refresh()
            background_tasks.create(refresh_status())

        # A ui.menu-backed button rather than ui.select, matching the pattern already
        # used elsewhere (e.g. manual_review.py's "Recategorize" control).
        engine_btn = ui.button(ENGINE_PREFERENCE_LABELS[state.engine_preference] + " ▾").props(
            "no-caps outline dense"
        ).style(
            f"color:{theme.TEXT}; font-size:12px; width:max-content; min-width:190px; "
            "white-space:nowrap;"
        )
        with engine_btn:
            with ui.menu():
                for key, label in ENGINE_PREFERENCE_LABELS.items():
                    ui.menu_item(label, on_click=lambda _e, k=key: pick(k)).style("font-size:12px;")
        status_line()
        background_tasks.create(refresh_status())


def _build_dropzone(state: AppState, actions) -> None:
    upload_dir = _upload_dir()

    with ui.column().style("gap:6px; width:100%;"):

        async def handle_upload(e: events.UploadEventArguments) -> None:
            if state.running:
                return
            suffix = Path(e.file.name).suffix.lower()
            if suffix not in SUPPORTED_SUFFIXES:
                ui.notify(f"Unsupported file type: {suffix or '(none)'}", type="warning")
                return
            # `max_file_size` on ui.upload is a Quasar prop — a browser-side constraint on
            # the file picker, and nothing at all to a direct POST to the upload endpoint,
            # which on the demo is public and unauthenticated. So the size is re-checked
            # here.
            #
            # Note what this does and does not bound. NiceGUI parses the whole multipart
            # body before any handler runs, spooling it to a temp file of its own, so by
            # the time `size()` can be asked the bytes are already on the instance. This
            # prevents an oversized upload from being *staged* and processed; it does not
            # prevent it from being *received*. Bounding that needs a Content-Length or
            # streaming check on the route itself, ahead of the body — worth doing if the
            # demo is ever exposed without an instance cap in front of it.
            if e.file.size() > MAX_UPLOAD_BYTES:
                ui.notify(
                    f"File too large — the limit is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
                    type="warning",
                )
                return
            # The name is client-supplied. Traversal is blocked twice over already —
            # NiceGUI strips path components, and the old `{id(e)}_` prefix fused onto
            # the first one — but both are accidents of unrelated code, and the display
            # name is carried separately anyway (`_set_file`, below). A generated name
            # depends on neither, and cannot collide the way `id()` can once one upload
            # is freed and the next reuses its address.
            dest = upload_dir / f"{uuid4().hex}{suffix}"
            # `save` streams; `write_bytes(await read())` held the whole manuscript in
            # memory a second time, on a service sized at 512 MiB–1 GiB.
            await e.file.save(dest)
            # Anything that stops this file from becoming `state.loaded` also stops
            # anything from ever deleting it: the disconnect handler reads
            # `state.loaded`, and no check will run. An unreadable or malformed upload
            # would otherwise sit in the staging directory until the next process start,
            # which on a long-lived instance is days — against a disclaimer that promises
            # the visitor it goes when the check finishes or the tab closes.
            staged = False
            try:
                staged = _set_file(state, actions, dest, display_name=e.file.name)
            finally:
                if not staged:
                    _cleanup_upload(dest)

        def handle_rejected(_e: events.UiEventArguments) -> None:
            ui.notify(
                f"File too large — the limit is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
                type="warning",
            )

        upload = ui.upload(
            on_upload=handle_upload,
            on_rejected=handle_rejected,
            max_file_size=MAX_UPLOAD_BYTES,
            auto_upload=True,
            label="Drop a file here",
        ).props(
            'accept=".pdf,.docx" flat hide-upload-btn'
        ).classes("rc-upload rc-dropzone").style(
            "width:100%; height:156px; min-height:156px; flex:0 0 156px;"
        )

        fixture_btn = ui.button("Load demo PDF ▾").props("flat no-caps").style(
            f"color:{theme.ACCENT}; align-self:center; padding:6px 12px;"
        )
        with fixture_btn:
            with ui.menu():
                for group_index, (group_label, demos) in enumerate(DEMO_GROUPS):
                    if group_index:
                        ui.separator()
                    ui.label(group_label).style(
                        f"padding:7px 16px 4px; color:{theme.TEXT_FAINT}; "
                        "font-size:10px; font-weight:700; letter-spacing:.04em; "
                        "text-transform:uppercase;"
                    )
                    for label, path in demos.items():
                        ui.menu_item(
                            label,
                            on_click=lambda _e, demo_path=path: _load_demo(
                                state, actions, demo_path
                            ),
                        ).style("font-size:12px;")


def _cleanup_upload(path: Path) -> None:
    """Remove a temp file we wrote under _UPLOAD_DIR, once it's no longer needed.

    The containment check is what keeps this from deleting a *demo* asset, which is
    loaded from the installed package rather than staged here, and is the same file for
    every visitor.
    """
    try:
        if path.is_relative_to(_UPLOAD_DIR):
            path.unlink(missing_ok=True)
    except OSError:
        pass


def register_session_cleanup(state: AppState) -> None:
    """Delete this client's staged upload when its browser session ends.

    A check that finishes deletes its own file, but that is only one of the ways a
    session ends. A visitor who uploads and closes the tab, whose check fails to find a
    bibliography, or who cancels, previously left the manuscript on the server with
    nothing left to remove it — the demo's own retention notice promising otherwise.

    Registered once per client (from `main.build_page`), not per visit to this screen,
    which would stack a handler per navigation.
    """
    try:
        client = context.client
    except Exception:  # noqa: BLE001 - no client context (tests, scripts): nothing to bind to
        return

    def _drop() -> None:
        # NiceGUI invokes disconnect handlers synchronously the moment a websocket
        # drops (client.handle_disconnect), *before* the reconnect grace period that
        # guards its own client deletion. So this fires on a laptop sleeping, a mobile
        # network changing, a throttled background tab — not only on a closed tab, and
        # the AppState survives the reconnect.
        #
        # Deleting the file underneath a running check is therefore a live hazard rather
        # than a theoretical one: a GROBID cold start alone is documented here at up to
        # three minutes. Whether it breaks depends on whether the pipeline had already
        # opened the path, so the failure would be intermittent and timing-dependent.
        # The check's own terminal callbacks delete the file, so skipping here loses
        # nothing except the race.
        if state.running:
            return
        if state.loaded is not None:
            _cleanup_upload(state.loaded.path)

    client.on_disconnect(_drop)


def _set_loaded(state: AppState, loaded: LoadedFile) -> None:
    if state.loaded is not None:
        _cleanup_upload(state.loaded.path)
    state.loaded = loaded
    state.results = []
    # A new manuscript starts from nothing, the citation fields included: a match, an
    # artifact or a run status left over from the previous document would be shown
    # against this one's references, and the artifact is raw manuscript text.
    state.citation_matches = ()
    state.truncated_from = None
    state.citation_run_status = CITATIONS_NOT_RUN
    state.document_artifact = None
    state.audit = NOT_AUDITED
    # How far each passage was unfolded resets with them: those are positions into the
    # previous document's text and mean nothing against this one.
    state.expanded_contexts = set()
    state.expanded_place_lists = set()
    _refresh_doc_panel(state)


def _set_file(
    state: AppState, actions, path: Path, *, display_name: str | None = None
) -> bool:
    """Load `path` into the session. True when the session took ownership of the file.

    The return value is what tells the caller whether anything will ever delete this
    file: only a load that reaches `_set_loaded` puts it somewhere the disconnect
    handler and the check's own cleanup can see.
    """
    try:
        loaded = load_file(path)
    except OSError as exc:
        _LOG.warning("Could not read upload %s: %s", path, exc)
        ui.notify(_user_facing_error("Could not read that file", exc), type="negative")
        return False
    if display_name is not None:
        loaded = replace(loaded, name=display_name)
    _set_loaded(state, loaded)
    return True


def _load_demo(state: AppState, actions, path: Path) -> None:
    if state.running:
        return
    if not path.exists():
        ui.notify(f"Demo manuscript not found at {path}", type="negative")
        return
    try:
        loaded = load_file(path, origin=DEMO_MANUSCRIPT_ORIGIN)
    except OSError as exc:
        _LOG.warning("Could not read demo manuscript %s: %s", path, exc)
        ui.notify(
            _user_facing_error("Could not read that demo manuscript", exc), type="negative"
        )
        return
    _set_loaded(state, loaded)


def _build_doc_panel(state: AppState, actions) -> None:
    with ui.column().classes("rc-panel").style("padding:0; gap:0; height:100%; width:100%;"):
        _build_engine_panel(state)

        ui.label("Loaded document").style(
            f"padding:9px 12px 0; font-weight:600; font-size:12px; color:{theme.TEXT_STRONG}; width:100%;"
        )

        @ui.refreshable
        def body() -> None:
            if state.running:
                _render_processing(state)
            elif state.loaded is not None:
                _render_info(state.loaded)
            else:
                ui.label(
                    'No file loaded yet. "Start Check" becomes active once a document is present.'
                ).style(f"padding:14px; color:{theme.TEXT_FAINT}; font-size:12.5px;")

        body()
        state.upload_body_refresh = body.refresh  # type: ignore[attr-defined]

        with ui.column().style(f"border-top:1px solid {theme.BORDER_SOFT}; padding:10px 12px; gap:6px; width:100%;"):

            @ui.refreshable
            def footer_buttons() -> None:
                has_file = state.loaded is not None
                if not has_file:
                    ui.button("Start Check").props("disable no-caps").style(theme.PRIMARY_BUTTON_DISABLED + "width:100%;")
                elif state.running:
                    ui.button(
                        "Cancel", on_click=lambda: _cancel_check(state, actions)
                    ).props("no-caps").style(
                        theme.SECONDARY_BUTTON + "width:100%; padding:9px;"
                    )
                else:
                    ui.button(
                        "Start Check", on_click=lambda: _start_check(state, actions)
                    ).props("no-caps").style(theme.PRIMARY_BUTTON + "width:100%; padding:9px;")

            footer_buttons()
            state.upload_footer_refresh = footer_buttons.refresh  # type: ignore[attr-defined]


def _render_info(loaded: LoadedFile) -> None:
    with ui.column().style("padding:10px 12px; gap:8px;"):
        ui.label(loaded.name).classes("rc-mono").style(
            f"box-sizing:border-box; width:100%; padding:8px 10px; border:1px solid {theme.BORDER_SOFT}; "
            f"border-radius:4px; background:{theme.SIDEBAR_BG}; color:{theme.TEXT}; "
            "font-size:12px; font-weight:600; overflow-wrap:anywhere;"
        )
        with ui.grid(columns=2).style("column-gap:14px; row-gap:6px; width:auto;"):
            for key, value in [("Size", loaded.size_label), ("Pages", loaded.pages_label), ("Source", loaded.origin)]:
                ui.label(key).style(f"color:{theme.TEXT_FAINT}; font-size:12px;")
                ui.label(value).style(f"color:{theme.TEXT_MUTED}; font-size:12px;")


def _render_processing(state: AppState) -> None:
    with ui.column().style("box-sizing:border-box; width:100%; padding:14px; gap:13px;"):
        ui.label(state.loaded.name if state.loaded else "").style(
            f"font-size:13px; font-weight:500; color:{theme.TEXT};"
        )
        # The real pipeline's extraction step (extract_references — a single blocking
        # GROBID call or pymupdf4llm conversion, see real_pipeline.py/check_runner.py)
        # has no partial progress to report: on_progress only fires once verification
        # starts. state.total stays 0 for the whole extraction stage, which would
        # otherwise render as a stuck "0 % / 0 of 0 references processed" — reading as
        # frozen rather than "still parsing". An indeterminate bar and stage-specific
        # text make clear this stage is running, just without a countable fraction.
        parsing = state.total == 0
        with ui.row().style("width:100%; justify-content:space-between;"):
            ui.label(STAGES[state.stage_index]).style(f"color:{theme.TEXT_MUTED}; font-size:12px;")
            if not parsing:
                pct = round(state.done * 100 / state.total)
                ui.label(f"{pct} %").classes("rc-mono").style(f"color:{theme.TEXT_MUTED}; font-size:12px;")
        if parsing:
            ui.linear_progress(show_value=False).style(
                f"width:100%; height:9px; border-radius:5px; background:{theme.SIDEBAR_BG};"
            ).props("indeterminate color=primary track-color=grey-3")
            ui.label("Parsing document — extracting the reference list…").classes("rc-mono").style(
                f"color:{theme.TEXT_FAINT}; font-size:11px;"
            )
        else:
            pct = round(state.done * 100 / state.total)
            ui.linear_progress(value=pct / 100, show_value=False).style(
                f"width:100%; height:9px; border-radius:5px; background:{theme.SIDEBAR_BG};"
            ).props("color=primary track-color=grey-3")
            ui.label(f"{state.done} of {state.total} references processed").classes("rc-mono").style(
                f"color:{theme.TEXT_FAINT}; font-size:11px;"
            )


def _start_check(state: AppState, actions) -> None:
    if state.loaded is None or state.running:
        return
    state.running = True
    state.stage_index, state.done, state.total = 0, 0, 0
    _refresh_doc_panel(state)

    def on_progress(stage_index: int, done: int, total: int) -> None:
        state.stage_index, state.done, state.total = stage_index, done, total
        _refresh_doc_panel(state)

    def on_finished(result: CheckResult) -> None:
        state.running = False
        state.results = result.references
        # Unpacked here and not fetched later: this handler deletes the uploaded file
        # immediately below, so anything the citation feature needs has to already be in
        # the bundle by the time it arrives. Nothing can be re-read from the source.
        state.citation_matches = result.citation_matches
        state.citation_run_status = result.citation_run_status
        state.document_artifact = result.artifact
        state.audit = result.audit
        state.truncated_from = result.truncated_from
        state.decisions = {}
        state.review_originals = {}
        # A status filter/sort/expansion left over from a previous check can otherwise
        # hide every row of a new one (e.g. "Duplicates" still selected from the last
        # document, which had one, filters an unrelated new result set down to zero
        # rows — cards show data but the table looks blank).
        state.ref_tab = "all"
        state.ref_sort_key = "n"
        state.ref_sort_dir = 1
        state.ref_expanded_n = None
        state.ref_page = 0
        state.review_page = 0
        if state.loaded is not None:
            _cleanup_upload(state.loaded.path)
        _refresh_doc_panel(state)
        actions.on_check_finished()

    def on_cancelled() -> None:
        state.running = False
        _refresh_doc_panel(state)

    def on_failed(message: str) -> None:
        state.running = False
        _refresh_doc_panel(state)
        _LOG.error("Reference check failed: %s", message)
        ui.notify(
            _user_facing_error("Reference check failed", message),
            type="negative", multi_line=True, close_button=True,
        )

    runner = CheckRunner(
        state.loaded,
        engine=state.engine_preference,
        on_progress=on_progress,
        on_finished=on_finished,
        on_cancelled=on_cancelled,
        on_failed=on_failed,
    )
    state.check_runner = runner  # type: ignore[attr-defined]
    runner.start()


def _cancel_check(state: AppState, actions) -> None:
    runner: CheckRunner | None = getattr(state, "check_runner", None)
    if runner is not None:
        runner.request_cancel()


def _refresh_doc_panel(state: AppState) -> None:
    if hasattr(state, "upload_body_refresh"):
        state.upload_body_refresh()  # type: ignore[attr-defined]
    if hasattr(state, "upload_footer_refresh"):
        state.upload_footer_refresh()  # type: ignore[attr-defined]
