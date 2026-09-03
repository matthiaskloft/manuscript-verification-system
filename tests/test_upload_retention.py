"""What happens to an uploaded manuscript that nobody comes back for.

The demo tells a visitor their file is deleted when the check finishes or the tab
closes (openrefcheck.gui.deployment). A finished check already deleted its own file; these
cover the paths that previously left the manuscript sitting in the container — a crash,
and the size limit that only existed in the browser.
"""

from __future__ import annotations

import os
import stat

from openrefcheck.webui.pages import upload


def test_a_file_left_by_a_crashed_run_is_swept_at_startup(tmp_path, monkeypatch):
    monkeypatch.setattr(upload, "_UPLOAD_DIR", tmp_path)
    stale = tmp_path / "123_manuscript.pdf"
    stale.write_bytes(b"unpublished work")
    old = 1_000_000.0
    os.utime(stale, (old, old))

    removed = upload.sweep_stale_uploads(now=old + upload._STALE_UPLOAD_SECONDS + 1)

    assert removed == 1
    assert not stale.exists()


def test_a_file_a_check_is_still_using_survives_the_sweep(tmp_path, monkeypatch):
    """The sweep runs at process start, but nothing guarantees it is the only process on
    the machine — a desktop user can have two windows open. Age is what separates
    "abandoned" from "in use", and an hour is far longer than any check."""
    monkeypatch.setattr(upload, "_UPLOAD_DIR", tmp_path)
    fresh = tmp_path / "456_manuscript.pdf"
    fresh.write_bytes(b"unpublished work")
    now = os.stat(fresh).st_mtime + 5

    removed = upload.sweep_stale_uploads(now=now)

    assert removed == 0
    assert fresh.exists()


def test_the_sweep_survives_a_missing_directory(tmp_path, monkeypatch):
    """First start on a fresh container: nothing has created the directory yet."""
    monkeypatch.setattr(upload, "_UPLOAD_DIR", tmp_path / "not-created-yet")

    assert upload.sweep_stale_uploads() == 0


def test_the_upload_directory_is_private_to_its_owner(tmp_path, monkeypatch):
    """It lives inside a world-writable shared temp directory and holds unpublished
    manuscripts, so the default mode would expose one user's upload to every account on
    the machine."""
    target = tmp_path / "refcheck-uploads"
    monkeypatch.setattr(upload, "_UPLOAD_DIR", target)

    created = upload._upload_dir()

    assert created.is_dir()
    assert stat.S_IMODE(created.stat().st_mode) == 0o700


def test_an_existing_world_readable_directory_is_tightened(tmp_path, monkeypatch):
    """mkdir(exist_ok=True) does not touch an existing directory's mode, so a directory
    left behind by an earlier version — or planted by another user — would keep it."""
    target = tmp_path / "refcheck-uploads"
    target.mkdir(mode=0o777)
    monkeypatch.setattr(upload, "_UPLOAD_DIR", target)

    upload._upload_dir()

    assert stat.S_IMODE(target.stat().st_mode) == 0o700


def test_cleanup_refuses_paths_outside_the_upload_directory(tmp_path, monkeypatch):
    """Demo manuscripts are loaded from the installed package and shared by every
    visitor; the containment check is what stops a session ending from deleting one."""
    monkeypatch.setattr(upload, "_UPLOAD_DIR", tmp_path / "uploads")
    (tmp_path / "uploads").mkdir()
    bundled = tmp_path / "assets" / "demo_social_apa7.pdf"
    bundled.parent.mkdir()
    bundled.write_bytes(b"a bundled demo")

    upload._cleanup_upload(bundled)

    assert bundled.exists()
