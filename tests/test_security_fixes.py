"""Tests for the C1/C2 security fixes from the 2026-11 review.

C1: a tenant repository's shipzen.yaml could inject Kubernetes objects into the
    GitOps manifests (health_check_path rendered raw into YAML).
C2: the GitHub App installation token leaked into deployments.last_error
    (clone URL in the exception text) and into images (.git/config).
"""
from unittest.mock import MagicMock, patch

import jinja2
import pytest
import yaml

from _component import ROOT, load
from shipzen_common.github_app import git_auth_env, git_auth_header
from shipzen_common.redact import redact
from shipzen_common.repo_config import RepoConfigError, parse_repo_config

controller = load("controller")
worker = load("worker")

INJECTION = '/"\n---\napiVersion: rbac.authorization.k8s.io/v1\nkind: ClusterRoleBinding\nmetadata: {name: pwned}\n#'
FAKE_TOKEN = "ghs_" + "A" * 36


# ── C1: repository config is validated ───────────────────────────────────────

def test_repo_config_keeps_valid_settings():
    cfg = parse_repo_config({"port": 3000, "health_check_path": "/api/health", "buildContext": "apps/web/"})
    assert cfg == {"port": 3000, "health_check_path": "/api/health", "buildContext": "apps/web"}


@pytest.mark.parametrize("raw", [
    {"health_check_path": INJECTION},
    {"health_check_path": '/ok" injected'},
    {"health_check_path": "health"},          # must start with /
    {"health_check_path": "/a:b"},
    {"port": "8080\n---"},
    {"port": True},
    {"port": 0},
    {"port": 70000},
    {"buildContext": "../../etc"},
    {"buildContext": "/abs"},
    {"buildContext": "a/../../b"},
    ["not", "a", "mapping"],
])
def test_repo_config_rejects_unsafe_values(raw):
    with pytest.raises(RepoConfigError):
        parse_repo_config(raw)


def test_repo_config_drops_internal_and_unknown_keys():
    # These used to flow straight into the worker's internal build options.
    raw = {"github_secret_name": "someone-elses-secret", "inject_server_js": True,
           "trace_id": "x\ny", "anything": 1, "port": 8080}
    assert parse_repo_config(raw) == {"port": 8080}


def test_repo_config_empty_file():
    assert parse_repo_config(None) == {}


def _render_app(health_check_path):
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(ROOT / "controller" / "templates")))
    return env.get_template("app-deployment.yaml.j2").render(
        deployment_name="d1", deployment_id="d1234567", namespace="tenant-a",
        project_id="p1", project_name="app", image_uri="img:1", port=8080,
        replicas=1, health_check_path=health_check_path)


def test_template_cannot_be_broken_out_of_even_with_a_raw_value():
    # Defence in depth: even if an unvalidated value reached the template,
    # tojson keeps it a single YAML string, so no extra objects appear.
    docs = [d for d in yaml.safe_load_all(_render_app(INJECTION)) if d]
    assert [d["kind"] for d in docs] == ["ExternalSecret", "Deployment", "Service", "HTTPRoute", "PodDisruptionBudget"]
    probe = docs[1]["spec"]["template"]["spec"]["containers"][0]["readinessProbe"]
    assert probe["httpGet"]["path"] == INJECTION


def test_controller_falls_back_to_root_for_invalid_stored_paths():
    assert controller._safe_health_path(INJECTION) == "/"
    assert controller._safe_health_path(None) == "/"
    assert controller._safe_health_path("/healthz") == "/healthz"
    assert controller._safe_port("8080") == 8080
    assert controller._safe_port(3000) == 3000


# ── C2: the GitHub token stays out of errors, URLs and images ────────────────

@pytest.mark.parametrize("text", [
    f"Command '['git', 'clone', 'https://x-access-token:{FAKE_TOKEN}@github.com/o/r', '/tmp/w']' returned non-zero exit status 128.",
    f"token {FAKE_TOKEN} rejected",
    f"Authorization: Bearer {FAKE_TOKEN}",
    "AUTHORIZATION: basic eC1hY2Nlc3MtdG9rZW46c2VjcmV0",
    "https://oauth2:supersecret@example.com/repo.git",
])
def test_redact_removes_credentials(text):
    out = redact(text)
    assert FAKE_TOKEN not in out
    assert "supersecret" not in out
    assert "eC1hY2Nlc3MtdG9rZW46c2VjcmV0" not in out
    assert "***" in out


def test_redact_leaves_ordinary_text_alone():
    msg = "Build failed at step 4/9: npm ERR! missing script: build"
    assert redact(msg) == msg
    assert redact(None) is None


def test_git_auth_is_passed_by_env_not_url():
    env = git_auth_env(FAKE_TOKEN)
    assert env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"
    assert env["GIT_CONFIG_VALUE_0"] == git_auth_header(FAKE_TOKEN)
    assert FAKE_TOKEN not in env["GIT_CONFIG_VALUE_0"]  # base64-encoded basic auth


@pytest.mark.parametrize("builder_cls", ["DockerfileBuilder", "NixpacksBuilder"])
def test_build_job_never_puts_the_token_in_the_clone_url(builder_cls):
    builder = getattr(worker, builder_cls)()
    job = builder.generate_job_manifest(
        "abcdef12-0000", "https://github.com/o/r", "main",
        "us-central1-docker.pkg.dev/p/shipzen-builds/proj:dep", {"github_secret_name": "git-token-abcdef12"})
    spec = job["spec"]["template"]["spec"]
    clone = spec["initContainers"][0]
    text = str(clone)
    assert "x-access-token" not in text and "GITHUB_TOKEN" not in text and "sed" not in text
    env = {e["name"]: e for e in clone["env"]}
    assert env["GIT_CONFIG_VALUE_0"]["valueFrom"]["secretKeyRef"] == {
        "name": "git-token-abcdef12", "key": "GIT_AUTH_HEADER"}


def test_installation_tokens_are_scoped_to_one_repo():
    from shipzen_common import github_app
    install = MagicMock(status_code=200, json=lambda: {"id": 7})
    created = MagicMock(status_code=201, json=lambda: {"token": "t"})
    with patch.dict("os.environ", {"GITHUB_APP_ID": "1", "GITHUB_APP_PRIVATE_KEY": "k"}), \
         patch.object(github_app.jwt, "encode", lambda *a, **k: "jwt"), \
         patch.object(github_app.requests, "get", return_value=install), \
         patch.object(github_app.requests, "post", return_value=created) as post:
        assert github_app.get_github_app_token("https://github.com/o/r.git") == "t"
        assert post.call_args.kwargs["json"] == {"repositories": ["r"], "permissions": {"contents": "read"}}
        github_app.get_github_app_token("https://github.com/o/tenants", write=True)
        assert post.call_args.kwargs["json"]["permissions"] == {"contents": "write"}


def test_failed_state_stores_redacted_error():
    # The worker's modules are loaded side by side (tests/_component.py), so
    # patch the name the method actually resolves, in its own globals.
    get_conn = MagicMock()
    cur = MagicMock(rowcount=1)
    get_conn.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = cur
    with patch.dict(worker.StateMachine.update_state.__globals__, {"get_db_connection": get_conn}):
        sm = worker.StateMachine()
        sm._redis = MagicMock()
        sm.update_state("dep", "Failed", f"clone https://x-access-token:{FAKE_TOKEN}@github.com/o/r failed")
    stored = cur.execute.call_args[0][1][2]
    assert FAKE_TOKEN not in stored
    published = sm._redis.publish.call_args[0][1]
    assert FAKE_TOKEN not in published


# ── C4: builds push only to staging; apps run by digest ──────────────────────

DIGEST = "sha256:" + "a" * 64


@pytest.mark.parametrize("builder_cls", ["DockerfileBuilder", "NixpacksBuilder"])
def test_build_job_has_no_identity_and_reports_its_digest(builder_cls):
    builder = getattr(worker, builder_cls)()
    staging = "us-central1-docker.pkg.dev/p/shipzen-staging/proj:dep"
    job = builder.generate_job_manifest("abcdef12-0000", "https://github.com/o/r", "main", staging,
                                        {"registry_secret_name": "registry-abcdef12"})
    pod = job["spec"]["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False
    kaniko = next(c for c in pod["containers"] if c["name"] == "kaniko")
    assert f"--destination={staging}" in kaniko["args"]
    assert "--digest-file=/dev/termination-log" in kaniko["args"]
    assert not any(a.startswith("--cache") for a in kaniko["args"])  # no shared, poisonable cache
    assert {"name": "registry-auth", "mountPath": "/kaniko/.docker", "readOnly": True} in kaniko["volumeMounts"]
    vol = next(v for v in pod["volumes"] if v["name"] == "registry-auth")
    assert vol["secret"]["secretName"] == "registry-abcdef12"


def test_builds_push_to_staging_not_the_verified_registry():
    img = "us-central1-docker.pkg.dev/p/shipzen-builds/proj:dep"
    assert worker.staging_uri_for(img) == "us-central1-docker.pkg.dev/p/shipzen-staging/proj:dep"


def test_controller_pins_images_to_their_digest():
    assert controller.pinned_image({"image_uri": "r/shipzen-builds/p:d", "image_digest": DIGEST}) == f"r/shipzen-builds/p:d@{DIGEST}"
    assert controller.pinned_image({"image_uri": "r/shipzen-builds/p:d", "image_digest": None}) == "r/shipzen-builds/p:d"
    assert controller.pinned_image({"image_uri": "r/x:d", "image_digest": "sha256:short"}) == "r/x:d"


@pytest.mark.parametrize("message,ok", [(DIGEST, True), (DIGEST + "\n", True), ("", False), ("latest", False)])
def test_build_digest_comes_only_from_kaniko_termination_message(message, ok):
    status = MagicMock(state=MagicMock(terminated=MagicMock(message=message)))
    status.name = "kaniko"
    pod = MagicMock(status=MagicMock(container_statuses=[status]))
    with patch.dict(worker._build_digest.__globals__, {"core_v1": MagicMock(read_namespaced_pod=MagicMock(return_value=pod))}):
        if ok:
            assert worker._build_digest("pod") == DIGEST
        else:
            with pytest.raises(RuntimeError):
                worker._build_digest("pod")


# ── Task 25: secrets stored in Postgres are encrypted when a key is set ───────

def _crypto_box():
    import importlib.util
    spec = importlib.util.spec_from_file_location("shipzen_crypto_box", ROOT / "api" / "crypto_box.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_webhook_secrets_are_encrypted_with_a_key():
    from cryptography.fernet import Fernet
    box = _crypto_box()
    with patch.dict("os.environ", {"SHIPZEN_DATA_KEY": Fernet.generate_key().decode()}):
        stored = box.encrypt_value("hmac-secret")
        assert stored.startswith("enc:v1:") and "hmac-secret" not in stored
        assert box.decrypt_value(stored) == "hmac-secret"
        assert box.decrypt_value("legacy-plain") == "legacy-plain"   # old rows still work


def test_without_a_key_values_are_stored_as_before():
    box = _crypto_box()
    with patch.dict("os.environ", {"SHIPZEN_DATA_KEY": ""}):
        assert box.encrypt_value("hmac-secret") == "hmac-secret"
        with pytest.raises(RuntimeError):
            box.decrypt_value("enc:v1:abc")
