"""Hostnames ShipZen serves apps on.

Two kinds, both one label under ZONE so the free Cloudflare certificate
(*.jeneeldumasia.codes) covers them:

  <first 8 chars of deployment id>-<project slug>-shipzen.<zone>   one per release
  <vanity name>-shipzen.<zone>                                     stable, chosen by the owner

Vanity names are free: they cost nothing beyond the zone we already have.
"""
import re

ZONE = "jeneeldumasia.codes"
SUFFIX = f"-shipzen.{ZONE}"

# 3-40 characters: lowercase letters, digits and single hyphens, starting with a
# letter and not ending with a hyphen.
_VANITY_RE = re.compile(r"\A[a-z](?:[a-z0-9]|-(?!-)){1,38}[a-z0-9]\Z")

# Names whose hostname the platform already uses, or may want.
RESERVED_VANITY = frozenset({
    "grafana", "argocd", "api", "app", "www", "admin", "status", "docs",
    "mail", "customers", "shipzen", "dashboard", "login", "auth",
})


def vanity_problem(name):
    """Why `name` can't be a vanity name, or None if it can."""
    if not isinstance(name, str) or not _VANITY_RE.match(name):
        return ("Use 3-40 lowercase letters, digits and single hyphens, starting "
                "with a letter and not ending with a hyphen.")
    if name in RESERVED_VANITY:
        return f"'{name}' is reserved."
    # Release URLs are <8 chars>-<slug>-shipzen. A vanity name with a hyphen as
    # its 9th character could equal one of them (or be claimed through that
    # pattern), so that shape is kept for releases.
    if len(name) > 8 and name[8] == "-":
        return "Names with a hyphen as the 9th character are reserved for release URLs."
    return None


def valid_vanity(name) -> bool:
    return vanity_problem(name) is None


def vanity_hostname(name: str) -> str:
    return f"{name}{SUFFIX}"
