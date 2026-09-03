"""Verify that every 'recovery' case in the citation-style corpus really reproduces a failure.

A regression corpus is only worth running if each case can tell a fixed parser from a
broken one. It is very easy to add a case that passes before the fix as well as after —
it looks like coverage, costs review time, and protects nothing. Every round of this
parser's history has been at risk of that, so the corpus records, per case, the commit
where it failed and the wrong output measured there; this script replays it.

For each case marked "kind": "recovery", it checks out that case's `broken_at` commit
into a throwaway worktree, runs the case against *that* commit's parser, and fails if
the case passes. Guard cases (correct before the fix, present to stop a later one from
breaking them) are replayed too, and must pass at their `passed_at` commit.

Usage:
    python scripts/check_corpus_reproduces.py
    python scripts/check_corpus_reproduces.py --ref HEAD~1   # replay every case at one ref

The second form is the one to run *before* applying a fix, while adding a new case:
whatever it prints for the new case is what belongs in that case's `observed_then`.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tests"))

from citation_style_corpus import load_cases  # noqa: E402


def evaluate(case: dict) -> dict:
    """Run one case against whatever openrefcheck is importable, and report what happened.

    Imports inside the function because in worker mode this module is executed with a
    *different* checkout's src/ on sys.path than the one it was read from.
    """
    from openrefcheck.extraction import document
    from openrefcheck.extraction.document import find_bibliography_section
    from openrefcheck.extraction.tier0 import split_bibliography_block
    from openrefcheck.extraction.title import extract_title

    expect = case["expect"]
    try:
        if case["layer"] == "normalize":
            # normalize_markdown_text was extracted from _extract_pdf_text when the
            # first cleanup-layer case was written; at older commits the chain is
            # still inlined there, and a case that cannot run is a failure to report,
            # not a crash to swallow.
            normalize = getattr(document, "normalize_markdown_text", None)
            if normalize is None:
                return {"error": "normalize_markdown_text does not exist at this commit"}
            normalized = normalize(case["text"])
            observed = {
                "normalized_contains": {f: f in normalized for f in expect.get("normalized_contains", [])},
                "normalized_excludes": {f: f in normalized for f in expect.get("normalized_excludes", [])},
            }
            if "count" in expect:
                entries = split_bibliography_block(find_bibliography_section(normalized))
                observed["count"] = len(entries)
                for index, prefix in expect.get("entry_starts", {}).items():
                    got = entries[int(index)].raw_text[: len(prefix)] if int(index) < len(entries) else None
                    observed.setdefault("entry_starts", {})[index] = got
        elif case["layer"] == "split":
            entries = split_bibliography_block(case["text"])
            observed = {"count": len(entries)}
            for index, prefix in expect.get("entry_starts", {}).items():
                got = entries[int(index)].raw_text[: len(prefix)] if int(index) < len(entries) else None
                observed.setdefault("entry_starts", {})[index] = got
            for index, fragment in expect.get("entry_contains", {}).items():
                got = fragment in entries[int(index)].raw_text if int(index) < len(entries) else None
                observed.setdefault("entry_contains", {})[index] = got
        elif case["layer"] == "section":
            observed = {"section": find_bibliography_section(case["text"])}
        else:
            observed = {"title": extract_title(case["raw"])}
    except Exception as exc:  # a crash is a failure, and a legitimate thing to record
        return {"error": f"{type(exc).__name__}: {exc}"}
    return observed


def passes(case: dict, observed: dict) -> bool:
    expect = case["expect"]
    if "error" in observed:
        return False
    if case["layer"] == "normalize":
        if not all(observed["normalized_contains"].values()):
            return False
        if any(observed["normalized_excludes"].values()):
            return False
        if "count" not in expect:
            return True
        if observed["count"] != expect["count"]:
            return False
        return all(
            observed.get("entry_starts", {}).get(index) == prefix
            for index, prefix in expect.get("entry_starts", {}).items()
        )
    if case["layer"] == "split":
        if observed["count"] != expect["count"]:
            return False
        for index, prefix in expect.get("entry_starts", {}).items():
            if observed.get("entry_starts", {}).get(index) != prefix:
                return False
        return all(observed.get("entry_contains", {}).get(i) for i in expect.get("entry_contains", {}))
    if case["layer"] == "section":
        section = observed["section"]
        if "section_equals" in expect and section != expect["section_equals"]:
            return False
        if any(f not in section for f in expect.get("section_contains", [])):
            return False
        return not any(f in section for f in expect.get("section_excludes", []))
    return observed["title"] == expect["title"]


def _run_at_ref(ref: str, cases: list[dict]) -> dict[str, dict]:
    """Evaluate cases against `ref`'s parser in a detached worktree."""
    with tempfile.TemporaryDirectory(prefix="refcheck-corpus-replay-") as tmp:
        tree = Path(tmp) / "tree"
        subprocess.run(
            ["git", "worktree", "add", "-q", "--detach", str(tree), ref],
            cwd=REPO_ROOT, check=True,
        )
        try:
            payload = json.dumps(cases)
            result = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--worker", str(tree / "src")],
                input=payload, capture_output=True, text=True, cwd=REPO_ROOT,
            )
            if result.returncode != 0:
                raise RuntimeError(f"replay at {ref} failed:\n{result.stderr}")
            return json.loads(result.stdout)
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(tree)],
                cwd=REPO_ROOT, check=False,
            )


def _worker(src_dir: str) -> None:
    # The old checkout's src/ must win over the current one, hence position 0.
    sys.path.insert(0, src_dir)
    cases = json.loads(sys.stdin.read())
    json.dump({case["id"]: evaluate(case) for case in cases}, sys.stdout)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ref",
        help="replay every case at this ref instead of each case's recorded commit; "
        "run this before applying a fix to find out what a new case actually does",
    )
    parser.add_argument("--worker", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.worker:
        _worker(args.worker)
        return 0

    cases = {case["id"]: case for case in load_cases()}

    if args.ref:
        by_ref = {args.ref: list(cases.values())}
    else:
        by_ref = defaultdict(list)
        for case in cases.values():
            reproduces = case["reproduces"]
            by_ref[reproduces.get("broken_at") or reproduces["passed_at"]].append(case)

    problems = []
    for ref, ref_cases in sorted(by_ref.items()):
        print(f"\n=== replaying {len(ref_cases)} case(s) at {ref} ===")
        observed_by_id = _run_at_ref(ref, ref_cases)
        for case in sorted(ref_cases, key=lambda c: (c["style"], c["id"])):
            observed = observed_by_id[case["id"]]
            ok = passes(case, observed)
            kind = case["reproduces"]["kind"]
            expected_to_pass = args.ref is not None or kind == "guard"
            status = "PASS" if ok else "FAIL"
            print(f"  {status:4}  {case['style']}/{case['id']}")
            if not ok and (args.ref or kind == "guard"):
                print(f"        observed: {json.dumps(observed)[:200]}")
            if args.ref is None and ok is not expected_to_pass:
                problems.append(
                    f"{case['style']}/{case['id']}: {kind} case "
                    f"{'passes' if ok else 'fails'} at {ref}, which contradicts its "
                    "reproduces block"
                )

    if args.ref:
        print("\nreplay only — nothing asserted. Record what a new case printed above "
              "as its reproduces.observed_then.")
        return 0

    if problems:
        print("\nThe corpus claims failures it cannot reproduce:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print("\nEvery recovery case reproduces its failure; every guard case held.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
