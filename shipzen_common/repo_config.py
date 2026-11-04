"""Validate the deploy config a user's repository ships (shipzen.yaml / deployhub.yml).

This file comes from the repository being built, so it is untrusted input. Its
values end up in the database, in Kubernetes Job specs and in the GitOps
manifests ArgoCD applies, so nothing from it may pass through unchecked: a
health-check path with a quote and a newline in it used to be able to inject
whole Kubernetes objects into the tenant manifests.

Only the keys below are read; anything else in the file is ignored, and in
particular can't set the worker's internal build options.
"""
import re

ALLOWED_KEYS = ("port", "health_check_path", "buildContext")

# An HTTP path: starts with '/', then unreserved characters, '/' and %-escapes.
# No quotes, spaces, colons, newlines or YAML/JSON-significant characters.
HEALTH_PATH_RE = re.compile(r"\A/[A-Za-z0-9._~%/-]{0,200}\Z")
# A relative directory inside the repository.
BUILD_CONTEXT_RE = re.compile(r"\A[A-Za-z0-9._/-]{0,200}\Z")


class RepoConfigError(ValueError):
    """The repository's deploy config is invalid; the message is safe to show the user."""


def valid_health_check_path(value) -> bool:
    return isinstance(value, str) and bool(HEALTH_PATH_RE.match(value))


def valid_image_digest(value) -> bool:
    """An OCI content digest: sha256 followed by 64 lowercase hex characters."""
    return isinstance(value, str) and bool(re.fullmatch(r"sha256:[0-9a-f]{64}", value))


def valid_port(value) -> bool:
    # bool is an int subclass; `port: true` is not a port.
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 65535


def parse_repo_config(raw) -> dict:
    """Return only the validated settings from a parsed shipzen.yaml.

    Raises RepoConfigError (with a user-facing message) if a known key has an
    invalid value. Unknown keys are dropped.
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise RepoConfigError("shipzen.yaml must be a mapping of settings (key: value)")

    config = {}
    if raw.get("port") is not None:
        if not valid_port(raw["port"]):
            raise RepoConfigError("shipzen.yaml: port must be a whole number from 1 to 65535")
        config["port"] = raw["port"]

    if raw.get("health_check_path") is not None:
        if not valid_health_check_path(raw["health_check_path"]):
            raise RepoConfigError(
                "shipzen.yaml: health_check_path must start with '/' and contain only "
                "letters, digits and . _ ~ % / - (max 200 characters)")
        config["health_check_path"] = raw["health_check_path"]

    if raw.get("buildContext") is not None:
        ctx = raw["buildContext"]
        if (not isinstance(ctx, str) or not BUILD_CONTEXT_RE.match(ctx)
                or ctx.startswith("/") or ".." in ctx.split("/")):
            raise RepoConfigError(
                "shipzen.yaml: buildContext must be a folder inside the repository, "
                "like 'backend' or 'apps/web' (no leading '/' and no '..')")
        config["buildContext"] = ctx.strip("/")

    return config
