import pytest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException
import psycopg2
import os

from tests.test_core import postgres_container

def test_verify_project_access(postgres_container):
    from api.database import verify_project_access
    from api.auth import User
    
    # Setup test data
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("INSERT INTO users (id, email, role) VALUES ('admin1', 'admin@test.com', 'admin') ON CONFLICT DO NOTHING")
        cur.execute("INSERT INTO users (id, email, role) VALUES ('owner1', 'owner@test.com', 'user') ON CONFLICT DO NOTHING")
        cur.execute("INSERT INTO users (id, email, role) VALUES ('member1', 'member@test.com', 'user') ON CONFLICT DO NOTHING")
        cur.execute("INSERT INTO users (id, email, role) VALUES ('random1', 'random@test.com', 'user') ON CONFLICT DO NOTHING")
        
        cur.execute("INSERT INTO projects (id, owner_id, name, namespace) VALUES ('proj_rbac', 'owner1', 'p_rbac', 'ns_rbac') ON CONFLICT DO NOTHING")
        cur.execute("INSERT INTO project_members (project_id, user_id, role) VALUES ('proj_rbac', 'member1', 'viewer') ON CONFLICT DO NOTHING")
    conn.close()

    # 1. Admin should have access
    admin_user = User(user_id="admin1", role="admin")
    proj = verify_project_access("proj_rbac", admin_user)
    assert proj["id"] == "proj_rbac"

    # 2. Owner should have access
    owner_user = User(user_id="owner1", role="user")
    proj = verify_project_access("proj_rbac", owner_user)
    assert proj["id"] == "proj_rbac"

    # 3. Member should have access
    member_user = User(user_id="member1", role="user")
    proj = verify_project_access("proj_rbac", member_user)
    assert proj["id"] == "proj_rbac"

    # 4. Random user should be rejected
    random_user = User(user_id="random1", role="user")
    with pytest.raises(HTTPException) as exc:
        verify_project_access("proj_rbac", random_user)
    assert exc.value.status_code == 403
    assert "Forbidden" in str(exc.value.detail)

    # 5. Non-existent project should return 404
    with pytest.raises(HTTPException) as exc:
        verify_project_access("proj_not_found", admin_user)
    assert exc.value.status_code == 404
    assert "not found" in str(exc.value.detail).lower()
