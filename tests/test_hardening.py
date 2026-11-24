"""November hardening: GitOps manifest cache, tenant egress ports, shipzen.yaml schema."""
import base64
from unittest.mock import MagicMock, patch

import pytest
import yaml

from _component import ROOT, load

controller = load("controller")
api = load("api")


# ── Controller: manifest cache ───────────────────────────────────────────────

def _gh(existing=None):
    get = MagicMock()
    if existing is None:
        get.return_value = MagicMock(status_code=404)
    else:
        get.return_value = MagicMock(status_code=200, json=lambda: {
            "sha": "old", "content": base64.b64encode(existing.encode()).decode()})
    put = MagicMock(return_value=MagicMock(status_code=201, json=lambda: {"content": {"sha": "new"}}))
    return MagicMock(get=get, put=put, delete=MagicMock())


def _commit(requests_mock, clock, *args, **kwargs):
    g = controller.commit_manifests_to_git.__globals__
    with patch.dict(g, {"requests": requests_mock, "get_github_app_token": lambda *a, **k: "tok"}), \
         patch.object(g["time"], "monotonic", lambda: clock[0]):
        controller.commit_manifests_to_git(*args, **kwargs)


@pytest.fixture(autouse=True)
def _empty_cache():
    controller.commit_manifests_to_git.__globals__["_manifest_cache"].clear()
    yield


def test_unchanged_manifest_skips_github_until_the_cache_expires():
    gh, clock = _gh(), [1000.0]
    _commit(gh, clock, "ns", "a.yaml", "v1")
    assert gh.get.call_count == 1 and gh.put.call_count == 1

    _commit(gh, clock, "ns", "a.yaml", "v1")          # same content: no GitHub calls
    assert gh.get.call_count == 1 and gh.put.call_count == 1

    clock[0] += controller.MANIFEST_CACHE_TTL_SECONDS + 1
    gh.get.return_value = MagicMock(status_code=404)   # someone deleted it in Git
    _commit(gh, clock, "ns", "a.yaml", "v1")          # expired: checked again and repaired
    assert gh.get.call_count == 2 and gh.put.call_count == 2


def test_changed_manifest_is_written_even_when_cached():
    gh, clock = _gh(), [0.0]
    _commit(gh, clock, "ns", "a.yaml", "v1")
    _commit(gh, clock, "ns", "a.yaml", "v2")
    assert gh.put.call_count == 2


def test_failed_write_is_not_cached():
    gh, clock = _gh(), [0.0]
    gh.put.return_value = MagicMock(status_code=409, text="sha mismatch")
    _commit(gh, clock, "ns", "a.yaml", "v1")
    _commit(gh, clock, "ns", "a.yaml", "v1")
    assert gh.get.call_count == 2 and gh.put.call_count == 2


def test_matching_content_in_git_is_cached_without_a_commit():
    gh, clock = _gh(existing="v1"), [0.0]
    _commit(gh, clock, "ns", "a.yaml", "v1")
    _commit(gh, clock, "ns", "a.yaml", "v1")
    assert gh.get.call_count == 1 and gh.put.call_count == 0


def test_delete_clears_the_cache():
    gh, clock = _gh(), [0.0]
    _commit(gh, clock, "ns", "a.yaml", "v1")
    gh.get.return_value = MagicMock(status_code=200, json=lambda: {"sha": "new", "content": ""})
    _commit(gh, clock, "ns", "a.yaml", "", delete=True)
    assert gh.delete.call_count == 1
    gh.get.return_value = MagicMock(status_code=404)
    _commit(gh, clock, "ns", "a.yaml", "v1")          # written again, not skipped
    assert gh.put.call_count == 2


def test_no_direct_kubernetes_apply_fallback():
    """GitOps stays the only write path: a direct apply would fight ArgoCD's self-heal."""
    import inspect
    assert "apply_manifests" not in inspect.getsource(controller.commit_manifests_to_git)


# ── Controller: tenant egress ports ──────────────────────────────────────────

def _tenant_policy(monkeypatch, ports):
    monkeypatch.chdir(ROOT / "controller")
    g = controller.render_tenant.__globals__
    monkeypatch.setitem(g, "TENANT_EGRESS_PORTS", ports)
    docs = yaml.safe_load_all(controller.render_tenant("demo-ns", "p1", "Demo"))
    pol = next(d for d in docs if d and d["kind"] == "NetworkPolicy" and d["metadata"]["name"] == "tenant-isolation")
    return pol["spec"]["egress"][-1]


def test_tenant_internet_egress_is_unrestricted_by_default(monkeypatch):
    rule = _tenant_policy(monkeypatch, [])
    assert "ports" not in rule and rule["to"][0]["ipBlock"]["cidr"] == "0.0.0.0/0"


def test_tenant_internet_egress_can_be_limited_to_ports(monkeypatch):
    rule = _tenant_policy(monkeypatch, [443, 5432])
    assert rule["ports"] == [{"protocol": "TCP", "port": 443}, {"protocol": "TCP", "port": 5432}]
    assert "169.254.0.0/16" in rule["to"][0]["ipBlock"]["except"]  # metadata server still blocked


@pytest.mark.parametrize("raw,expected", [("", []), ("443, 80,443", [80, 443])])
def test_egress_ports_parsing(raw, expected):
    assert controller._egress_ports(raw) == expected


@pytest.mark.parametrize("raw", ["0", "70000", "http"])
def test_egress_ports_rejects_nonsense(raw):
    with pytest.raises(ValueError):
        controller._egress_ports(raw)


def test_build_namespace_internet_egress_is_web_and_ssh_only():
    pol = yaml.safe_load((ROOT / "infra/system/build-network-policy.yaml").read_text())
    internet = next(r for r in pol["spec"]["egress"] if "to" in r)
    assert sorted(p["port"] for p in internet["ports"]) == [22, 80, 443]


# ── API: one shipzen.yaml schema ─────────────────────────────────────────────

def test_analyze_accepts_build_context(tmp_path):
    analyzer = __import__("sys").modules.get("analyzer")
    if analyzer is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("analyzer_t", ROOT / "api" / "analyzer.py")
        analyzer = importlib.util.module_from_spec(spec); spec.loader.exec_module(analyzer)
    cfg = analyzer.ShipzenConfig(buildContext="apps/web/", port=3000)
    assert cfg.buildContext == "apps/web"
    with pytest.raises(Exception):
        analyzer.ShipzenConfig(buildContext="../secrets")
    (tmp_path / "shipzen.yaml").write_text("buildContext: web\nport: 3000\n")
    (tmp_path / "Dockerfile").write_text("FROM scratch\n")
    services = analyzer.RepoAnalyzer(str(tmp_path)).analyze()
    assert services[0].override_config["buildContext"] == "web"
