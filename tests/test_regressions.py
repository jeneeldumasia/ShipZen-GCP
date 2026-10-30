"""Regression tests for bugs found in the October 2026 review and live testing.

Each test names the bug it pins. Tests that need PostgreSQL skip when it isn't
reachable at DATABASE_URL; everything else runs with no external services.
"""
import asyncio
import datetime
import inspect
import time
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, patch

import pytest
import yaml

from _component import ROOT, load, postgres_available

api = load("api")
worker = load("worker")
controller = load("controller")

needs_pg = pytest.mark.skipif(not postgres_available(), reason="PostgreSQL not reachable at DATABASE_URL")


# ── API ──────────────────────────────────────────────────────────────────────

def test_project_name_cannot_inject_yaml():
    """A quote/newline/--- in a project name used to add objects to GitOps YAML."""
    evil = 'demo"\n---\nkind: ClusterRoleBinding'
    with pytest.raises(Exception):
        api.CreateProjectRequest(name=evil, namespace="demo-ns")
    assert api.CreateProjectRequest(name="My App 2", namespace="demo-ns").name == "My App 2"


def test_restart_targets_the_deployment_the_controller_creates():
    """Restart patched '<id[:8]>-<name>'; the controller names Deployments by full id."""
    src = inspect.getsource(api.restart_deployment)
    assert "deployment_name = deployment_id" in src


def test_rate_limit_key_ignores_spoofable_headers():
    def req(headers):
        return NS(headers=headers, client=NS(host="10.0.0.5"), scope={"client": ("10.0.0.5", 1)})
    with patch.object(api, "get_remote_address", lambda r: "10.0.0.5"):
        a = api._user_id_or_ip(req({"CF-Connecting-IP": "1.2.3.4", "Authorization": "Bearer aaa"}))
        b = api._user_id_or_ip(req({"CF-Connecting-IP": "1.2.3.4", "Authorization": "Bearer bbb",
                                    "X-Forwarded-For": "9.9.9.9"}))
    assert a == b == "ip:1.2.3.4"  # rotating tokens or faking XFF no longer changes the bucket


def test_metrics_endpoint_is_internal_only():
    from fastapi.testclient import TestClient
    client = TestClient(api.app)
    assert client.get("/metrics", headers={"CF-Connecting-IP": "1.2.3.4"}).status_code == 404
    r = client.get("/metrics")
    assert r.status_code == 200 and "shipzen_api_requests_total" in r.text


def test_github_allowlist_rejects_unlisted_users():
    auth = api.get_current_user.__globals__  # api's auth module namespace
    resp_user = MagicMock(status_code=200, json=lambda: {"id": 42, "login": "stranger"})
    resp_mail = MagicMock(status_code=200, json=lambda: [])
    client = MagicMock()
    client.get = MagicMock(side_effect=[resp_user, resp_mail])
    from fastapi.security import HTTPAuthorizationCredentials
    with patch.dict(auth, {"_http_client": client, "GITHUB_ENABLED": True,
                           "ALLOWED_GITHUB_USERS": {"jeneeldumasia"}}):
        async def call():
            fut = asyncio.Future(); fut.set_result(None)
            client.get.side_effect = [_awaitable(resp_user), _awaitable(resp_mail)]
            return await auth["get_current_user"](HTTPAuthorizationCredentials(scheme="Bearer", credentials="tok-x"))
        with pytest.raises(Exception) as e:
            asyncio.run(call())
    assert getattr(e.value, "status_code", None) == 403


def _awaitable(value):
    async def _f():
        return value
    return _f()


@pytest.mark.asyncio
async def test_sse_log_stream_honours_its_deadline():
    """The 5-minute SSE cap was only checked when a message arrived."""
    resp = await api.stream_logs("p1", "quiet", project={})
    gen = resp.body_iterator
    real, calls = time.time, {"n": 0}

    def clock():
        calls["n"] += 1
        return real() if calls["n"] <= 2 else real() + 600

    pubsub = MagicMock()
    pubsub.subscribe = MagicMock(side_effect=lambda *a: _awaitable(None))
    pubsub.get_message = MagicMock(side_effect=lambda **k: _awaitable(None))
    pubsub.unsubscribe = MagicMock(side_effect=lambda *a: _awaitable(None))
    pubsub.close = MagicMock(side_effect=lambda *a: _awaitable(None))
    with patch.object(api._aioredis_client, "pubsub", return_value=pubsub), patch.object(api.time, "time", clock):
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(gen.__anext__(), timeout=3)


# ── API + PostgreSQL ─────────────────────────────────────────────────────────

@pytest.fixture
def db():
    import os, psycopg2
    from psycopg2.extras import DictCursor
    conn = psycopg2.connect(os.environ["DATABASE_URL"]); conn.autocommit = True
    cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    cur.execute((ROOT / "api" / "schema.sql").read_text())
    cur.execute("INSERT INTO users (id,email,role) VALUES ('owner','o@x','user'),('viewer','v@x','user')")
    cur.execute("INSERT INTO projects (id,owner_id,name,namespace,status) VALUES ('p1','owner','demo','demo-ns','Ready')")
    cur.execute("INSERT INTO project_members VALUES ('p1','owner','owner'),('p1','viewer','viewer')")
    yield cur
    conn.close()


def _client_as(user_id):
    from fastapi.testclient import TestClient
    auth_get_user = api.get_current_user
    api.app.dependency_overrides[auth_get_user] = lambda: NS(user_id=user_id, role="user", is_admin=False)
    return TestClient(api.app)


@needs_pg
def test_viewer_cannot_deploy(db):
    r = _client_as("viewer").post("/projects/p1/deployments", json={"repo_url": "https://github.com/x/y"})
    api.app.dependency_overrides.clear()
    assert r.status_code == 403


@needs_pg
def test_rollback_goes_to_the_previous_release(db):
    def release(dep_id, image):
        db.execute("INSERT INTO deployments (deployment_id,project_id,repo_url,image_uri,replicas,port,state) "
                   "VALUES (%s,'p1','r',%s,1,8080,'Running')", (dep_id, image))
        db.execute("UPDATE deployments SET replicas = 0 WHERE project_id='p1' AND deployment_id != %s "
                   "AND state='Running' AND replicas > 0", (dep_id,))
        time.sleep(0.02)
    release("v1", "app:v1"); release("v2", "app:v2")
    r = _client_as("owner").post("/projects/p1/rollback")
    api.app.dependency_overrides.clear()
    db.execute("SELECT image_uri, replicas FROM deployments WHERE deployment_id=%s", (r.json()["deployment_id"],))
    assert dict(db.fetchone()) == {"image_uri": "app:v1", "replicas": 1}


@needs_pg
def test_first_user_is_not_automatically_admin(db, monkeypatch):
    database = api.get_current_user.__globals__.get("get_or_create_user") or __import__("database").get_or_create_user
    db.execute("DELETE FROM project_members; DELETE FROM projects; DELETE FROM users;")
    monkeypatch.delenv("ADMIN_EMAILS", raising=False)
    monkeypatch.setenv("ADMIN_GITHUB_USERS", "jeneeldumasia")
    assert database("u1", "a@x", "someone")["role"] == "user"
    assert database("u2", "b@x", "jeneeldumasia")["role"] == "admin"


# ── Worker ───────────────────────────────────────────────────────────────────

def test_worker_releases_slot_on_rollback_messages():
    """Early returns skipped the semaphore release; 20 rollbacks froze the worker."""
    sm = MagicMock(); sm.get_deployment.return_value = {"state": "Queued", "project_id": "p1"}
    start = worker._semaphore._value
    for i in range(25):
        worker._semaphore.acquire()
        worker._process_and_release(MagicMock(), sm, "1-0",
                                    {"deployment_id": f"d{i}", "repo_url": "r", "image_name": "i", "is_rollback": "true"})
    assert worker._semaphore._value == start


def test_worker_reads_init_container_logs():
    c = MagicMock()
    c.read_namespaced_pod.return_value = NS(spec=NS(init_containers=[NS(name="setup")], containers=[NS(name="kaniko")]))
    c.read_namespaced_pod_log.side_effect = lambda **k: {"setup": "cloning\n", "kaniko": "pushed\n"}[k["container"]]
    with patch.object(worker, "core_v1", c):
        assert worker._build_containers("pod") == ["setup", "kaniko"]
        assert worker._read_container_log("pod", "setup") == "cloning\n"


def test_crane_token_is_not_passed_on_the_command_line():
    src = inspect.getsource(worker.monitor_job)
    assert "--password-stdin" in src and '"-p", password' not in src


# ── Controller ───────────────────────────────────────────────────────────────

def test_superseded_release_is_not_marked_crashlooping():
    controller.commit_manifests_to_git = MagicMock()
    controller._redis_client = MagicMock()
    now = datetime.datetime.now(datetime.timezone.utc)
    rows = [{"deployment_id": "old", "state": "Running", "replicas": 0, "image_uri": "i:1", "updated_at": now},
            {"deployment_id": "new", "state": "Running", "replicas": 1, "image_uri": "i:2", "updated_at": now}]

    def k8s(img, n, ready):
        return NS(spec=NS(replicas=n, template=NS(spec=NS(containers=[NS(image=img)]))),
                  status=NS(ready_replicas=ready, conditions=[]))
    deps = {"ns": {"old": k8s("i:1", 0, 0), "new": k8s("i:2", 1, 1)}}
    names = {"ns": {"old-svc", "new-svc"}}, {"ns": {"old-route", "new-route"}}, {"ns": {"old-secrets", "new-secrets"}}
    cur = MagicMock(); cur.fetchall.return_value = rows
    for _ in range(3):
        controller.reconcile_deployments(MagicMock(), cur, NS(id="p1", namespace="ns", name="d"), deps, *names)
    failed = [c.args[1] for c in cur.execute.call_args_list if "last_error" in c.args[0] and c.args[1][0] == "Failed"]
    assert failed == []


def test_project_names_are_slugged_before_rendering():
    assert controller._k8s_slug('x"\n---\nkind: Evil') == "x-kind-evil"
    assert controller._k8s_slug("My App") == "my-app"


def test_orphan_gc_removes_only_unowned_folders():
    listing = {"namespaces": [{"name": n, "type": "dir"} for n in ("live", "orphan")],
               "orphan": [{"name": "tenant.yaml", "type": "file"}]}

    def fake_get(url, **k):
        return MagicMock(status_code=200, json=lambda: listing[url.rstrip("/").split("/")[-1]])
    deleted = []
    with patch.object(controller, "get_github_app_token", lambda u: "t"), \
         patch.object(controller.requests, "get", fake_get), \
         patch.object(controller, "commit_manifests_to_git", lambda ns, fn, c, delete=False: deleted.append(ns)):
        controller._orphan_gc_counter = controller.ORPHAN_GC_EVERY - 1
        controller.gc_orphan_tenant_folders({"live"})
    assert deleted == ["orphan"]


def test_controller_health_fails_when_loop_stalls():
    h = controller._health
    h.update(loop_tick=time.time(), leader=True, last_reconcile=time.time())
    assert controller._health_status()[0] == 200
    h.update(loop_tick=time.time() - controller.LOOP_STALE_SECONDS - 1)
    assert controller._health_status()[0] == 503


# ── Manifests and observability config ───────────────────────────────────────

def test_tenant_appset_cascades_deletes():
    appset = yaml.safe_load((ROOT / "infra/system/applicationset.yaml").read_text())
    assert "resources-finalizer.argocd.argoproj.io" in appset["spec"]["template"]["metadata"]["finalizers"]


def test_alert_rules_and_dashboards_only_query_exported_metrics():
    import re
    exported = set()
    for f in ("worker/metrics.py", "controller/metrics.py", "api/main.py"):
        exported |= set(re.findall(r"['\"](shipzen_[a-z_]+)['\"]", (ROOT / f).read_text()))
    rules = (ROOT / "infra/system/shipzen-alerts.yaml").read_text() + (ROOT / "infra/system/grafana-dashboards.yaml").read_text()
    used = {m.rstrip("_") for m in re.findall(r"\b(shipzen_[a-z_]+?)(?:_bucket|_count|_sum)?\b(?=[\[{(\s>])", rules)}
    missing = {m for m in used if m not in exported and not m.startswith("shipzen_io")}
    assert not missing, f"rules query metrics nothing exports: {missing}"


def test_grafana_dashboards_are_generated_from_source():
    """infra/system/grafana-dashboards.yaml must be the output of observability/dashboards.py."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("dashboards", ROOT / "observability/dashboards.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    assert (ROOT / "infra/system/grafana-dashboards.yaml").read_text() == mod.render(), \
        "run: python observability/dashboards.py"


def test_every_shipzen_alert_has_plain_language_text():
    import importlib.util
    spec = importlib.util.spec_from_file_location("dashboards", ROOT / "observability/dashboards.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    rules = yaml.safe_load((ROOT / "infra/system/shipzen-alerts.yaml").read_text())
    names = {r["alert"] for g in rules["spec"]["groups"] for r in g["rules"]}
    assert names <= set(mod.PROBLEM_TEXT), f"add to PROBLEM_TEXT: {names - set(mod.PROBLEM_TEXT)}"


@pytest.mark.parametrize("gh_status,remaining,expected", [(401, "4999", 401), (403, "0", 503), (502, None, 503)])
def test_github_errors_are_not_all_reported_as_invalid_token(gh_status, remaining, expected):
    """Any non-200 from GitHub used to become 401 'Invalid GitHub token'."""
    auth = api.get_current_user.__globals__
    resp = MagicMock(status_code=gh_status, text="x", headers={"X-RateLimit-Remaining": remaining} if remaining else {})
    client = MagicMock(); client.get = MagicMock(side_effect=lambda *a, **k: _awaitable(resp))
    from fastapi.security import HTTPAuthorizationCredentials
    with patch.dict(auth, {"_http_client": client, "GITHUB_ENABLED": True, "ALLOWED_GITHUB_USERS": set()}):
        with pytest.raises(Exception) as e:
            asyncio.run(auth["get_current_user"](HTTPAuthorizationCredentials(scheme="Bearer", credentials=f"t-{gh_status}")))
    assert getattr(e.value, "status_code", None) == expected
