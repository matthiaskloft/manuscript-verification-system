"""Serialize SynthReferenceEntry records into a .bib file for biblatex/biber.

We write .bib entries ourselves rather than exporting via Zotero's Better BibTeX
plugin: the entries already live as plain Python data (see entries.py), and
generating .bib directly keeps the pipeline self-contained without requiring a
particular Zotero plugin to be installed to reproduce the benchmark.
"""

from pathlib import Path

from openrefcheck.synth.entries import SynthReferenceEntry

_FIELD_ORDER = [
    "author", "title", "year", "journal", "volume", "number", "pages",
    "publisher", "address", "booktitle", "doi", "url", "note",
]


def _entry_fields(entry: SynthReferenceEntry) -> dict[str, str]:
    author = " and ".join(a.bibtex_name() for a in entry.authors)
    fields = {
        "author": author,
        "title": entry.title,
        "year": entry.year,
        "journal": entry.journal,
        "volume": entry.volume,
        "number": entry.number,
        "pages": entry.pages,
        "publisher": entry.publisher,
        "address": entry.address,
        "booktitle": entry.booktitle,
        "doi": entry.doi,
        "url": entry.url,
        "note": entry.note,
    }
    return {k: v for k, v in fields.items() if v}


def _escape(value: str) -> str:
    return value.replace("&", r"\&").replace("_", r"\_")


def format_bib_entry(entry: SynthReferenceEntry) -> str:
    fields = _entry_fields(entry)
    lines = [f"@{entry.entry_type}{{{entry.key},"]
    for name in _FIELD_ORDER:
        if name in fields:
            value = fields[name] if name in {"doi", "url"} else _escape(fields[name])
            lines.append(f"  {name} = {{{value}}},")
    lines.append("}")
    return "\n".join(lines)


def write_bib_file(entries: list[SynthReferenceEntry], path: Path) -> None:
    content = "\n\n".join(format_bib_entry(e) for e in entries) + "\n"
    path.write_text(content, encoding="utf-8")
