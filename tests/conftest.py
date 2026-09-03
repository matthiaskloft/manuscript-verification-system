from pathlib import Path

import pytest

import openrefcheck

# Multiple git worktrees of this repo can exist side by side (e.g. one per parallel
# agent session), but there's only one global Python environment. `pip install -e .`
# in worktree A repoints the *shared* editable install at A — so running pytest from
# worktree B silently tests A's source tree with no error, just confusing failures
# (or worse, a false-green run) that look like real bugs. Fail fast and loud instead.
_REPO_ROOT = Path(__file__).resolve().parent.parent


def pytest_sessionstart(session: pytest.Session) -> None:
    installed_root = Path(openrefcheck.__file__).resolve().parents[2]
    if installed_root != _REPO_ROOT:
        raise pytest.UsageError(
            f"openrefcheck is installed (editable) from a different worktree:\n"
            f"  installed from: {installed_root}\n"
            f"  running tests from: {_REPO_ROOT}\n"
            f"Run `pip install -e .` from {_REPO_ROOT} first, or these tests will "
            f"silently exercise the wrong source tree."
        )
