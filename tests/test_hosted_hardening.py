"""What a hosted instance must not do, and what it must say when it stops short.

These pin the findings from the pre-publication review. Each is about the difference
between the desktop app, where the person at the screen is the operator, and a public
server, where they are a stranger.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from openrefcheck.contact import CONTACT_EMAIL_ENV
from openrefcheck.gui.real_pipeline import MAX_VERIFIED_REFERENCES, CheckResult
from openrefcheck.webui import main as webui_main
from openrefcheck.gui.models import ReferenceResult
from openrefcheck.webui.pages import upload
from openrefcheck.webui.state import AppState


class TestTracebackVisibility:
    """A render error must not hand server internals to a visitor.

    The traceback carries absolute paths, the package layout and dependency versions.
    On the desktop app the reader is the operator and it is the whole point; on the demo
    the reader is anonymous.
    """

    def test_local_deployment_shows_internals(self, monkeypatch):
        monkeypatch.delenv("OPENREFCHECK_DEV", raising=False)
        monkeypatch.setenv("OPENREFCHECK_DEPLOYMENT_MODE", "local")
        assert webui_main._show_internal_errors() is True

    def test_demo_deployment_hides_internals(self, monkeypatch):
        monkeypatch.delenv("OPENREFCHECK_DEV", raising=False)
        monkeypatch.setenv("OPENREFCHECK_DEPLOYMENT_MODE", "demo")
        assert webui_main._show_internal_errors() is False

    def test_prod_deployment_hides_internals(self, monkeypatch):
        monkeypatch.delenv("OPENREFCHECK_DEV", raising=False)
        monkeypatch.setenv("OPENREFCHECK_DEPLOYMENT_MODE", "prod")
        assert webui_main._show_internal_errors() is False

    def test_an_explicit_dev_opt_in_wins(self, monkeypatch):
        """Diagnosing the deployed service is a real need; it just has to be deliberate."""
        monkeypatch.setenv("OPENREFCHECK_DEPLOYMENT_MODE", "demo")
        monkeypatch.setenv("OPENREFCHECK_DEV", "1")
        assert webui_main._show_internal_errors() is True

    @pytest.mark.parametrize("bad", ["demoo", "production", "hosted", "", "   "])
    def test_a_misconfigured_mode_hides_internals(self, monkeypatch, bad):
        """A value nobody recognises means somebody tried to configure this and got it
        wrong, which is overwhelmingly a server. It used to resolve to `local`, which
        both claimed local processing to the visitor and turned the traceback back on —
        one misspelling doing both. It now fails closed to `demo`."""
        monkeypatch.delenv("OPENREFCHECK_DEV", raising=False)
        monkeypatch.setenv("OPENREFCHECK_DEPLOYMENT_MODE", bad)
        with pytest.warns(UserWarning):
            assert webui_main._show_internal_errors() is False

    @pytest.mark.parametrize("bad", ["demoo", "production", "", "   "])
    def test_a_misconfigured_mode_does_not_claim_local_processing(self, monkeypatch, bad):
        """The other half of the same defect: local-mode copy tells the visitor the
        document never left their device."""
        from openrefcheck.gui.deployment import PRIVACY_STRIPE
        from openrefcheck.gui.sidebar_copy import configured_mode

        monkeypatch.setenv("OPENREFCHECK_DEPLOYMENT_MODE", bad)
        with pytest.warns(UserWarning):
            mode = configured_mode()
        assert mode == "demo"
        assert "has not left this device" not in PRIVACY_STRIPE[mode]

    def test_the_web_entry_point_overrides_an_empty_value(self, monkeypatch):
        """`setdefault` could not see this: an empty string is present, so it was a
        no-op, and an empty value is the realistic deploy accident."""
        monkeypatch.setenv("OPENREFCHECK_DEPLOYMENT_MODE", "")
        captured = {}
        monkeypatch.setattr("openrefcheck.app_web.create_app", lambda: None)
        monkeypatch.setattr(
            "openrefcheck.app_web.ui.run", lambda **kw: captured.update(mode=configured_mode())
        )

        from openrefcheck.app_web import main
        from openrefcheck.gui.sidebar_copy import configured_mode

        main()

        assert captured["mode"] == "demo"


class TestReferenceCap:
    """One upload must not become unbounded third-party traffic.

    A check makes roughly one OpenAlex and one Crossref request per reference, under the
    operator's contact address. The upload size limit bounds bytes, not how many
    reference-shaped lines fit in them.
    """

    def test_the_cap_is_above_any_real_manuscript(self):
        assert MAX_VERIFIED_REFERENCES >= 500

    def test_an_untruncated_result_says_so_with_none(self):
        """None and 0 must not be confused: 0 would read as 'the document had none'."""
        assert CheckResult().truncated_from is None

    def test_a_truncated_result_carries_the_original_count(self):
        result = CheckResult(references=[], truncated_from=1200)
        assert result.truncated_from == 1200


class TestUploadStaging:
    def test_a_symlinked_staging_directory_is_refused(self, tmp_path, monkeypatch):
        """The parent is world-writable shared temp. Following a planted link would hand
        every upload to whoever planted it, and the chmod would follow it too."""
        real = tmp_path / "elsewhere"
        real.mkdir()
        link = tmp_path / "openrefcheck-uploads"
        link.symlink_to(real, target_is_directory=True)
        monkeypatch.setattr(upload, "_UPLOAD_DIR", link)

        with pytest.raises(RuntimeError, match="symlink"):
            upload._upload_dir()

    def test_a_normal_directory_is_created_private(self, tmp_path, monkeypatch):
        import stat

        target = tmp_path / "openrefcheck-uploads"
        monkeypatch.setattr(upload, "_UPLOAD_DIR", target)

        created = upload._upload_dir()

        assert created.is_dir()
        assert stat.S_IMODE(created.stat().st_mode) == 0o700


def test_no_contact_address_is_compiled_in():
    """The address reaches OpenAlex and Crossref on every lookup. A fork that has not
    configured one must send nothing rather than whoever built the software."""
    import openrefcheck.contact as contact_module

    source = __import__("inspect").getsource(contact_module)
    assert "@" not in source.replace(CONTACT_EMAIL_ENV, ""), (
        "openrefcheck.contact should name no address at all"
    )


class TestServerDefaultsToServerCopy:
    """A server must never serve the local-processing disclaimer.

    `configured_mode()` falls back to "local" when the variable is unset, and local copy
    says "This document stays on your device" — false on a server, which uploaded and
    processed the manuscript. An absent variable is not an invalid one, so nothing warns.
    The web entry point therefore supplies its own default, because it is the thing that
    knows this process is a server.
    """

    def test_the_web_entry_point_defaults_to_demo(self, monkeypatch):
        monkeypatch.delenv("OPENREFCHECK_DEPLOYMENT_MODE", raising=False)
        captured = {}
        monkeypatch.setattr("openrefcheck.app_web.create_app", lambda: None)
        monkeypatch.setattr(
            "openrefcheck.app_web.ui.run",
            lambda **kw: captured.update(mode=configured_mode()),
        )

        from openrefcheck.app_web import main
        from openrefcheck.gui.sidebar_copy import configured_mode

        main()

        assert captured["mode"] == "demo", (
            "an unset mode on the web entry point must not resolve to 'local' — that "
            "copy claims the document never left the visitor's device"
        )

    def test_an_explicit_mode_still_wins(self, monkeypatch):
        """A Phase B university deployment sets prod; the default must not override it."""
        monkeypatch.setenv("OPENREFCHECK_DEPLOYMENT_MODE", "prod")
        captured = {}
        monkeypatch.setattr("openrefcheck.app_web.create_app", lambda: None)
        monkeypatch.setattr(
            "openrefcheck.app_web.ui.run",
            lambda **kw: captured.update(mode=configured_mode()),
        )

        from openrefcheck.app_web import main
        from openrefcheck.gui.sidebar_copy import configured_mode

        main()

        assert captured["mode"] == "prod"

    def test_the_desktop_default_is_still_local(self, monkeypatch):
        """The desktop app genuinely does keep the document on the device, and its
        disclaimer should say so without needing configuration."""
        monkeypatch.delenv("OPENREFCHECK_DEPLOYMENT_MODE", raising=False)

        from openrefcheck.gui.sidebar_copy import configured_mode

        assert configured_mode() == "local"


class TestTruncationReachesEveryClaim:
    """A truncated check must not be stated as a complete one anywhere.

    The cap bounds outbound API calls; these cover the other half, which is that a
    reader must never take "500 references, 3 unresolved" as a verdict on a document
    that had 900. The exported report matters most: it outlives the session and gets
    forwarded to people who never saw the screen.
    """

    @staticmethod
    def _results(n=3):
        return [
            ReferenceResult(n=i, raw=f"Ref {i}", title=f"T{i}", doi=f"10.1/{i}",
                            status="verified", confidence=0.9)
            for i in range(1, n + 1)
        ]

    def _report(self, **kw):
        from openrefcheck.extraction.reference_list_audit import ReferenceListAudit
        from openrefcheck.gui.report_builder import (
            DEFAULT_EXPORT_INCLUDED, ReportMeta, build_html_report,
        )

        return build_html_report(
            self._results(), {},
            ReportMeta(document="thesis.pdf", check_date="2026-01-01 00:00", watermark=False),
            DEFAULT_EXPORT_INCLUDED,
            audit=ReferenceListAudit(read=True, numbered=True, printed_count=3),
            **kw,
        )

    def test_an_untruncated_report_may_still_claim_the_list_matches(self):
        assert "match the list this document prints" in self._report()

    def test_a_truncated_report_never_claims_the_list_matches(self):
        """`audit` is computed over the full pre-truncation list, so the completeness
        note would otherwise be emitted about a document with more references than were
        ever checked — an affirmatively false sentence in a file people forward."""
        assert "match the list this document prints" not in self._report(truncated_from=900)

    def test_a_truncated_report_says_how_much_it_skipped(self):
        assert "Only the first 3 of 900" in self._report(truncated_from=900)

    def test_the_header_subline_reports_both_numbers_when_truncated(self):
        """Summary, Manual review and Export all draw this line and none of them
        mentions truncation otherwise."""
        state = AppState()
        state.results = self._results()
        state.truncated_from = 900
        assert "3 of 900 references" in state.subline()

    def test_the_header_subline_is_unchanged_when_nothing_was_truncated(self):
        state = AppState()
        state.results = self._results()
        assert state.subline().endswith("3 references")


class TestUploadLifecycleGuards:
    def test_a_socket_drop_during_a_check_does_not_delete_the_manuscript(self, tmp_path, monkeypatch):
        """NiceGUI runs disconnect handlers synchronously on any websocket drop, before
        its own reconnect grace period — a sleeping laptop or a changed network, not just
        a closed tab. Deleting mid-check would fail the run intermittently, depending on
        whether the pipeline had already opened the file."""
        monkeypatch.setattr(upload, "_UPLOAD_DIR", tmp_path)
        staged = tmp_path / "manuscript.pdf"
        staged.write_bytes(b"%PDF-1.4")

        state = AppState()
        state.loaded = SimpleNamespace(path=staged)
        state.running = True

        handlers = []
        monkeypatch.setattr(
            upload, "context",
            SimpleNamespace(client=SimpleNamespace(on_disconnect=handlers.append)),
        )
        upload.register_session_cleanup(state)
        handlers[0]()

        assert staged.exists(), "a drop mid-check must not delete the file being checked"

    def test_a_socket_drop_with_no_check_running_does_delete(self, tmp_path, monkeypatch):
        monkeypatch.setattr(upload, "_UPLOAD_DIR", tmp_path)
        staged = tmp_path / "manuscript.pdf"
        staged.write_bytes(b"%PDF-1.4")

        state = AppState()
        state.loaded = SimpleNamespace(path=staged)
        state.running = False

        handlers = []
        monkeypatch.setattr(
            upload, "context",
            SimpleNamespace(client=SimpleNamespace(on_disconnect=handlers.append)),
        )
        upload.register_session_cleanup(state)
        handlers[0]()

        assert not staged.exists()

    def test_the_sweep_refuses_a_symlinked_directory(self, tmp_path, monkeypatch):
        """The sweep runs at process start, before _upload_dir has ever been called, so
        it is the first thing to touch these paths — and the legacy one is a name the
        current build never creates and nothing else defends."""
        victim_dir = tmp_path / "victim"
        victim_dir.mkdir()
        victim = victim_dir / "operators-file.pdf"
        victim.write_bytes(b"private")
        old = 1_000_000.0
        os.utime(victim, (old, old))

        link = tmp_path / "legacy"
        link.symlink_to(victim_dir, target_is_directory=True)
        monkeypatch.setattr(upload, "_UPLOAD_DIR", tmp_path / "absent")
        monkeypatch.setattr(upload, "_LEGACY_UPLOAD_DIR", link)

        removed = upload.sweep_stale_uploads(now=old + upload._STALE_UPLOAD_SECONDS + 1)

        assert removed == 0
        assert victim.exists(), "the sweep must not delete through a planted symlink"

    def test_the_ownership_check_is_skipped_where_getuid_does_not_exist(self, tmp_path, monkeypatch):
        """`os.getuid` is POSIX-only. Calling it unguarded raised AttributeError on
        Windows and stopped uploads working at all there — a harder break than the
        multi-user hazard the check exists for, on the platform the README documents for
        setup. The hazard is POSIX-shaped anyway: Windows gives each user their own temp
        directory, so there is no other account to plant anything."""
        target = tmp_path / "openrefcheck-uploads"
        monkeypatch.setattr(upload, "_UPLOAD_DIR", target)
        monkeypatch.delattr(upload.os, "getuid", raising=False)

        assert upload._upload_dir().is_dir()

    @pytest.mark.skipif(not hasattr(os, "getuid"), reason="POSIX-only ownership check")
    def test_a_staging_directory_owned_by_someone_else_is_refused(self, tmp_path, monkeypatch):
        """mkdir(exist_ok=True) does not touch an existing directory's owner or mode, and
        the chmod that would fix it raises EPERM for a foreign owner. That used to be
        swallowed and the path returned anyway."""
        target = tmp_path / "openrefcheck-uploads"
        target.mkdir()
        monkeypatch.setattr(upload, "_UPLOAD_DIR", target)
        monkeypatch.setattr(upload.os, "getuid", lambda: os.stat(target).st_uid + 1)

        with pytest.raises(RuntimeError, match="owned by uid"):
            upload._upload_dir()

    def test_an_upload_that_cannot_be_loaded_is_not_left_on_disk(self, tmp_path, monkeypatch):
        """Nothing else would ever remove it: the disconnect handler reads state.loaded,
        which a failed load never sets, and no check will run."""
        monkeypatch.setattr(upload, "_UPLOAD_DIR", tmp_path)
        orphan = tmp_path / "unreadable.pdf"
        orphan.write_bytes(b"not really a pdf")
        monkeypatch.setattr(upload, "load_file", lambda *a, **k: (_ for _ in ()).throw(OSError("bad")))
        monkeypatch.setattr(upload.ui, "notify", lambda *a, **k: None)

        took_ownership = upload._set_file(AppState(), None, orphan)

        assert took_ownership is False
        upload._cleanup_upload(orphan)
        assert not orphan.exists()
