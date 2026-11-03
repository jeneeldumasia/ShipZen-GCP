"""Apply the numbered SQL migrations in api/migrations/, each exactly once.

    python migrate.py            # uses DATABASE_URL

The API also runs this at startup (database.init_db). Files are named
NNNN_description.sql and applied in order inside their own transaction; the
applied versions are recorded in schema_migrations. A Postgres advisory lock
makes concurrent runs (several API replicas starting at once) take turns.

To change the schema, add a new file with the next number. Never edit a
migration that has already been applied somewhere.
"""
import logging
import os
import re
import sys

import psycopg2

logger = logging.getLogger("migrate")

MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migrations")
_FILE_RE = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")
_LOCK_KEY = 74_260_001  # arbitrary, constant: "shipzen migrations"


def migration_files():
    """(version, path) for every migration file, in order."""
    names = sorted(n for n in os.listdir(MIGRATIONS_DIR) if _FILE_RE.match(n))
    return [(n[:-4], os.path.join(MIGRATIONS_DIR, n)) for n in names]


def apply_migrations(dsn: str = None) -> list:
    """Apply pending migrations; return the versions applied this time."""
    dsn = dsn or os.environ["DATABASE_URL"]
    conn = psycopg2.connect(dsn)
    applied = []
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_lock(%s);", (_LOCK_KEY,))
            try:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        version    TEXT PRIMARY KEY,
                        applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );""")
                conn.commit()
                cur.execute("SELECT version FROM schema_migrations;")
                done = {row[0] for row in cur.fetchall()}
                for version, path in migration_files():
                    if version in done:
                        continue
                    with open(path, encoding="utf-8") as f:
                        sql = f.read()
                    try:
                        cur.execute(sql)
                        cur.execute("INSERT INTO schema_migrations (version) VALUES (%s);", (version,))
                        conn.commit()
                    except Exception:
                        conn.rollback()
                        logger.error(f"Migration {version} failed; nothing from it was applied")
                        raise
                    logger.info(f"Applied migration {version}")
                    applied.append(version)
            finally:
                conn.rollback()
                cur.execute("SELECT pg_advisory_unlock(%s);", (_LOCK_KEY,))
                conn.commit()
    finally:
        conn.close()
    return applied


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    done = apply_migrations()
    print(f"Applied {len(done)} migration(s): {', '.join(done) or 'none pending'}")
    sys.exit(0)
