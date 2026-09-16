import os
import psycopg2
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://shipzen:shipzen@localhost:5432/shipzen")

def migrate():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        with conn.cursor() as cur:
            cur.execute("""
                ALTER TABLE projects
                ADD COLUMN IF NOT EXISTS repo_url TEXT,
                ADD COLUMN IF NOT EXISTS branch VARCHAR(255) DEFAULT 'main';
            """)
        conn.commit()
        logger.info("Successfully added repo_url and branch columns to projects table.")
    except Exception as e:
        logger.error(f"Migration failed: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    migrate()
