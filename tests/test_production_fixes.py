import os
import sys
import uuid
import pytest
from unittest.mock import patch, MagicMock

# Ensure DATABASE_URL is set before importing app modules
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = "postgresql://postgres:postgres@localhost:5432/shipzen_test"
if "REDIS_HOST" not in os.environ:
    os.environ["REDIS_HOST"] = "localhost"

API_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "api"))
CONTROLLER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "controller"))
WORKER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "worker"))

# --- 1. Token Cache Eviction Tests ---
def test_token_cache_eviction():
    sys.path.insert(0, API_DIR)
    import auth
    from auth import User, evict_user_token_cache, _token_cache, _user_to_cache_keys, _cache_lock

    user_id = "test-user-123"
    token_hash = "mock_hash_abc123"
    user_obj = User(user_id=user_id, role="admin")

    with _cache_lock:
        _token_cache[token_hash] = user_obj
        _user_to_cache_keys[user_id].add(token_hash)

    # Verify present
    assert token_hash in _token_cache
    assert token_hash in _user_to_cache_keys[user_id]

    # Evict
    evict_user_token_cache(user_id)

    # Verify evicted
    assert token_hash not in _token_cache
    assert user_id not in _user_to_cache_keys


# --- 2. Controller Leader Election Tests ---
def test_leader_elector_create_and_renew():
    sys.path.insert(0, CONTROLLER_DIR)
    # Remove cached metrics/database if any to ensure controller packages load
    for mod in ['metrics', 'models', 'database']:
        sys.modules.pop(mod, None)

    import controller.main as ctrl
    from controller.main import LeaderElector

    with patch("controller.main.k8s_coordination_api") as mock_coordination:
        from kubernetes.client.rest import ApiException
        import datetime

        # 1. Simulate 404 on read -> creates new lease
        mock_coordination.read_namespaced_lease.side_effect = ApiException(status=404)
        mock_coordination.create_namespaced_lease.return_value = MagicMock()

        elector = LeaderElector(lease_name="test-leader", lease_namespace="default")
        assert elector.is_leader is False

        acquired = elector.try_acquire_or_renew()
        assert acquired is True
        assert elector.is_leader is True
        assert mock_coordination.create_namespaced_lease.called

        # 2. Simulate renew
        mock_lease = MagicMock()
        mock_lease.spec.holder_identity = elector.holder_identity
        mock_lease.spec.renew_time = datetime.datetime.now(datetime.timezone.utc)
        mock_coordination.read_namespaced_lease.side_effect = None
        mock_coordination.read_namespaced_lease.return_value = mock_lease
        mock_coordination.replace_namespaced_lease.return_value = mock_lease

        renewed = elector.try_acquire_or_renew()
        assert renewed is True
        assert elector.is_leader is True

        # 3. Release
        elector.release()
        assert elector.is_leader is False
        assert mock_lease.spec.holder_identity is None


# --- 3. Event-Driven Workqueue Tests ---
def test_controller_workqueue():
    sys.path.insert(0, CONTROLLER_DIR)
    for mod in ['metrics', 'models', 'database']:
        sys.modules.pop(mod, None)

    from controller.main import _work_queue

    project_id = "test-project-uuid-99"
    _work_queue.put(project_id)
    assert not _work_queue.empty()
    item = _work_queue.get_nowait()
    assert item == project_id
    _work_queue.task_done()
    assert _work_queue.empty()


# --- 4. Distributed Tracing Middleware Tests ---
def test_trace_id_propagation():
    sys.path.insert(0, API_DIR)
    for mod in ['database', 'auth', 'audit']:
        sys.modules.pop(mod, None)

    from fastapi.testclient import TestClient
    import main as api_main

    client = TestClient(api_main.app)

    # 1. Custom Trace ID passed
    custom_trace = "custom-trace-uuid-12345"
    response = client.get("/healthz", headers={"X-Trace-ID": custom_trace})
    assert response.status_code == 200
    assert response.headers.get("X-Trace-ID") == custom_trace

    # 2. Auto-generated Trace ID when omitted
    response_auto = client.get("/healthz")
    assert response_auto.status_code == 200
    assert "X-Trace-ID" in response_auto.headers
    assert len(response_auto.headers["X-Trace-ID"]) > 10
