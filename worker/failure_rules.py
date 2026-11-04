"""Turn a failed build's log into a reason a person can act on.

Rule-based (no LLM, no cost): each rule matches known error text and gives a
plain-language reason, a suggested fix, and, for a few failures with a safe,
well-understood fix, build settings to retry once with automatically. Retry
settings are fixed strings defined here, never taken from the log or the repo.
"""
import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Diagnosis:
    code: str
    reason: str
    suggestion: str
    # Extra build environment for one automatic retry (Nixpacks builds only).
    retry_env: dict = field(default_factory=dict)
    retry_note: Optional[str] = None


_RULES = [
    (re.compile(r"npm ci` can only install packages when your package\.json and package-lock\.json"
                r"|npm ERR! `?npm ci`? can only install|package-lock\.json.{0,40}(not in sync|out of sync)"
                r"|The `npm ci` command can only install with an existing package-lock", re.I | re.S),
     Diagnosis("lockfile_mismatch",
               "package.json and package-lock.json don't match, so a clean install (npm ci) refused to run.",
               "Run `npm install` locally and commit the updated package-lock.json.",
               {"NIXPACKS_INSTALL_CMD": "npm install"},
               "installed with `npm install` instead of `npm ci` (lockfile out of sync)")),
    (re.compile(r"ERR_PNPM_OUTDATED_LOCKFILE|pnpm-lock\.yaml is not up to date", re.I),
     Diagnosis("pnpm_lockfile_mismatch",
               "pnpm-lock.yaml doesn't match package.json, so a frozen install refused to run.",
               "Run `pnpm install` locally and commit the updated pnpm-lock.yaml.",
               {"NIXPACKS_INSTALL_CMD": "pnpm install --no-frozen-lockfile"},
               "installed with `pnpm install --no-frozen-lockfile` (lockfile out of sync)")),
    (re.compile(r"error:0308010C:digital envelope routines|ERR_OSSL_EVP_UNSUPPORTED", re.I),
     Diagnosis("openssl_legacy",
               "The build tool (often an older webpack) uses a hashing method newer Node.js versions disabled.",
               "Upgrade the build tool (e.g. react-scripts 5 / webpack 5), or set NODE_OPTIONS=--openssl-legacy-provider.",
               {"NODE_OPTIONS": "--openssl-legacy-provider"},
               "built with NODE_OPTIONS=--openssl-legacy-provider (older webpack on newer Node.js)")),
    (re.compile(r"JavaScript heap out of memory|Reached heap limit", re.I),
     Diagnosis("node_heap",
               "The JavaScript build ran out of heap memory.",
               "Reduce what the build bundles, or set NODE_OPTIONS=--max-old-space-size=3072.",
               {"NODE_OPTIONS": "--max-old-space-size=3072"},
               "built with a larger Node.js heap (--max-old-space-size=3072)")),
    (re.compile(r"OOMKilled|exit code:? 137|exited with code 137|signal: killed", re.I),
     Diagnosis("out_of_memory",
               "The build ran out of memory (4 GiB) and was stopped.",
               "Make the build lighter, or build outside ShipZen and deploy with a Dockerfile that copies the result.")),
    (re.compile(r'engine "node" is incompatible|Unsupported engine|requires? (a )?node(\.js)? version|'
                r"The engines\.node", re.I),
     Diagnosis("node_version",
               "The project needs a different Node.js version than the build used.",
               "Set it in package.json (\"engines\": {\"node\": \"20\"}) or an .nvmrc file, matching what you use locally.")),
    (re.compile(r"requires a different Python|Requires-Python|No matching distribution found for", re.I),
     Diagnosis("python_version",
               "A Python package isn't available for the Python version the build used.",
               "Pin the Python version in .python-version or runtime.txt, or loosen the package version.")),
    (re.compile(r'Missing script: "?start"?|no start command could be found', re.I),
     Diagnosis("no_start_command",
               "The build doesn't know how to start your app.",
               "Add a \"start\" script to package.json (or a Procfile / Dockerfile CMD) that starts the server on $PORT.")),
    (re.compile(r"Nixpacks was unable to generate a build plan|unable to (detect|determine).{0,40}(language|provider)", re.I),
     Diagnosis("unknown_project",
               "ShipZen couldn't tell what kind of app this is.",
               "If the app lives in a subfolder, pick it with Analyze on the deploy page; otherwise add a Dockerfile.")),
    (re.compile(r"COPY failed|failed to compute cache key|no such file or directory.{0,80}Dockerfile", re.I | re.S),
     Diagnosis("dockerfile_path",
               "The Dockerfile copies a file or folder that isn't in the build context.",
               "Check the COPY paths, and that the build folder (build context) is the folder containing them.")),
    (re.compile(r"npm ERR! (code )?E404|404 Not Found.{0,80}registry\.npmjs\.org|"
                r"Could not resolve dependency|ERESOLVE", re.I | re.S),
     Diagnosis("dependency_resolution",
               "A dependency couldn't be found or its versions conflict.",
               "Check the package names and versions in package.json; for peer conflicts, align versions or commit a working lockfile.")),
]


def classify(log_text: str) -> Optional[Diagnosis]:
    """The first rule that matches the build log, or None."""
    if not log_text:
        return None
    text = log_text[-200_000:]  # the end of the log is where builds fail
    for pattern, diagnosis in _RULES:
        if pattern.search(text):
            return diagnosis
    return None


def readable_error(diagnosis: Optional[Diagnosis], tail: str) -> str:
    """last_error for the UI and emails: reason and fix first, log tail after."""
    if not diagnosis:
        return f"Build failed: {tail}"[:1000] if tail else "Build step failed."
    return f"{diagnosis.reason} Fix: {diagnosis.suggestion}" + (f"\n\nLast build output: {tail}" if tail else "")
