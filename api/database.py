import threading
from typing import Optional
from auth import get_current_user, User
from fastapi import Depends, HTTPException
from psycopg2.pool import ThreadedConnectionPool
import os
import psycopg2
from psycopg2.extras import DictCursor
import logging

logger = logging.getLogger(__name__)

# Fix #20: raise immediately on missing env var rather than silently falling
# back to postgres:postgres which will never connect inside the cluster.
DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set")


db_pool = None
_db_pool_lock = threading.Lock()

# psycopg2's ThreadedConnectionPool raises PoolError the moment it runs out of
# connections instead of waiting. Under any DB slowness that turned queued
# requests into instant 500s. A semaphore in front of the pool makes callers
# wait (bounded) for a free connection, and fail with a clear 503 if they can't.
DB_POOL_MAX = int(os.environ.get("DB_POOL_MAX", "5"))
DB_POOL_WAIT_SECONDS = float(os.environ.get("DB_POOL_WAIT_SECONDS", "10"))
_pool_slots = threading.BoundedSemaphore(DB_POOL_MAX)


class PooledConnectionWrapper:
    def __init__(self, conn, pool):
        self._conn = conn
        self._pool = pool

    def __enter__(self):
        self._conn.__enter__()
        return self._conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            self._conn.__exit__(exc_type, exc_val, exc_tb)
        finally:
            self._release()

    def _release(self):
        if self._conn is not None:
            self._pool.putconn(self._conn)
            self._conn = None  # Prevent double put
            _pool_slots.release()

    def cursor(self, *args, **kwargs):
        return self._conn.cursor(*args, **kwargs)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._release()


def get_connection():
    global db_pool
    if db_pool is None:                     # fast path — no lock once initialised
        with _db_pool_lock:
            if db_pool is None:             # double-checked locking
                # Read the URL now, not only at import: a module imported before the
                # database was known (tests, tooling) still connects to the right one.
                db_pool = ThreadedConnectionPool(1, DB_POOL_MAX, dsn=os.environ.get("DATABASE_URL") or DATABASE_URL)
    if not _pool_slots.acquire(timeout=DB_POOL_WAIT_SECONDS):
        raise HTTPException(status_code=503, detail="Database busy, please retry",
                            headers={"Retry-After": "2"})
    try:
        conn = db_pool.getconn()
    except Exception:
        _pool_slots.release()
        raise
    return PooledConnectionWrapper(conn, db_pool)


get_db_connection = get_connection



def get_or_create_user(user_id: str, email: str = None, login: str = None) -> dict:
    """Gets a user by ID, or creates them.

    Admins are named explicitly via ADMIN_GITHUB_USERS (GitHub logins) or
    ADMIN_EMAILS. Previously the first account ever created became admin, so on
    a fresh database whoever signed in first owned the platform.
    """
    admin_emails_env = os.getenv("ADMIN_EMAILS", "")
    ADMIN_EMAILS = {e.strip().lower() for e in admin_emails_env.split(",")} if admin_emails_env else set()
    ADMIN_LOGINS = {u.strip().lower() for u in os.getenv("ADMIN_GITHUB_USERS", "").split(",") if u.strip()}
    is_named_admin = bool((login and login.lower() in ADMIN_LOGINS) or (email and email.lower() in ADMIN_EMAILS))

    with get_connection() as conn:
        try:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute("SELECT id, role, email, admin_source, suspended_at IS NOT NULL AS suspended "
                            "FROM users WHERE id = %s", (user_id,))
                user = cur.fetchone()

                if user:
                    user_dict = dict(user)
                    if user_dict['role'] != 'admin' and is_named_admin:
                        cur.execute("UPDATE users SET role = 'admin', admin_source = 'env' WHERE id = %s", (user_id,))
                        user_dict['role'] = 'admin'
                        conn.commit()
                    elif user_dict['role'] == 'admin' and not is_named_admin \
                            and user_dict.get('admin_source') == 'env':
                        # Removed from the admin lists: the role they got from
                        # them goes too (M4). Admins made by another admin stay.
                        cur.execute("UPDATE users SET role = 'user', admin_source = NULL WHERE id = %s", (user_id,))
                        user_dict['role'] = 'user'
                        conn.commit()
                        logger.warning(f"Removed admin role from {user_id}: no longer in ADMIN_GITHUB_USERS / ADMIN_EMAILS")
                    user_dict.pop('admin_source', None)
                    return user_dict

                role = 'admin' if is_named_admin else 'user'

                cur.execute(
                    "INSERT INTO users (id, email, role, admin_source) VALUES (%s, %s, %s, %s) "
                    "RETURNING id, role, FALSE AS suspended",
                    (user_id, email, role, 'env' if is_named_admin else None)
                )
                new_user = cur.fetchone()
            conn.commit()
            return dict(new_user)
        except psycopg2.errors.UniqueViolation:
            conn.rollback()
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute(
                    "SELECT id, role, suspended_at IS NOT NULL AS suspended FROM users WHERE id = %s", (user_id,))
                return dict(cur.fetchone())
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to get_or_create_user: {e}")
            raise


def enforce_retention_policy():
    """
    Retention Policy: delete failed builds older than 30 days,
    successful builds older than 90 days.

    Fix #3.5: was mixing manual conn.commit() with the psycopg2 context
    manager, leaving no rollback path on failure. Now uses an explicit
    transaction block with proper commit/rollback.
    """
    logger.info("Running retention policy cleanup...")
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM builds
                WHERE (status = 'Failed'  AND completed_at < NOW() - INTERVAL '30 days')
                   OR (status = 'Success' AND completed_at < NOW() - INTERVAL '90 days');
            """)
            deleted = cur.rowcount
        conn.commit()
        logger.info(f"Retention policy applied. Deleted {deleted} old builds.")
    except Exception as e:
        conn.rollback()
        logger.error(f"Retention policy failed, rolled back: {e}")
        raise
    finally:
        conn.close()


def init_db():
    """Bring the schema up to date (api/migrations/, see migrate.py).

    Raises if a migration fails, so the API doesn't start against a schema its
    code doesn't match; the pod restarts and the error is in its log.
    """
    from migrate import apply_migrations
    applied = apply_migrations(os.environ.get("DATABASE_URL") or DATABASE_URL)
    logger.info(f"Database schema up to date ({len(applied)} migration(s) applied now).")


WRITE_ROLES = ("owner", "editor")


def verify_project_write_access(
    project_id: str,
    current_user: User = Depends(get_current_user)
) -> dict:
    """Like verify_project_access, but viewers are rejected (403).

    Use on every endpoint that changes state: deploys, rollbacks, cancels,
    restarts, env vars and secrets.
    """
    return _check_project_access(project_id, current_user, required_roles=WRITE_ROLES)


def verify_project_access(
    project_id: str,
    current_user: User = Depends(get_current_user)
) -> dict:
    return _check_project_access(project_id, current_user)


def _check_project_access(project_id: str, current_user: User, required_roles: tuple = None) -> dict:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            if current_user.role == 'admin':
                cur.execute(
                    "SELECT * FROM projects WHERE id = %s AND deleted_at IS NULL", (project_id,))
                project = cur.fetchone()
                if not project:
                    raise HTTPException(
                        status_code=404, detail="Project not found")
                return dict(project)
            else:
                cur.execute("""
                    SELECT p.*, pm.role AS member_role FROM projects p
                    JOIN project_members pm ON pm.project_id = p.id
                    WHERE p.id = %s AND pm.user_id = %s AND p.deleted_at IS NULL;
                """, (project_id, current_user.user_id))
                project = cur.fetchone()
                if not project:
                    raise HTTPException(
                        status_code=403, detail="You do not have access to this project")
                project = dict(project)
                member_role = project.pop("member_role")
                if required_roles and member_role not in required_roles:
                    raise HTTPException(
                        status_code=403,
                        detail=f"Your role on this project ('{member_role}') is read-only")
                return project


def assert_project_owner(project_id: str, current_user: User, detail: str) -> None:
    """Raise 403 with `detail` unless the user owns the project (admins always pass).

    For actions only an owner may take (deleting the project, managing its
    members), on top of verify_project_access.
    """
    if current_user.is_admin:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT role FROM project_members WHERE project_id = %s AND user_id = %s;",
                        (project_id, current_user.user_id))
            member = cur.fetchone()
    if not member or member[0] != 'owner':
        raise HTTPException(status_code=403, detail=detail)


# ── Invitations ───────────────────────────────────────────────────────────────
# An admin invites a GitHub login or a verified email. The first sign-in that
# matches accepts it; after that the invitation is the user's standing access,
# until an admin revokes it. See migrations/0016_user_invitations.sql.

_INVITATION_COLUMNS = ("id, github_login, email, role, created_by, created_at, "
                       "expires_at, accepted_at, accepted_by")


def create_invitation(created_by: str, github_login: Optional[str] = None,
                      email: Optional[str] = None, role: str = 'user',
                      expires_in_days: Optional[int] = 14) -> dict:
    """Create an invitation for a GitHub login or an email address."""
    login = github_login.strip().lstrip("@").lower() if github_login and github_login.strip() else None
    mail = email.strip().lower() if email and email.strip() else None
    if not login and not mail:
        raise HTTPException(status_code=400, detail="Give a GitHub login or an email address")
    with get_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute(
                f"INSERT INTO user_invitations (github_login, email, role, created_by, expires_at) "
                f"VALUES (%s, %s, %s, %s, CASE WHEN %s::int IS NULL THEN NULL "
                f"ELSE NOW() + make_interval(days => %s::int) END) "
                f"RETURNING {_INVITATION_COLUMNS};",
                (login, mail, role, created_by, expires_in_days, expires_in_days))
            inv = cur.fetchone()
        conn.commit()
    return dict(inv)


def list_invitations() -> list:
    """The 200 most recent invitations, pending and accepted."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute(f"SELECT {_INVITATION_COLUMNS} FROM user_invitations "
                        f"ORDER BY created_at DESC LIMIT 200;")
            return [dict(r) for r in cur.fetchall()]


def find_access_invitation(user_id: str, login: Optional[str], email: Optional[str]) -> Optional[dict]:
    """The invitation that lets this user in, if any.

    Either one they already accepted, or a pending, unexpired one for their
    GitHub login or verified email. Errors propagate: the caller refuses the
    sign-in rather than guessing.
    """
    login = login.lower() if login else None
    email = email.lower() if email else None
    with get_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute(
                f"SELECT {_INVITATION_COLUMNS} FROM user_invitations "
                f"WHERE accepted_by = %s "
                f"   OR (accepted_at IS NULL AND (expires_at IS NULL OR expires_at > NOW()) "
                f"       AND ((%s::text IS NOT NULL AND LOWER(github_login) = %s) "
                f"         OR (%s::text IS NOT NULL AND LOWER(email) = %s))) "
                f"ORDER BY (accepted_by = %s) DESC NULLS LAST, created_at DESC LIMIT 1;",
                (user_id, login, login, email, email, user_id))
            row = cur.fetchone()
    return dict(row) if row else None


def accept_invitation(invitation_id, user_id: str) -> Optional[str]:
    """Mark a pending invitation accepted by user_id. Returns the user's role.

    An admin invitation makes the user an admin (admin_source 'invite', so
    revoking the invitation takes the role away again).
    """
    with get_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute(
                "UPDATE user_invitations SET accepted_at = NOW(), accepted_by = %s "
                "WHERE id = %s AND accepted_at IS NULL RETURNING role;",
                (user_id, str(invitation_id)))
            row = cur.fetchone()
            if row and row["role"] == "admin":
                cur.execute("UPDATE users SET role = 'admin', admin_source = 'invite' "
                            "WHERE id = %s AND role <> 'admin';", (user_id,))
            cur.execute("SELECT role FROM users WHERE id = %s;", (user_id,))
            user = cur.fetchone()
        conn.commit()
    return user["role"] if user else None


def revoke_invitation(invitation_id: str) -> Optional[dict]:
    """Delete an invitation. Returns it (None if there was none).

    If it had been accepted, the user loses access, and an admin role that came
    from the invitation goes with it.
    """
    with get_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute(f"DELETE FROM user_invitations WHERE id = %s RETURNING {_INVITATION_COLUMNS};",
                        (invitation_id,))
            inv = cur.fetchone()
            if inv and inv["accepted_by"]:
                cur.execute("UPDATE users SET role = 'user', admin_source = NULL "
                            "WHERE id = %s AND admin_source = 'invite';", (inv["accepted_by"],))
        conn.commit()
    return dict(inv) if inv else None
