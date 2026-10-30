import threading
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
                db_pool = ThreadedConnectionPool(1, DB_POOL_MAX, dsn=DATABASE_URL)
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



def get_or_create_user(user_id: str, email: str = None) -> dict:
    """Gets a user by ID, or creates them. The first user created gets the 'admin' role."""
    admin_emails_env = os.getenv("ADMIN_EMAILS", "")
    ADMIN_EMAILS = {e.strip().lower() for e in admin_emails_env.split(",")} if admin_emails_env else set()

    with get_connection() as conn:
        try:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute("SELECT id, role, email FROM users WHERE id = %s", (user_id,))
                user = cur.fetchone()
                
                check_email = email.lower() if email else None

                if user:
                    user_dict = dict(user)
                    db_email = user_dict.get('email').lower() if user_dict.get('email') else None
                    
                    if user_dict['role'] != 'admin' and ((check_email and check_email in ADMIN_EMAILS) or (db_email and db_email in ADMIN_EMAILS)):
                        cur.execute("UPDATE users SET role = 'admin' WHERE id = %s", (user_id,))
                        user_dict['role'] = 'admin'
                        conn.commit()
                    return user_dict

                cur.execute("SELECT COUNT(*) FROM users")
                count = cur.fetchone()[0]
                
                role = 'admin' if count == 0 or (check_email and check_email in ADMIN_EMAILS) else 'user'

                cur.execute(
                    "INSERT INTO users (id, email, role) VALUES (%s, %s, %s) RETURNING id, role",
                    (user_id, email, role)
                )
                new_user = cur.fetchone()
            conn.commit()
            return dict(new_user)
        except psycopg2.errors.UniqueViolation:
            conn.rollback()
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute(
                    "SELECT id, role FROM users WHERE id = %s", (user_id,))
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
    """Run schema.sql to ensure tables exist on startup."""
    try:
        schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
        with open(schema_path, "r") as f:
            schema_sql = f.read()

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(schema_sql)
            conn.commit()
            logger.info("Database schema initialized successfully.")
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to execute schema.sql: {e}")
            raise
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"Failed to read/initialize database schema: {e}")


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
