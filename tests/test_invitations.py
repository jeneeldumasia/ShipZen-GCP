"""Invitations: admins let people in without editing ALLOWED_GITHUB_USERS.

The sign-in tests stub GitHub and the database module; the database tests run
the real SQL against a Postgres testcontainer and skip without Docker.
"""
import asyncio
import os
import sys
import types
from unittest.mock import MagicMock, patch

import pytest
from fastapi.security import HTTPAuthorizationCredentials

from _component import load
from _docker import is_docker_running

api = load("api")
auth = api.get_current_user.__globals__  # api's auth module namespace


def _awaitable(value):
    async def _f():
        return value
    return _f()


def _github(login="newcomer", uid=77, email="new@example.com"):
    user = MagicMock(status_code=200, json=lambda: {"id": uid, "login": login})
    mails = MagicMock(status_code=200, json=lambda: [{"email": email, "primary": True, "verified": True}])
    client = MagicMock()
    client.get = MagicMock(side_effect=[_awaitable(user), _awaitable(mails)])
    return client


def _fake_db(invitation=None, lookup_error=None, role_after_accept="user"):
    db = types.ModuleType("database")
    calls = {"find": [], "accept": []}

    def find_access_invitation(user_id, login, email):
        calls["find"].append((user_id, login, email))
        if lookup_error:
            raise lookup_error
        return invitation

    def accept_invitation(inv_id, user_id):
        calls["accept"].append((inv_id, user_id))
        return role_after_accept

    db.find_access_invitation = find_access_invitation
    db.accept_invitation = accept_invitation
    db.get_or_create_user = lambda uid, email, login: {"id": uid, "role": "user", "suspended": False}
    return db, calls


def _sign_in(client, db, token):
    with patch.dict(auth, {"_http_client": client, "GITHUB_ENABLED": True,
                           "ALLOWED_GITHUB_USERS": {"jeneeldumasia"}}), \
         patch.dict(sys.modules, {"database": db}):
        return asyncio.run(auth["get_current_user"](
            HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)))


def test_uninvited_user_is_refused():
    db, calls = _fake_db(invitation=None)
    with pytest.raises(Exception) as e:
        _sign_in(_github(), db, "tok-uninvited")
    assert getattr(e.value, "status_code", None) == 403
    assert calls["find"] == [("77", "newcomer", "new@example.com")]


def test_pending_invitation_lets_user_in_and_is_accepted():
    inv = {"id": "11111111-1111-1111-1111-111111111111", "role": "admin", "accepted_by": None}
    db, calls = _fake_db(invitation=inv, role_after_accept="admin")
    user = _sign_in(_github(), db, "tok-pending")
    assert user.user_id == "77" and user.role == "admin"
    assert calls["accept"] == [(inv["id"], "77")]


def test_accepted_invitation_is_standing_access():
    """Accepting must not end access: the next sign-in finds it by accepted_by."""
    inv = {"id": "22222222-2222-2222-2222-222222222222", "role": "user", "accepted_by": "77"}
    db, calls = _fake_db(invitation=inv)
    user = _sign_in(_github(), db, "tok-accepted")
    assert user.user_id == "77"
    assert calls["accept"] == []


def test_invitation_lookup_failure_fails_closed():
    db, _ = _fake_db(lookup_error=RuntimeError("db down"))
    with pytest.raises(Exception) as e:
        _sign_in(_github(), db, "tok-dbdown")
    assert getattr(e.value, "status_code", None) == 503


def test_allowlisted_user_skips_invitation_lookup():
    db, calls = _fake_db(invitation=None)
    user = _sign_in(_github(login="JeneelDumasia", uid=1), db, "tok-owner")
    assert user.user_id == "1" and calls["find"] == []


@pytest.mark.parametrize("body,ok", [
    ({"github_login": "octo-cat"}, True),
    ({"github_login": "@octocat"}, True),
    ({"email": "a@b.co", "role": "admin"}, True),
    ({"github_login": "-bad"}, False),
    ({"github_login": "a--b"}, False),
    ({"email": "nope"}, False),
    ({"github_login": "x", "role": "owner"}, False),
    ({"github_login": "x", "expires_in_days": 0}, False),
])
def test_invitation_request_validation(body, ok):
    from pydantic import ValidationError
    Req = _invitation_model()
    if ok:
        r = Req(**body)
        assert not (r.github_login or "").startswith("@")
    else:
        with pytest.raises(ValidationError):
            Req(**body)


def _invitation_model():
    for route in api.app.routes:
        if getattr(route, "path", "") == "/admin/invitations" and "POST" in route.methods:
            import inspect
            return inspect.signature(route.endpoint).parameters["body"].annotation
    raise AssertionError("no /admin/invitations route")


# ── Database (real SQL) ──────────────────────────────────────────────────────

needs_docker = pytest.mark.skipif(not is_docker_running(), reason="Docker daemon is not running")


@needs_docker
def test_invitation_lifecycle(postgres_container):
    import psycopg2
    from api import database as db

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("INSERT INTO users (id, email, role) VALUES ('inv-u1', 'friend@example.com', 'user') "
                    "ON CONFLICT DO NOTHING")

    inv = db.create_invitation(created_by="admin1", github_login="@Friend", role="admin")
    assert inv["github_login"] == "friend" and inv["expires_at"] is not None

    # Pending invitation is found by login (case-insensitive), not by someone else.
    assert db.find_access_invitation("inv-u1", "FRIEND", None)["id"] == inv["id"]
    assert db.find_access_invitation("other", "stranger", None) is None

    assert db.accept_invitation(inv["id"], "inv-u1") == "admin"
    # After acceptance it is found through accepted_by, even with no login given.
    assert db.find_access_invitation("inv-u1", None, None)["accepted_by"] == "inv-u1"

    revoked = db.revoke_invitation(str(inv["id"]))
    assert revoked["accepted_by"] == "inv-u1"
    assert db.find_access_invitation("inv-u1", "friend", None) is None
    with conn.cursor() as cur:
        cur.execute("SELECT role, admin_source FROM users WHERE id = 'inv-u1'")
        assert cur.fetchone() == ("user", None)  # the invited admin role went with it

    # Expired pending invitations don't count; email invitations match by email.
    with conn.cursor() as cur:
        cur.execute("INSERT INTO user_invitations (email, created_by, expires_at) "
                    "VALUES ('late@example.com', 'admin1', NOW() - INTERVAL '1 day')")
    assert db.find_access_invitation("late", None, "late@example.com") is None
    mail = db.create_invitation(created_by="admin1", email="Mail@Example.com", expires_in_days=None)
    assert mail["expires_at"] is None
    assert db.find_access_invitation("m1", None, "mail@example.com")["id"] == mail["id"]
    conn.close()
