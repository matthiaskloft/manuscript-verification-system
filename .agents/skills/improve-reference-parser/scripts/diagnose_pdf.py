"""Capture evidence for built-in reference-parser failures on one PDF."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from dataclasses import asdict
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run pymupdf4llm, the project parser, and optionally Crossref/OpenAlex "
            "verification; write evidence for unmatched-reference diagnosis."
        )
    )
    parser.add_argument("pdf", type=Path, help="Manuscript PDF to diagnose")
    parser.add_argument("--repo-root", type=Path, help="Repository root (auto-detected by default)")
    parser.add_argument("--output-dir", type=Path, help="Evidence directory (a temporary directory by default)")
    parser.add_argument("--engine", choices=("anchor", "auto", "grobid"), default="anchor")
    parser.add_argument("--no-api", action="store_true", help="Skip Crossref/OpenAlex verification")
    return parser.parse_args()


def find_repo_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "src" / "openrefcheck").is_dir():
            return candidate
    raise SystemExit("Could not locate an openrefcheck repository; pass --repo-root.")


def package_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
    ) as temporary:
        temporary.write(content)
        temporary_path = Path(temporary.name)
    os.replace(temporary_path, path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def markdown_report(records: list[dict], api_enabled: bool) -> str:
    lines = ["# Non-matched reference diagnostics", ""]
    if not api_enabled:
        lines.extend(["API verification was skipped; all entries are listed for extraction review.", ""])

    selected = records if not api_enabled else [record for record in records if not record["verification"]["matched"]]
    if not selected:
        lines.extend(["No non-matched entries.", ""])
        return "\n".join(lines)

    for record in selected:
        verification = record["verification"]
        lines.extend(
            [
                f"## Entry {record['index']}",
                "",
                f"- Query title: {record['query_title']}",
                f"- Matched: {verification['matched']}",
                f"- Confidence: {verification['confidence']}",
                f"- Error: {verification['error'] or 'none'}",
                "",
                "```text",
                record["raw_text"],
                "```",
                "",
            ]
        )
        if verification["candidates"]:
            lines.extend(["Candidates:", ""])
            for candidate in verification["candidates"]:
                lines.append(
                    f"- {candidate['similarity']:.3f} — {candidate['title']} "
                    f"({candidate['doi']}; {candidate['source']})"
                )
            lines.append("")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    pdf = args.pdf.resolve()
    if not pdf.is_file() or pdf.suffix.lower() != ".pdf":
        raise SystemExit(f"Expected an existing PDF file: {pdf}")

    script_path = Path(__file__).resolve()
    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root(script_path.parent)
    if not (repo_root / "src" / "openrefcheck").is_dir():
        raise SystemExit(f"Not an openrefcheck repository: {repo_root}")
    sys.path.insert(0, str(repo_root / "src"))

    import pymupdf4llm

    from openrefcheck.extraction.document import extract_full_text, extract_references, find_bibliography_section
    from openrefcheck.extraction.engine_status import ENGINE_ANCHOR, ENGINE_AUTO, ENGINE_GROBID
    from openrefcheck.extraction.title import extract_title
    from openrefcheck.verification.openalex_crossref import VerificationResult, verify_reference

    engines = {"anchor": ENGINE_ANCHOR, "auto": ENGINE_AUTO, "grobid": ENGINE_GROBID}
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir
        else Path(tempfile.mkdtemp(prefix=f"refcheck-parser-{pdf.stem}-"))
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_markdown = pymupdf4llm.to_markdown(str(pdf))
    normalized = extract_full_text(pdf)
    bibliography = find_bibliography_section(normalized)
    entries = extract_references(pdf, engine=engines[args.engine])

    records: list[dict] = []
    for entry in entries:
        query_title = entry.title or extract_title(entry.raw_text) or entry.raw_text
        if args.no_api:
            verification = VerificationResult(matched=False, confidence=0.0, error="API verification skipped")
        else:
            verification = verify_reference(query_title, raw_text=entry.raw_text)
        records.append(
            {
                "index": entry.index,
                "raw_text": entry.raw_text,
                "parser_title": entry.title,
                "query_title": query_title,
                "verification": asdict(verification),
            }
        )

    report = {
        "schema_version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "input": {"filename": pdf.name, "sha256": sha256(pdf)},
        "engine": args.engine,
        "api_enabled": not args.no_api,
        "versions": {
            "pymupdf": package_version("pymupdf"),
            "pymupdf4llm": package_version("pymupdf4llm"),
        },
        "entry_count": len(records),
        "nonmatched_count": sum(not record["verification"]["matched"] for record in records)
        if not args.no_api
        else None,
        "entries": records,
    }

    atomic_write_text(output_dir / "pymupdf.md", raw_markdown)
    atomic_write_text(output_dir / "normalized.md", normalized)
    atomic_write_text(output_dir / "bibliography.md", bibliography)
    atomic_write_text(output_dir / "report.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    atomic_write_text(output_dir / "nonmatched.md", markdown_report(records, not args.no_api))

    print(output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
