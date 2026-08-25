"""Async port of the PySide6 QThread-based CheckWorker.

Runs the real extraction/verification pipeline (real_pipeline.run_real_pipeline) for
any loaded file, including the bundled demo manuscript (see upload.py).

The real pipeline makes blocking HTTP calls, so it runs on a background thread; its
progress callback hands events back to the asyncio event loop via
`loop.call_soon_threadsafe`, which is the only thread-safe way to touch NiceGUI's UI
state from outside the event loop.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable

from nicegui import context

from refcheck.extraction.engine_status import ENGINE_AUTO
from refcheck.gui.file_info import LoadedFile
from refcheck.gui.real_pipeline import BibliographyNotFoundError, CheckResult, run_real_pipeline


class CheckRunner:
    def __init__(
        self,
        loaded_file: LoadedFile,
        *,
        engine: str = ENGINE_AUTO,
        on_progress: Callable[[int, int, int], None],
        on_finished: Callable[[CheckResult], None],
        on_cancelled: Callable[[], None],
        on_failed: Callable[[str], None],
    ) -> None:
        self._loaded_file = loaded_file
        self._engine = engine
        self._on_progress = on_progress
        self._on_finished = on_finished
        self._on_cancelled = on_cancelled
        self._on_failed = on_failed
        self._cancel_requested = False
        self._task: asyncio.Task | None = None
        # UI callbacks fire from a background asyncio task, which has no NiceGUI "slot"
        # context of its own; capture the client here (while we're still in the click
        # handler's context) so `_run` can re-enter it explicitly.
        self._client = context.client

    def request_cancel(self) -> None:
        if self._cancel_requested:
            return
        self._cancel_requested = True
        # Extraction is a blocking library/HTTP call running in a worker thread and
        # Python cannot safely terminate that thread mid-call. Cancel the asyncio
        # coordinator immediately so the UI returns to its ready state; the detached
        # worker may finish parsing, but its queued result is no longer consumed and
        # can never update the UI or start API verification.
        if self._task is not None and not self._task.done():
            self._task.cancel()

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        with self._client:
            try:
                await self._run_real()
            except asyncio.CancelledError:
                self._on_cancelled()

    async def _run_real(self) -> None:
        self._on_progress(0, 0, 0)
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def progress_cb(done: int, total: int) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, ("progress", done, total))

        def is_cancelled() -> bool:
            return self._cancel_requested

        def worker() -> None:
            try:
                result = run_real_pipeline(
                    self._loaded_file, engine=self._engine, on_progress=progress_cb, is_cancelled=is_cancelled
                )
            except BibliographyNotFoundError as exc:
                loop.call_soon_threadsafe(queue.put_nowait, ("failed", str(exc)))
                return
            except Exception as exc:  # unsupported file, corrupt PDF/DOCX, etc.
                loop.call_soon_threadsafe(queue.put_nowait, ("failed", str(exc)))
                return
            loop.call_soon_threadsafe(queue.put_nowait, ("done", result))

        threading.Thread(target=worker, daemon=True).start()

        while True:
            event = await queue.get()
            kind = event[0]
            if kind == "progress":
                _, done, total = event
                self._on_progress(1, done, total)
            elif kind == "done":
                _, result = event
                if self._cancel_requested:
                    self._on_cancelled()
                else:
                    done = len(result.references)
                    self._on_progress(2, done, done)
                    self._on_finished(result)
                return
            elif kind == "failed":
                _, message = event
                self._on_failed(message)
                return
