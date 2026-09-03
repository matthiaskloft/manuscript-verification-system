"""Web entry point for the hosted demo (see docs/demo-deployment-decision.md).

Separate from openrefcheck.app:main, which opens a native pywebview window and is
only for local desktop use. This module runs the same NiceGUI app (openrefcheck.
webui.main:create_app) as an ordinary web server — no native window, no
pywebview/PySide6, so the container built from docker/nicegui/Dockerfile only
needs the base "openrefcheck" install (not the "native" extra).

Cloud Run injects the port to listen on via the PORT env var and routes to it
over HTTPS itself, so this binds to 0.0.0.0 on that port with plain HTTP.
"""

from __future__ import annotations

import os

from nicegui import core, ui

from openrefcheck.webui.main import create_app


def main() -> None:
    # See openrefcheck.app:main's identical line — python-socketio's default
    # max_http_buffer_size (1,000,000 bytes) is too small for this app's larger
    # table/report updates. Must be set before any client connects.
    core.sio.eio.max_http_buffer_size = 20_000_000

    create_app()

    port = int(os.environ.get("PORT", "8080"))
    ui.run(
        title="Reference Checker (Demo)",
        host="0.0.0.0",
        port=port,
        native=False,
        reload=False,
        # Cloud Run's WebSocket request timeout is configured separately (see
        # docs/demo-deployment-decision.md); this just controls how long the
        # NiceGUI client tries to reconnect a dropped socket before giving up.
        reconnect_timeout=120.0,
        show=False,
    )


if __name__ in {"__main__", "__mp_main__"}:
    main()
