import pytest
from unittest.mock import patch, MagicMock
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer
import os
import threading
import psycopg2

import docker

def is_docker_running():
    try:
        client = docker.from_env()
        client.ping()
        return True
    except Exception:
        return False

pytestmark = pytest.mark.skipif(not is_docker_running(), reason="Docker daemon is not running")

# Set test environment variables BEFORE importing application code
os.environ["S3_LOG_BUCKET"] = "test-bucket"
os.environ["STREAM_NAME"] = "test_stream"
os.environ["CONSUMER_GROUP"] = "test_group"

@pytest.fixture(scope="session")
def postgres_container():
    with PostgresContainer("mirror.gcr.io/library/postgres:15-alpine", dbname="shipzen") as postgres:
        os.environ["DATABASE_URL"] = postgres.get_connection_url()
        # Initialize schema
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        conn.autocommit = True
        with conn.cursor() as cur:
            schema_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "api", "schema.sql")
            with open(schema_path, "r") as f:
                cur.execute(f.read())
        conn.close()
        yield postgres

@pytest.fixture(scope="session")
def redis_container():
    with RedisContainer("mirror.gcr.io/library/redis:7-alpine") as redis_server:
        os.environ["REDIS_HOST"] = redis_server.get_container_host_ip()
        os.environ["REDIS_PORT"] = redis_server.get_exposed_port(6379)
        yield redis_server

@pytest.fixture(autouse=True)
def setup_db(postgres_container):
    # Truncate tables before each test to ensure a clean state.
    # NOTE: env_vars is not part of the current schema (secrets are stored in
    # AWS Secrets Manager / LocalStack). Only truncate tables that exist.
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    conn.autocommit = True
    with conn.cursor() as cur:
        # Disable the append-only trigger on audit_logs so we can clean it up.
        cur.execute("ALTER TABLE audit_logs DISABLE TRIGGER trg_audit_logs_append_only;")
        cur.execute(
            "TRUNCATE TABLE audit_logs, outbox_events, builds, deployments, "
            "project_members, projects, users RESTART IDENTITY CASCADE;"
        )
        cur.execute("ALTER TABLE audit_logs ENABLE TRIGGER trg_audit_logs_append_only;")
    conn.close()

# --- 1. Deployment State Machine Transitions ---
def test_deployment_state_machine(postgres_container):
    from worker.state_machine import StateMachine, DeploymentState
    
    # Setup test data
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("INSERT INTO users (id, email, role) VALUES ('user1', 'test@test.com', 'admin')")
        cur.execute("INSERT INTO projects (id, owner_id, name, namespace) VALUES ('proj1', 'user1', 'p1', 'ns1')")
        cur.execute("INSERT INTO deployments (deployment_id, project_id, repo_url, port, state) VALUES ('dep1', 'proj1', 'http://repo', 80, 'Queued')")
    conn.close()

    sm = StateMachine()
    
    # Test Queued -> Deploying
    sm.update_state('dep1', DeploymentState.DEPLOYING)
    deployment = sm.get_deployment('dep1')
    assert deployment["state"] == DeploymentState.DEPLOYING
    
    # Test Deploying -> Running
    sm.update_state('dep1', DeploymentState.RUNNING)
    deployment = sm.get_deployment('dep1')
    assert deployment["state"] == DeploymentState.RUNNING

# --- 2. Rollback Flow End-to-End ---
def test_rollback_skips_build(redis_container, postgres_container):
    from worker.main import process_message
    
    # Setup test data
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("INSERT INTO users (id, email, role) VALUES ('user1', 'test@test.com', 'admin') ON CONFLICT DO NOTHING")
        cur.execute("INSERT INTO projects (id, owner_id, name, namespace) VALUES ('proj2', 'user1', 'p2', 'ns2')")
        cur.execute("INSERT INTO deployments (deployment_id, project_id, repo_url, port, state) VALUES ('dep2', 'proj2', 'http://repo', 80, 'Queued')")
    conn.close()

    payload = {
        "deployment_id": "dep2",
        "repo_url": "http://repo",
        "is_rollback": "true",
        "image_name": "123.dkr.ecr.us-east-1.amazonaws.com/app:abc123"
    }
    
    mock_queue = MagicMock()
    
    from worker.state_machine import StateMachine
    sm = StateMachine()

    # The actual regression guard: ensure subprocess.run (used for git clone and crane) is NOT called!
    with patch("worker.main.subprocess.run") as mock_sub:
        process_message(mock_queue, sm, "msg-123", payload)
        mock_sub.assert_not_called()
        
    deployment = sm.get_deployment('dep2')
    # Rollback should skip BUILD and immediately go to DEPLOYING
    assert deployment["state"] == "Deploying"

# --- 3. Webhook Handler ---
@pytest.mark.asyncio
async def test_webhook_handler_hmac_rejection(postgres_container):
    from api.main import github_webhook
    from fastapi import Request, HTTPException
    
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("INSERT INTO users (id, email, role) VALUES ('user1', 'test@test.com', 'admin') ON CONFLICT DO NOTHING")
        cur.execute("INSERT INTO projects (id, owner_id, name, namespace, webhook_secret) VALUES ('proj3', 'user1', 'p3', 'ns3', 'mysecret')")
    conn.close()

    mock_request = MagicMock(spec=Request)
    mock_request.headers = {
        "X-GitHub-Event": "push",
        "X-Hub-Signature-256": "sha256=invalid_signature_here"
    }
    mock_request.body = MagicMock(return_value=b'{"repository": {"clone_url": "http://repo"}}')
    
    with pytest.raises(HTTPException) as exc:
        await github_webhook(mock_request, "proj3")
    
    # CRIT-08 Fix: Wait, actual handler raises 401 for invalid signature, test asserted 403
    assert exc.value.status_code == 401
    assert "Invalid signature" in exc.value.detail

# --- 4. get_or_create_user Concurrent Inserts ---
def test_get_or_create_user_concurrent(postgres_container):
    from api.database import get_or_create_user
    
    results = []
    
    def worker():
        try:
            user = get_or_create_user("concurrent_user_1", "concurrent@test.com")
            results.append(user)
        except Exception as e:
            results.append(e)

    # Spawn multiple threads to trigger a race condition (UniqueViolation)
    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # All threads should have received a valid user dict, no Exceptions!
    for res in results:
        assert isinstance(res, dict)
        assert res["id"] == "concurrent_user_1"

# --- 5. Env Var Endpoints (Secret ID uses project ID, not project name) ---
def test_env_var_secret_id_uses_project_id():
    """
    Regression guard: the Secrets Manager secret key must be built from the
    project UUID, not from the human-readable project name, so two projects
    named "My Project" don't collide.
    """
    from api.main import put_env_var, PutEnvVarRequest
    from api.auth import User

    mock_user = User(user_id="user1", role="admin")

    # Capture whatever SecretId is used in the _sm_client.put_secret_value call.
    captured = {}

    def fake_get_secret_value(**kwargs):
        from botocore.exceptions import ClientError
        error = {"Error": {"Code": "ResourceNotFoundException", "Message": "not found"}}
        raise ClientError(error, "GetSecretValue")

    def fake_create_secret(**kwargs):
        captured["secret_id"] = kwargs.get("Name")
        return {"ARN": "arn:aws:secretsmanager:us-east-1:000000000000:secret:test"}

    with patch("api.main._sm_client") as mock_sm:
        mock_sm.get_secret_value.side_effect = fake_get_secret_value
        mock_sm.exceptions.ResourceNotFoundException = type(
            "ResourceNotFoundException", (Exception,), {}
        )
        mock_sm.create_secret.side_effect = fake_create_secret
        mock_sm.put_secret_value.return_value = {}

        mock_project = {"id": "proj4", "namespace": "ns4", "name": "My Project"}
        mock_request = MagicMock()

        body = PutEnvVarRequest(key="MY_VAR", value="myval")
        put_env_var(mock_request, "proj4", body, mock_project, mock_user)

    # THE REGRESSION GUARD: secret path must contain the UUID, NOT the name
    assert captured.get("secret_id") == "shipzen/project/proj4", (
        f"Expected 'shipzen/project/proj4' but got {captured.get('secret_id')!r}"
    )

# --- 6. Analyze Repo Branch Validation ---
@pytest.mark.asyncio
async def test_analyze_repo_branch_validation():
    """Branch names with spaces / special chars must be rejected with HTTP 400."""
    from api.main import analyze_repo, AnalyzeRequest
    from api.auth import User
    from fastapi import HTTPException

    mock_user = User(user_id="user1", role="admin")
    mock_request = MagicMock()

    class MockBody:
        repo_url = "https://github.com/test/test.git"
        branch = "invalid branch name with spaces!"

    with pytest.raises(HTTPException) as exc:
        await analyze_repo(mock_request, MockBody(), mock_user)

    assert exc.value.status_code == 400
    assert "Invalid branch name" in exc.value.detail
