"""Reading OpenRefCheck's environment variables, including the legacy names.

Every setting is `OPENREFCHECK_<NAME>`. The package was called `refcheck` before it
was published, so the same settings also existed as `REFCHECK_<NAME>`, and a
deployment configured under the old names is still out there — the hosted demo among
them.

The fallback exists because of one specific failure. `configured_mode()` defaults to
`"local"` when its variable is *missing*, and a missing variable looks nothing like an
invalid one: no warning fires. A server still setting `REFCHECK_DEPLOYMENT_MODE=demo`
against code reading only the new name would therefore not fail loudly — it would
quietly serve the local-mode disclaimer, telling visitors "this document stays on your
device" while it uploaded and processed their manuscripts. A rename must not be able to
turn a privacy notice into a false one, whatever order the code and the deployment are
updated in.

So the legacy names keep working, and say so: reading one emits a DeprecationWarning
naming both, which is what makes the transition finishable rather than permanent. Once
every deployment sets the new names, delete `_LEGACY_PREFIX` and this note with it.
"""

from __future__ import annotations

import os
import warnings

PREFIX = "OPENREFCHECK_"
_LEGACY_PREFIX = "REFCHECK_"


def env_name(suffix: str) -> str:
    """The canonical variable name for a setting, e.g. "DEPLOYMENT_MODE"."""
    return f"{PREFIX}{suffix}"


def legacy_env_name(suffix: str) -> str:
    return f"{_LEGACY_PREFIX}{suffix}"


def read_env(suffix: str, default: str = "") -> str:
    """The value of `OPENREFCHECK_<suffix>`, or the legacy `REFCHECK_<suffix>`.

    The canonical name wins whenever it is set to anything at all — including the empty
    string, which is how a deployment deliberately clears a setting. Only an unset
    canonical name falls through to the legacy one, so migrating a variable never has to
    mean unsetting the old one first.
    """
    value = os.environ.get(env_name(suffix))
    if value is not None:
        return value

    legacy = os.environ.get(legacy_env_name(suffix))
    if legacy is not None:
        warnings.warn(
            f"{legacy_env_name(suffix)} is the old name for {env_name(suffix)} and is "
            "still being read. Set the new name; support for the old one will be removed.",
            DeprecationWarning,
            stacklevel=3,
        )
        return legacy
    return default
