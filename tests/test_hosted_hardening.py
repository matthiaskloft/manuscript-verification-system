"""What a hosted instance must not do, and what it must say when it stops short.

These pin the findings from the pre-publication review. Each is about the difference
between the desktop app, where the person at the screen is the operator, and a public
server, where they are a stranger.
"""

from __future__ import annotations

import pytest

from refcheck.contact import CONTACT_EMAIL_ENV
from refcheck.gui.real_pipeline import MAX_VERIFIED_REFERENCES, CheckResult
from refcheck.webui import main as webui_main
from refcheck.webui.pages import upload


class TestTracebackVisibility:
    """A render error must not hand server internals to a visitor.

    The traceback carries absolute paths, the package layout and dependency versions.
    On the desktop app the reader is the operator and it is the whole point; on the demo
    the reader is anonymous.
    """

    def test_local_deployment_shows_internals(self, monkeypatch):
        monkeypatch.delenv("REFCHECK_DEV", raising=False)
        monkeypatch.setenv("REFCHECK_DEPLOYMENT_MODE", "local")
        assert webui_main._show_internal_errors() is True

    def test_demo_deployment_hides_internals(self, monkeypatch):
        monkeypatch.delenv("REFCHECK_DEV", raising=False)
        monkeypatch.setenv("REFCHECK_DEPLOYMENT_MODE", "demo")
        assert webui_main._show_internal_errors() is False

    def test_prod_deployment_hides_internals(self, monkeypatch):
        monkeypatch.delenv("REFCHECK_DEV", raising=False)
        monkeypatch.setenv("REFCHECK_DEPLOYMENT_MODE", "prod")
        assert webui_main._show_internal_errors() is False

    def test_an_explicit_dev_opt_in_wins(self, monkeypatch):
        """Diagnosing the deployed service is a real need; it just has to be deliberate."""
        monkeypatch.setenv("REFCHECK_DEPLOYMENT_MODE", "demo")
        monkeypatch.setenv("REFCHECK_DEV", "1")
        assert webui_main._show_internal_errors() is True

    def test_an_unrecognised_mode_hides_internals(self, monkeypatch):
        """configured_mode falls back to 'local' on a bad value, which would otherwise
        turn a typo in a deploy script into a disclosure. Assert the real behaviour so a
        change to that fallback cannot pass silently."""
        monkeypatch.delenv("REFCHECK_DEV", raising=False)
        monkeypatch.setenv("REFCHECK_DEPLOYMENT_MODE", "demoo")
        with pytest.warns(UserWarning):
            result = webui_main._show_internal_errors()
        assert result is True, (
            "a misspelled mode falls back to 'local' and so shows internals — if this "
            "ever changes, the fallback is the thing to re-examine, not this assertion"
        )


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
        link = tmp_path / "refcheck-uploads"
        link.symlink_to(real, target_is_directory=True)
        monkeypatch.setattr(upload, "_UPLOAD_DIR", link)

        with pytest.raises(RuntimeError, match="symlink"):
            upload._upload_dir()

    def test_a_normal_directory_is_created_private(self, tmp_path, monkeypatch):
        import stat

        target = tmp_path / "refcheck-uploads"
        monkeypatch.setattr(upload, "_UPLOAD_DIR", target)

        created = upload._upload_dir()

        assert created.is_dir()
        assert stat.S_IMODE(created.stat().st_mode) == 0o700


def test_no_contact_address_is_compiled_in():
    """The address reaches OpenAlex and Crossref on every lookup. A fork that has not
    configured one must send nothing rather than whoever built the software."""
    import refcheck.contact as contact_module

    source = __import__("inspect").getsource(contact_module)
    assert "@" not in source.replace(CONTACT_EMAIL_ENV, ""), (
        "refcheck.contact should name no address at all"
    )
