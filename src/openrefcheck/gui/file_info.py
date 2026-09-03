"""File metadata helpers for the Upload screen."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

SUPPORTED_SUFFIXES = {".pdf", ".docx"}

# LoadedFile.origin value for the bundled demo manuscript — a synthetic (LaTeX-generated)
# fixture, checked by report_export.py to decide whether to watermark an exported report.
DEMO_MANUSCRIPT_ORIGIN = "Bundled demo manuscript"


@dataclass(frozen=True)
class LoadedFile:
    path: Path
    name: str
    size_label: str
    pages_label: str
    origin: str


def format_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def page_count(path: Path) -> str:
    if path.suffix.lower() != ".pdf":
        return "—"  # DOCX has no fixed page count without rendering
    try:
        import fitz  # PyMuPDF

        with fitz.open(path) as doc:
            return str(doc.page_count)
    except Exception:
        return "—"


def load_file(path: Path, *, origin: str = "Local file") -> LoadedFile:
    return LoadedFile(
        path=path,
        name=path.name,
        size_label=format_size(path.stat().st_size),
        pages_label=page_count(path),
        origin=origin,
    )
