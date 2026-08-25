"""NiceGUI entry point for the local reference-checker (Phase A / Stufe 0-1)."""

from __future__ import annotations

import logging
import os
import sys

from nicegui import app, core, ui

from refcheck.webui.main import create_app


def main() -> None:
    # Diagnosed via the browser's own "Connection lost / message too long" toast
    # (python-socketio's default max_http_buffer_size is 1,000,000 bytes): a page
    # rendering enough reference rows — each with badges, tooltips, buttons, and
    # (on the Manual Review screen) candidate cards and a hidden correction form —
    # can produce a single websocket update larger than that limit. When it does,
    # the message is silently dropped and the socket reconnects, leaving the page
    # showing nothing new — no Python exception, no JS console error, reproducible
    # in a plain browser tab as well as the native window, which is what pointed
    # away from every WebView2/CSS/compositing theory tried before this. Must be
    # set before any client connects, so as early as possible.
    core.sio.eio.max_http_buffer_size = 20_000_000

    create_app()
    # pywebview's Windows edgechromium backend logs WebView2-level events (most
    # importantly, a CoreWebView2 initialization failure — the exact "window
    # opens, nothing ever loads, no crash" failure mode reported for this app)
    # through the standard `logging` module under the name "pywebview", not by
    # raising an exception or writing to the window itself. Nothing in this app
    # configured that logger before, so on a machine where nothing else sets up
    # root logging handlers, those messages could go nowhere. Attach an explicit
    # handler so an init failure becomes visible instead of silent.
    pywebview_logger = logging.getLogger("pywebview")
    pywebview_logger.setLevel(logging.DEBUG)
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(logging.Formatter("[pywebview] %(levelname)s %(message)s"))
    pywebview_logger.addHandler(_handler)

    # pywebview auto-selects a Windows GUI backend and will silently fall back to
    # the legacy "mshtml" (old-IE/Trident) engine if the Microsoft Edge WebView2
    # Runtime isn't installed or detected — mshtml can't run this app's Vue3/Quasar
    # JS at all, which shows up as a permanently blank native window with no error
    # and no working right-click/F12 devtools (that's edgechromium/CEF-only). Pin
    # the backend explicitly so a missing WebView2 Runtime raises a clear startup
    # error instead of degrading silently into that blank-window failure mode.
    app.native.start_args["gui"] = "edgechromium"
    if os.environ.get("REFCHECK_NATIVE_DEBUG", "").strip().lower() in {"1", "true", "yes"}:
        # Opens the native window's devtools (right-click -> Inspect, or F12) so a
        # blank-content-area report can be diagnosed from the actual JS console
        # instead of guessing — see REFCHECK_NATIVE_DEBUG in README.md.
        app.native.start_args["debug"] = True
    ui.run(
        title="Reference Checker (MVP)",
        native=True,
        window_size=(1180, 780),
        reload=False,
        reconnect_timeout=120.0,
    )


if __name__ in {"__main__", "__mp_main__"}:
    main()
