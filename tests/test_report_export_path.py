from pathlib import Path

from openrefcheck.webui.pages.report_export import _validated_export_path


def test_export_path_requires_absolute_path() -> None:
    path, error = _validated_export_path("report.html")

    assert path is None
    assert "absolute" in error


def test_export_path_adds_html_suffix(tmp_path: Path) -> None:
    path, error = _validated_export_path(str(tmp_path / "report"))

    assert error is None
    assert path == tmp_path / "report.html"


def test_export_path_rejects_missing_parent(tmp_path: Path) -> None:
    path, error = _validated_export_path(str(tmp_path / "missing" / "report.html"))

    assert path is None
    assert error == "The selected folder does not exist."


def test_export_path_rejects_non_html_extension(tmp_path: Path) -> None:
    path, error = _validated_export_path(str(tmp_path / "report.pdf"))

    assert path is None
    assert error == "The report filename must end in .html or .htm."
