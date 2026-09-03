"""The contact address OpenRefCheck gives Crossref and OpenAlex to identify itself.

Both APIs run a "polite pool": a caller that supplies a contact address gets faster,
more reliable service than an anonymous one. Crossref takes it as a `mailto` in the
User-Agent; OpenAlex takes it as `pyalex.config.email`.

It is deliberately **not** hardcoded. This address is sent to a third party on every
single reference lookup, so a compiled-in default would mean every fork and every
self-hosted deployment announcing whoever happened to build it — publishing one
person's address from other people's servers, and misattributing that traffic to
someone with no control over it.

So it comes from the environment, and there is no fallback. Unset means unset: the
clients then call the anonymous pool, which works, is slower, and is the correct
outcome for someone who has not chosen an address to be identified by. Operators who
want the polite pool set OPENREFCHECK_CONTACT_EMAIL to an address they own (see README).
"""

from __future__ import annotations

from openrefcheck.env import env_name, read_env

CONTACT_EMAIL_ENV = env_name("CONTACT_EMAIL")


def contact_email() -> str | None:
    """The configured contact address, or None if the operator has not set one.

    Whitespace-only is treated as unset — a deployment that exports the variable empty
    (a common way to "clear" it in a shell or a Cloud Run env var) means no address,
    not an address that is the empty string, which would put a malformed `mailto:` in
    front of Crossref.
    """
    value = read_env("CONTACT_EMAIL").strip()
    return value or None
