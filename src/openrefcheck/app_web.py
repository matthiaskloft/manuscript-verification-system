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

from openrefcheck.gui.deployment import MODES
from openrefcheck.gui.sidebar_copy import DEPLOYMENT_MODE_ENV
from openrefcheck.webui.main import create_app


def main() -> None:
    # A server is not a local install, and the disclaimer must not claim it is.
    #
    # `configured_mode()` falls back to "local" when OPENREFCHECK_DEPLOYMENT_MODE is
    # unset, and local-mode copy tells the visitor "This document stays on your device."
    # On a server that is false: their manuscript was uploaded and processed here. An
    # operator who forgets the variable — a fresh deploy, a service whose env vars were
    # not carried over, a container run by hand — would otherwise publish that claim
    # with nothing failing and nothing warning, because an absent variable is not an
    # invalid one.
    #
    # So the entry point supplies the default instead of the config layer, since it is
    # the entry point that knows which kind of process this is. `demo` is the
    # conservative choice: a Phase B university deployment should still set `prod`
    # explicitly, but being told "processed on this server, don't upload confidential
    # work" when it is in fact a managed server is a survivable overstatement, and the
    # Validated rather than `setdefault`: setdefault only fires when the variable is
    # *absent*, and the realistic deploy accident is an empty one — `--set-env-vars
    # MODE=`, a Compose entry with a blank value, a template that rendered to nothing.
    # An empty string is present, so setdefault would leave it, and an unrecognised value
    # is what `configured_mode` then has to interpret. Anything this process would not
    # accept is replaced here, so the server floor holds for empty and misspelled alike;
    # an explicit valid mode still wins.
    if os.environ.get(DEPLOYMENT_MODE_ENV, "").strip().lower() not in MODES:
        os.environ[DEPLOYMENT_MODE_ENV] = "demo"

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
