"""Repo intelligence: what the analyzer detects and why, and build-failure diagnosis."""
import json

import pytest

import failure_rules
from analyzer import RepoAnalyzer


# ── Build failure diagnosis ──────────────────────────────────────────────────

@pytest.mark.parametrize("log,code,retries", [
    ("npm ERR! `npm ci` can only install packages when your package.json and package-lock.json are in sync",
     "lockfile_mismatch", True),
    ("ERR_PNPM_OUTDATED_LOCKFILE Cannot install with frozen-lockfile", "pnpm_lockfile_mismatch", True),
    ("Error: error:0308010C:digital envelope routines::unsupported", "openssl_legacy", True),
    ("FATAL ERROR: Reached heap limit Allocation failed - JavaScript heap out of memory", "node_heap", True),
    ("container terminated: OOMKilled", "out_of_memory", False),
    ('error my-app@1.0.0: The engine "node" is incompatible with this module.', "node_version", False),
    ("ERROR: No matching distribution found for numpy==3.0", "python_version", False),
    ('npm ERR! Missing script: "start"', "no_start_command", False),
    ("Nixpacks was unable to generate a build plan for this app.", "unknown_project", False),
    ("error building image: COPY failed: file not found in build context", "dockerfile_path", False),
    ("npm ERR! code ERESOLVE\nnpm ERR! ERESOLVE unable to resolve dependency tree", "dependency_resolution", False),
])
def test_known_build_failures_are_explained(log, code, retries):
    d = failure_rules.classify("Step 4/9\n" + log + "\n")
    assert d is not None and d.code == code
    assert d.reason and d.suggestion
    assert bool(d.retry_env) is retries


def test_unknown_failures_keep_the_log_tail():
    assert failure_rules.classify("something odd happened") is None
    assert failure_rules.readable_error(None, "a | b") == "Build failed: a | b"
    d = failure_rules.classify('npm ERR! Missing script: "start"')
    msg = failure_rules.readable_error(d, "tail")
    assert msg.startswith(d.reason) and "Fix:" in msg and msg.endswith("tail")


def test_retry_settings_are_fixed_values():
    # Only these keys ever reach the build (nixpacks --env), whatever the log says.
    allowed = {"NIXPACKS_INSTALL_CMD", "NODE_OPTIONS"}
    for _, d in failure_rules._RULES:
        assert set(d.retry_env) <= allowed
        if d.retry_env:
            assert d.retry_note


def test_nixpacks_passes_retry_settings_as_env():
    import builder
    m = builder.NixpacksBuilder().generate_job_manifest(
        "d1234567-x", "https://github.com/o/r", "main", "img", {"build_env": {"NODE_OPTIONS": "--openssl-legacy-provider"}})
    args = [c for c in m["spec"]["template"]["spec"]["initContainers"] + m["spec"]["template"]["spec"]["containers"]
            if c.get("args") and "build" in c["args"]][0]["args"]
    assert args[args.index("--env") + 1] == "NODE_OPTIONS=--openssl-legacy-provider"


# ── Analyzer ─────────────────────────────────────────────────────────────────

def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_monorepo_services_are_explained(tmp_path):
    _write(tmp_path, "web/package.json", json.dumps({
        "dependencies": {"next": "14"}, "scripts": {"start": "next start", "build": "next build"},
        "engines": {"node": ">=20"}}))
    _write(tmp_path, "web/pnpm-lock.yaml", "")
    _write(tmp_path, "api/requirements.txt", "fastapi\nuvicorn\n")
    _write(tmp_path, "api/.python-version", "3.12\n")
    _write(tmp_path, "worker/Dockerfile", "FROM python:3.12\nEXPOSE 9000\n")
    found = {s.path: s for s in RepoAnalyzer(tmp_path, "repo").analyze()}

    web = found["web"]
    assert (web.framework, web.package_manager, web.port, web.start_command, web.runtime_version) == (
        "nextjs", "pnpm", 3000, "pnpm start", "node >=20")
    assert any("pnpm-lock.yaml" in r for r in web.reasons)

    api = found["api"]
    assert (api.framework, api.port, api.runtime_version) == ("fastapi", 8000, "3.12")

    worker = found["worker"]
    assert (worker.type, worker.port) == ("dockerfile", 9000)


def test_shipzen_yaml_port_wins(tmp_path):
    _write(tmp_path, "package.json", json.dumps({"dependencies": {"express": "4"}}))
    _write(tmp_path, "shipzen.yaml", "port: 4000\n")
    (svc,) = RepoAnalyzer(tmp_path, "repo").analyze()
    assert svc.port == 4000
    assert any("shipzen.yaml" in r for r in svc.reasons)
    assert any("No start script" in r for r in svc.reasons)
