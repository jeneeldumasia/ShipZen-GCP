"""Remove credentials from text before it is stored, logged or shown to users.

Deployment errors are saved in deployments.last_error, which every member of a
project (viewers included) can read in the UI. A failed `git clone` used to put
the GitHub App installation token there, because the token was part of the
clone URL and the command line ends up in the exception message.
"""
import re

_PATTERNS = [
    # https://user:secret@host  (x-access-token:..., oauth2:..., any basic auth in a URL)
    (re.compile(r"(https?://)[^/\s:@]+:[^/\s@]+@"), r"\1***@"),
    # GitHub tokens: ghp_, gho_, ghu_, ghs_, ghr_, github_pat_
    (re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"), "***"),
    # Authorization headers and bearer tokens
    (re.compile(r"(?i)(authorization:\s*(?:basic|bearer|token)\s+)\S+"), r"\1***"),
    (re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]{8,}"), r"\1***"),
    # Telegram bot tokens (123456789:AA...)
    (re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{30,}\b"), "***"),
]


def redact(text):
    """Return text with known credential shapes replaced by ***. None stays None."""
    if text is None:
        return None
    out = str(text)
    for pattern, replacement in _PATTERNS:
        out = pattern.sub(replacement, out)
    return out
