"""Contract tests for the ShipZen API: what each endpoint does, seen over HTTP.

They pin down current behaviour (status codes, who may do what, what lands in
the database) so the API can be reorganised internally and checked against
them. They deliberately don't depend on where code lives: dependencies are
stubbed by name in whichever API module holds them (see `_stub`), and
authentication is replaced with FastAPI's dependency override.

Needs Docker (a throwaway Postgres container), like test_core.py.
"""
import hashlib
import hmac
import json
import os
import types
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import psycopg2
import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute, APIWebSocketRoute
from fastapi.testclient import TestClient

from _component import ROOT, load
from _docker import is_docker_running

api = load("api")
app = api.app


# ── Route table: every endpoint still exists (no Docker needed) ──────────────

EXPECTED_ROUTES = {
    ("GET", "/metrics"), ("GET", "/healthz"),
    ("POST", "/projects"), ("GET", "/projects"), ("GET", "/projects/{project_id}"),
    ("DELETE", "/projects/{project_id}"), ("POST", "/projects/analyze"),
    ("GET", "/projects/{project_id}/members"), ("POST", "/projects/{project_id}/members"),
    ("DELETE", "/projects/{project_id}/members/{target_user_id}"),
    ("POST", "/projects/{project_id}/deployments"), ("GET", "/projects/{project_id}/deployments"),
    ("GET", "/projects/{project_id}/deployments/{deployment_id}"),
    ("POST", "/projects/{project_id}/deployments/{deployment_id}/cancel"),
    ("POST", "/projects/{project_id}/deployments/{deployment_id}/restart"),
    ("POST", "/projects/{project_id}/rollback"),
    ("WS", "/ws/projects/{project_id}/deployments/{deployment_id}/status"),
    ("WS", "/ws/projects/{project_id}/deployments/{deployment_id}/logs"),
    ("GET", "/projects/{project_id}/deployments/{deployment_id}/logs/stream"),
    ("GET", "/projects/{project_id}/deployments/{deployment_id}/builds"),
    ("GET", "/projects/{project_id}/deployments/{deployment_id}/builds/{build_id}/logs"),
    ("GET", "/projects/{project_id}/audit"), ("GET", "/audit"),
    ("GET", "/projects/{project_id}/env"), ("PUT", "/projects/{project_id}/env"),
    ("DELETE", "/projects/{project_id}/env/{key}"),
    ("GET", "/projects/{project_id}/secrets"), ("POST", "/projects/{project_id}/secrets"),
    ("DELETE", "/projects/{project_id}/secrets/{key}"),
    ("GET", "/github/branches"),
    ("POST", "/webhooks/github/{project_id}"), ("POST", "/webhooks/github-app"),
    ("GET", "/users/me"),
    ("GET", "/admin/users"), ("PUT", "/admin/users/{user_id}/role"),
    ("GET", "/admin/audit-logs"), ("GET", "/admin/deployments"),
    ("POST", "/admin/system/restart"), ("GET", "/admin/metrics"),
}


def _routes():
    found = set()
    for r in app.routes:
        if isinstance(r, APIWebSocketRoute):
            found.add(("WS", r.path))
        elif isinstance(r, APIRoute):
            found |= {(m, r.path) for m in r.methods if m != "HEAD"}
    return found


def test_route_table_is_unchanged():
    assert _routes() == EXPECTED_ROUTES


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _api_module_dicts():
    """Globals of every API-code module reachable from the routes.

    Lets tests stub a dependency by name without knowing which module defines
    it, so they keep working when code moves between modules.
    """
    seen, out, todo = set(), [], []
    for r in app.routes:
        fn = getattr(r, "endpoint", None)
        if fn is not None:
            todo.append(fn)
    for dep in app.dependency_overrides:  # nothing yet, kept for completeness
        todo.append(dep)
    api_dir = str(ROOT / "api")
    while todo:
        obj = todo.pop()
        fn = getattr(obj, "__wrapped__", obj)
        g = getattr(fn, "__globals__", None)
        code = getattr(fn, "__code__", None)
        if g is None or code is None or not code.co_filename.startswith(api_dir):
            continue
        if id(g) not in seen:
            seen.add(id(g))
            out.append(g)
            for v in list(g.values()):
                if isinstance(v, types.FunctionType):
                    todo.append(v)
                elif isinstance(v, type):
                    todo.extend(m for m in vars(v).values() if isinstance(m, types.FunctionType))
    return out


def _find(name):
    for g in _api_module_dicts():
        if name in g:
            return g[name]
    raise LookupError(name)


class _Stubs:
    def __init__(self):
        self._saved = []

    def set(self, name, value):
        hit = False
        for g in _api_module_dicts():
            if name in g:
                self._saved.append((g, name, g[name]))
                g[name] = value
                hit = True
        assert hit, f"no API module defines {name}"

    def restore(self):
        for g, name, value in reversed(self._saved):
            g[name] = value


class FakeSecretManager:
    """Just enough of SecretManagerServiceClient for the env/secrets endpoints."""

    def __init__(self):
        self.data = {}

    @staticmethod
    def _sid(name):
        return name.split("/secrets/")[1].split("/")[0]

    def create_secret(self, request):
        sid = request["secret_id"]
        if sid in self.data:
            raise Exception("409 AlreadyExists")
        self.data[sid] = None

    def access_secret_version(self, request):
        value = self.data.get(self._sid(request["name"]))
        if value is None:
            raise Exception("404 NotFound")
        return SimpleNamespace(payload=SimpleNamespace(data=value))

    def add_secret_version(self, request):
        self.data[self._sid(request["parent"])] = request["payload"]["data"]

    def delete_secret(self, request):
        self.data.pop(self._sid(request["name"]), None)

    def keys(self, project_id):
        raw = self.data.get(f"shipzen-project-{project_id}")
        return set(json.loads(raw)) if raw else set()


def _sql(query, params=()):
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall() if cur.description else None
    finally:
        conn.close()


REPO_IDS = {"o/r": 1, "o/other": 2}
USERS = {"owner": "user", "editor": "user", "viewer": "user", "stranger": "user", "admin": "admin"}


@pytest.fixture
def env(postgres_container):
    if not is_docker_running():
        pytest.skip("Docker daemon is not running")
    _sql("ALTER TABLE audit_logs DISABLE TRIGGER trg_audit_logs_append_only;")
    _sql("TRUNCATE TABLE audit_logs, outbox_events, builds, deployments, project_members, "
         "projects, users RESTART IDENTITY CASCADE;")
    _sql("ALTER TABLE audit_logs ENABLE TRIGGER trg_audit_logs_append_only;")
    for uid, role in USERS.items():
        _sql("INSERT INTO users (id, email, role) VALUES (%s, %s, %s)", (uid, f"{uid}@example.com", role))

    stubs = _Stubs()
    stubs.set("DATABASE_URL", os.environ["DATABASE_URL"])
    stubs.set("db_pool", None)
    sm = FakeSecretManager()
    stubs.set("_sm_client", sm)
    stubs.set("GCP_PROJECT", "test-project")
    stubs.set("_redis_client", MagicMock())
    # GitHub repository access (C3): by default every repository is readable;
    # "id" comes from REPO_IDS so tests can name different repositories.
    access = {"deny": set()}

    def fake_check_repo_access(user, repo_url):
        if not repo_url.startswith("https://github.com/"):
            return None
        if repo_url in access["deny"]:
            raise HTTPException(status_code=403, detail="You don't have access")
        full = repo_url.split("github.com/", 1)[1].removesuffix(".git")
        return {"id": REPO_IDS.get(full, 1), "full_name": full, "private": True}
    stubs.set("check_repo_access", fake_check_repo_access)
    app.state.limiter.enabled = False

    user_cls = _find("User")
    who = {"id": "owner"}
    get_current_user = _find("get_current_user")
    app.dependency_overrides[get_current_user] = lambda: user_cls(user_id=who["id"], role=USERS[who["id"]])

    state = SimpleNamespace(client=TestClient(app), sm=sm, stubs=stubs, access=access,
                            as_user=lambda uid: who.update(id=uid))
    try:
        yield state
    finally:
        app.dependency_overrides.clear()
        app.state.limiter.enabled = True
        stubs.restore()


def _make_project(env, name="Demo", namespace=None):
    env.as_user("owner")
    ns = namespace or f"demo-{uuid.uuid4().hex[:8]}"
    r = env.client.post("/projects", json={"name": name, "namespace": ns,
                                           "repo_url": "https://github.com/o/r", "branch": "main"})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    _sql("UPDATE projects SET status = 'Ready' WHERE id = %s", (pid,))
    _sql("INSERT INTO project_members (project_id, user_id, role) VALUES (%s, 'editor', 'editor'), (%s, 'viewer', 'viewer')",
         (pid, pid))
    return pid


# ── Projects ─────────────────────────────────────────────────────────────────

def test_create_project_makes_caller_owner_and_hides_webhook_secret(env):
    env.as_user("owner")
    r = env.client.post("/projects", json={"name": "My App", "namespace": "my-app"})
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "Provisioning" and "webhook_secret" not in body
    assert _sql("SELECT role FROM project_members WHERE project_id = %s AND user_id = 'owner'", (body["id"],)) == [("owner",)]
    assert f"shipzen-project-{body['id']}" in env.sm.data  # an (empty) env-var secret exists
    assert _sql("SELECT action FROM audit_logs WHERE resource_id = %s", (body["id"],)) == [("CREATE",)]


@pytest.mark.parametrize("payload", [
    {"name": "ok", "namespace": "Bad_NS"},
    {"name": "ok", "namespace": "kube-system"},
    {"name": "ok", "namespace": "shipzen-anything"},
    {"name": 'evil"\n---', "namespace": "fine-ns"},
])
def test_create_project_rejects_invalid_input(env, payload):
    assert env.client.post("/projects", json=payload).status_code == 422


def test_create_project_duplicate_namespace_conflicts(env):
    _make_project(env, namespace="taken-ns")
    r = env.client.post("/projects", json={"name": "Other", "namespace": "taken-ns"})
    assert r.status_code == 409


def test_project_visibility(env):
    pid = _make_project(env)
    for uid in ("owner", "editor", "viewer", "admin"):
        env.as_user(uid)
        assert env.client.get(f"/projects/{pid}").status_code == 200, uid
        assert pid in [p["id"] for p in env.client.get("/projects").json()], uid
    env.as_user("stranger")
    assert env.client.get(f"/projects/{pid}").status_code == 403
    assert env.client.get("/projects").json() == []


def test_only_owner_or_admin_can_delete_project(env):
    pid = _make_project(env)
    for uid in ("editor", "viewer"):
        env.as_user(uid)
        assert env.client.delete(f"/projects/{pid}").status_code == 403, uid
    env.as_user("owner")
    assert env.client.delete(f"/projects/{pid}").status_code == 202
    assert _sql("SELECT status FROM projects WHERE id = %s", (pid,)) == [("Terminating",)]
    assert f"shipzen-project-{pid}" not in env.sm.data
    env.as_user("owner")
    assert env.client.get(f"/projects/{pid}").status_code == 403  # soft-deleted projects disappear


# ── Members ──────────────────────────────────────────────────────────────────

def test_members_are_managed_by_owner_only(env):
    pid = _make_project(env)
    env.as_user("editor")
    assert env.client.get(f"/projects/{pid}/members").status_code == 403
    assert env.client.post(f"/projects/{pid}/members", json={"email": "stranger@example.com", "role": "viewer"}).status_code == 403

    env.as_user("owner")
    roles = {m["user_id"]: m["role"] for m in env.client.get(f"/projects/{pid}/members").json()}
    assert roles == {"owner": "owner", "editor": "editor", "viewer": "viewer"}
    r = env.client.post(f"/projects/{pid}/members", json={"email": "stranger@example.com", "role": "viewer"})
    assert r.status_code == 201 and r.json()["role"] == "viewer"
    assert env.client.post(f"/projects/{pid}/members", json={"email": "stranger@example.com", "role": "viewer"}).status_code == 409
    assert env.client.post(f"/projects/{pid}/members", json={"email": "nobody@example.com", "role": "viewer"}).status_code == 404
    assert env.client.post(f"/projects/{pid}/members", json={"email": "x@example.com", "role": "owner"}).status_code == 422


def test_member_removal_rules(env):
    pid = _make_project(env)
    env.as_user("owner")
    assert env.client.delete(f"/projects/{pid}/members/owner").status_code == 403  # yourself
    env.as_user("admin")
    assert env.client.delete(f"/projects/{pid}/members/owner").status_code == 403  # the owner
    env.as_user("owner")
    assert env.client.delete(f"/projects/{pid}/members/viewer").status_code == 200
    assert env.client.delete(f"/projects/{pid}/members/viewer").status_code == 404


# ── Deployments ──────────────────────────────────────────────────────────────

def test_deploy_requires_write_access_and_queues_through_outbox(env):
    pid = _make_project(env)
    body = {"repo_url": "https://github.com/o/r", "branch": "main", "port": 3000}
    env.as_user("viewer")
    assert env.client.post(f"/projects/{pid}/deployments", json=body).status_code == 403
    env.as_user("stranger")
    assert env.client.post(f"/projects/{pid}/deployments", json=body).status_code == 403

    env.as_user("editor")
    r = env.client.post(f"/projects/{pid}/deployments", json=body)
    assert r.status_code == 202
    dep = r.json()
    assert dep["state"] == "Queued" and dep["port"] == 3000 and dep["replicas"] == 1
    assert dep["image_uri"].endswith(f"shipzen-builds/{pid}:{dep['deployment_id']}")
    (payload,) = _sql("SELECT payload FROM outbox_events")[0]
    payload = payload if isinstance(payload, dict) else json.loads(payload)
    assert payload["deployment_id"] == dep["deployment_id"] and payload["branch"] == "main"

    # One in-flight deployment per project.
    assert env.client.post(f"/projects/{pid}/deployments", json=body).status_code == 409


@pytest.mark.parametrize("body", [
    {"repo_url": "file:///etc/passwd"},
    {"repo_url": "https://github.com/o/r\nx"},
    {"repo_url": "https://github.com/o/r", "port": 0},
])
def test_deploy_rejects_invalid_input(env, body):
    pid = _make_project(env)
    env.as_user("owner")
    assert env.client.post(f"/projects/{pid}/deployments", json=body).status_code == 422


def test_deployment_listing_and_lookup(env):
    pid = _make_project(env)
    env.as_user("owner")
    dep = env.client.post(f"/projects/{pid}/deployments", json={"repo_url": "https://github.com/o/r"}).json()
    env.as_user("viewer")
    listed = env.client.get(f"/projects/{pid}/deployments").json()
    assert [d["deployment_id"] for d in listed] == [dep["deployment_id"]]
    assert env.client.get(f"/projects/{pid}/deployments/{dep['deployment_id']}").status_code == 200
    assert env.client.get(f"/projects/{pid}/deployments/nope").status_code == 404
    assert env.client.get(f"/projects/{pid}/deployments?cursor=garbage").status_code == 400


def test_cancel(env):
    pid = _make_project(env)
    env.as_user("owner")
    dep = env.client.post(f"/projects/{pid}/deployments", json={"repo_url": "https://github.com/o/r"}).json()
    did = dep["deployment_id"]
    env.as_user("viewer")
    assert env.client.post(f"/projects/{pid}/deployments/{did}/cancel").status_code == 403
    env.as_user("editor")
    assert env.client.post(f"/projects/{pid}/deployments/{did}/cancel").status_code == 202
    assert _sql("SELECT state, last_error FROM deployments WHERE deployment_id = %s", (did,)) == [("Failed", "Cancelled by user")]
    assert env.client.post(f"/projects/{pid}/deployments/{did}/cancel").status_code == 400


def test_rollback(env):
    pid = _make_project(env)
    env.as_user("owner")
    assert env.client.post(f"/projects/{pid}/rollback").status_code == 409  # nothing to roll back to
    _sql("""INSERT INTO deployments (deployment_id, project_id, repo_url, image_uri, replicas, port, state, created_at)
            VALUES ('old', %s, 'https://github.com/o/r', 'img:old', 0, 8080, 'Running', NOW() - INTERVAL '1 hour'),
                   ('live', %s, 'https://github.com/o/r', 'img:live', 1, 8080, 'Running', NOW())""", (pid, pid))
    env.as_user("viewer")
    assert env.client.post(f"/projects/{pid}/rollback").status_code == 403
    env.as_user("editor")
    r = env.client.post(f"/projects/{pid}/rollback")
    assert r.status_code == 202
    new = r.json()["deployment_id"]
    assert _sql("SELECT image_uri, replicas, state FROM deployments WHERE deployment_id = %s", (new,)) == [("img:old", 1, "Queued")]


def test_restart_patches_the_kubernetes_deployment(env):
    pid = _make_project(env)
    apps = MagicMock()
    env.stubs.set("apps_v1", apps)
    _sql("INSERT INTO deployments (deployment_id, project_id, repo_url, image_uri, replicas, port, state) "
         "VALUES ('dep1', %s, 'https://github.com/o/r', 'img', 1, 8080, 'Running')", (pid,))
    env.as_user("viewer")
    assert env.client.post(f"/projects/{pid}/deployments/dep1/restart").status_code == 403
    env.as_user("editor")
    assert env.client.post(f"/projects/{pid}/deployments/dep1/restart").status_code == 200
    kwargs = apps.patch_namespaced_deployment.call_args.kwargs
    assert kwargs["name"] == "dep1"
    assert "kubectl.kubernetes.io/restartedAt" in kwargs["body"]["spec"]["template"]["metadata"]["annotations"]


# ── Env vars and secrets ─────────────────────────────────────────────────────

def test_env_vars(env):
    pid = _make_project(env)
    env.as_user("viewer")
    assert env.client.put(f"/projects/{pid}/env", json={"key": "API_KEY", "value": "x"}).status_code == 403
    env.as_user("editor")
    assert env.client.put(f"/projects/{pid}/env", json={"key": "API_KEY", "value": "s3cret"}).status_code == 200
    assert env.client.put(f"/projects/{pid}/env", json={"key": "bad-key", "value": "x"}).status_code == 422
    env.as_user("viewer")
    r = env.client.get(f"/projects/{pid}/env")
    assert r.status_code == 200 and r.json() == {"keys": ["API_KEY"]}
    assert "s3cret" not in r.text
    env.as_user("editor")
    assert env.client.delete(f"/projects/{pid}/env/API_KEY").status_code == 200
    assert env.sm.keys(pid) == set()


def test_secrets_share_the_env_store_and_are_masked(env):
    pid = _make_project(env)
    env.as_user("editor")
    assert env.client.post(f"/projects/{pid}/secrets", json={"key": "DB_PASS", "value": "hunter2"}).status_code == 200
    env.as_user("viewer")
    r = env.client.get(f"/projects/{pid}/secrets")
    assert r.json() == {"secrets": [{"key": "DB_PASS", "value": "********"}]}
    assert env.client.get(f"/projects/{pid}/env").json() == {"keys": ["DB_PASS"]}
    assert env.client.delete(f"/projects/{pid}/secrets/DB_PASS").status_code == 403
    env.as_user("editor")
    assert env.client.delete(f"/projects/{pid}/secrets/DB_PASS").status_code == 200
    assert env.sm.keys(pid) == set()


# ── Audit, users, admin ──────────────────────────────────────────────────────

def test_audit_log_visibility(env):
    pid = _make_project(env)
    env.as_user("viewer")
    actions = [a["action"] for a in env.client.get(f"/projects/{pid}/audit").json()]
    assert "CREATE" in actions
    env.as_user("stranger")
    assert env.client.get(f"/projects/{pid}/audit").status_code == 403
    assert env.client.get("/audit").json() == []


def test_users_me(env):
    env.as_user("admin")
    assert env.client.get("/users/me").json() == {
        "user_id": "admin", "email": "admin@example.com", "role": "admin", "is_admin": True}


@pytest.mark.parametrize("method,path", [
    ("get", "/admin/users"), ("get", "/admin/audit-logs"), ("get", "/admin/deployments"),
])
def test_admin_endpoints(env, method, path):
    env.as_user("owner")
    assert getattr(env.client, method)(path).status_code == 403
    env.as_user("admin")
    assert getattr(env.client, method)(path).status_code == 200


def test_admin_role_changes(env):
    env.as_user("owner")
    assert env.client.put("/admin/users/viewer/role", json={"role": "admin"}).status_code == 403
    env.as_user("admin")
    assert env.client.put("/admin/users/viewer/role", json={"role": "superuser"}).status_code == 400
    assert env.client.put("/admin/users/ghost/role", json={"role": "admin"}).status_code == 404
    assert env.client.put("/admin/users/viewer/role", json={"role": "admin"}).status_code == 200
    assert _sql("SELECT role FROM users WHERE id = 'viewer'") == [("admin",)]


# ── Webhooks ─────────────────────────────────────────────────────────────────

def _signed(secret, body):
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_project_webhook_signature_and_branch(env):
    pid = _make_project(env)
    (secret,) = _sql("SELECT webhook_secret FROM projects WHERE id = %s", (pid,))[0]
    url = f"/webhooks/github/{pid}"
    push = {"X-GitHub-Event": "push"}

    assert env.client.post(url, content=b"{}", headers=push).status_code == 400  # no signature
    assert env.client.post(url, content=b"{}", headers={**push, "x-hub-signature-256": "sha256=bad"}).status_code == 401

    other = json.dumps({"ref": "refs/heads/dev", "repository": {"id": 1, "clone_url": "https://github.com/o/r.git"}}).encode()
    r = env.client.post(url, content=other, headers={**push, "x-hub-signature-256": _signed(secret, other)})
    assert r.status_code == 200 and "Ignored" in r.json()["message"]

    main = json.dumps({"ref": "refs/heads/main", "repository": {"id": 1, "clone_url": "https://github.com/o/r.git"}}).encode()
    r = env.client.post(url, content=main, headers={**push, "x-hub-signature-256": _signed(secret, main)})
    assert r.status_code == 200 and r.json()["deployment_id"]
    assert _sql("SELECT state FROM deployments WHERE project_id = %s", (pid,)) == [("Queued",)]

    ping = {"X-GitHub-Event": "ping", "x-hub-signature-256": "sha256=whatever"}
    assert env.client.post(url, content=b"{}", headers=ping).json() == {"message": "event ignored"}


# ── C3: repository access and project binding ────────────────────────────────

def test_project_creation_refuses_a_repo_the_user_cannot_read(env):
    env.access["deny"].add("https://github.com/someone/private")
    env.as_user("owner")
    r = env.client.post("/projects", json={"name": "x", "namespace": "x-ns",
                                           "repo_url": "https://github.com/someone/private"})
    assert r.status_code == 403
    assert _sql("SELECT count(*) FROM projects") == [(0,)]


def test_project_records_the_repo_it_is_bound_to(env):
    pid = _make_project(env)
    assert _sql("SELECT github_repo_id, github_repo_full_name FROM projects WHERE id = %s", (pid,)) == [(1, "o/r")]


def test_deploy_refuses_a_repo_the_user_cannot_read(env):
    pid = _make_project(env)
    env.access["deny"].add("https://github.com/someone/private")
    env.as_user("editor")
    r = env.client.post(f"/projects/{pid}/deployments", json={"repo_url": "https://github.com/someone/private"})
    assert r.status_code == 403
    assert _sql("SELECT count(*) FROM deployments") == [(0,)]


def test_deploy_must_use_the_projects_repo(env):
    pid = _make_project(env)  # bound to o/r
    env.as_user("editor")
    r = env.client.post(f"/projects/{pid}/deployments", json={"repo_url": "https://github.com/o/other"})
    assert r.status_code == 403 and "o/r" in r.json()["detail"]


def test_first_github_deploy_binds_an_unbound_project(env):
    env.as_user("owner")
    r = env.client.post("/projects", json={"name": "Loose", "namespace": "loose-ns"})
    pid = r.json()["id"]
    _sql("UPDATE projects SET status = 'Ready' WHERE id = %s", (pid,))
    assert env.client.post(f"/projects/{pid}/deployments", json={"repo_url": "https://github.com/o/other"}).status_code == 202
    assert _sql("SELECT github_repo_id FROM projects WHERE id = %s", (pid,)) == [(2,)]


def test_project_webhook_ignores_pushes_from_another_repo(env):
    pid = _make_project(env)  # bound to repo id 1
    (secret,) = _sql("SELECT webhook_secret FROM projects WHERE id = %s", (pid,))[0]
    body = json.dumps({"ref": "refs/heads/main", "repository": {"id": 99, "clone_url": "https://github.com/o/r.git"}}).encode()
    r = env.client.post(f"/webhooks/github/{pid}", content=body,
                        headers={"X-GitHub-Event": "push", "x-hub-signature-256": _signed(secret, body)})
    assert r.status_code == 403
