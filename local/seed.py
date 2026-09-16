#!/usr/bin/env python3
"""
ShipZen local-dev seed script
==============================
Populates PostgreSQL with a ready-to-use demo dataset so you can test every
API endpoint immediately after `docker compose up`.

Usage (from repo root, with the local stack running):
    python local/seed.py

What it creates
---------------
* 1 admin user      (id: local-dev-user)
* 1 regular user    (id: local-dev-user-2)
* 2 projects        (one Ready, one Provisioning)
* project membership for user-2 on project-1 as viewer
* 2 deployments     (Running + Failed) on project-1
* 1 build record    for the Running deployment

After seeding, try:
    curl -s -H "Authorization: Bearer stub-token" http://localhost:8000/projects | python -m json.tool
"""

import os
import sys
import json
import uuid
import datetime
import psycopg2
from psycopg2.extras import DictCursor

# ---------------------------------------------------------------------------
# Connection — use DATABASE_URL if set, otherwise the docker-compose default
# ---------------------------------------------------------------------------
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://shipzen:shipzen-local@localhost:5432/shipzen",
)

DEMO_PROJECT_1_ID = "00000000-0000-0000-0000-000000000001"
DEMO_PROJECT_2_ID = "00000000-0000-0000-0000-000000000002"
DEMO_DEPLOY_RUN   = "aaaa0000-0000-0000-0000-000000000001"
DEMO_DEPLOY_FAIL  = "aaaa0000-0000-0000-0000-000000000002"
DEMO_BUILD_ID     = "bbbb0000-0000-0000-0000-000000000001"

NOW = datetime.datetime.utcnow().isoformat()


def seed():
    try:
        conn = psycopg2.connect(DATABASE_URL)
    except psycopg2.OperationalError as e:
        print(f"ERROR: Cannot connect to database.\n  {e}")
        print("\nMake sure the local stack is running:")
        print("  docker compose -f docker-compose.local.yml up -d postgres")
        sys.exit(1)

    conn.autocommit = False
    cur = conn.cursor(cursor_factory=DictCursor)

    try:
        print("Seeding users …")
        cur.execute("""
            INSERT INTO users (id, email, role) VALUES
                ('local-dev-user',   'admin@shipzen.local',   'admin'),
                ('local-dev-user-2', 'viewer@shipzen.local',  'user')
            ON CONFLICT (id) DO UPDATE SET email = EXCLUDED.email, role = EXCLUDED.role;
        """)

        print("Seeding projects …")
        cur.execute("""
            INSERT INTO projects (id, owner_id, name, namespace, status, webhook_secret)
            VALUES
                (%s, 'local-dev-user', 'Demo App',     'demo-app',     'Ready',        'dev-webhook-secret-1'),
                (%s, 'local-dev-user', 'Staging Env',  'staging-env',  'Provisioning', 'dev-webhook-secret-2')
            ON CONFLICT (id) DO NOTHING;
        """, (DEMO_PROJECT_1_ID, DEMO_PROJECT_2_ID))

        print("Seeding project members …")
        # owner record for both projects
        cur.execute("""
            INSERT INTO project_members (project_id, user_id, role) VALUES
                (%s, 'local-dev-user',   'owner'),
                (%s, 'local-dev-user',   'owner'),
                (%s, 'local-dev-user-2', 'viewer')
            ON CONFLICT DO NOTHING;
        """, (DEMO_PROJECT_1_ID, DEMO_PROJECT_2_ID, DEMO_PROJECT_1_ID))

        print("Seeding deployments …")
        cur.execute("""
            INSERT INTO deployments
                (deployment_id, project_id, repo_url, image_uri, replicas, port, state, health_check_path)
            VALUES
                (%s, %s, 'https://github.com/example/demo-app.git',
                 'localhost:5001/shipzen-builds/demo-app:latest',
                 1, 3000, 'Running',  '/health'),
                (%s, %s, 'https://github.com/example/demo-app.git',
                 NULL,
                 1, 3000, 'Failed', '/')
            ON CONFLICT (deployment_id) DO NOTHING;
        """, (DEMO_DEPLOY_RUN, DEMO_PROJECT_1_ID, DEMO_DEPLOY_FAIL, DEMO_PROJECT_1_ID))

        print("Seeding build record …")
        cur.execute("""
            INSERT INTO builds (build_id, deployment_id, s3_log_uri, status, started_at, completed_at)
            VALUES (%s, %s, 's3://shipzen-logs/logs/%s/build.log', 'Success', NOW() - INTERVAL '5 minutes', NOW() - INTERVAL '2 minutes')
            ON CONFLICT (build_id) DO NOTHING;
        """, (DEMO_BUILD_ID, DEMO_DEPLOY_RUN, DEMO_DEPLOY_RUN))

        print("Seeding audit log entries …")
        cur.execute("""
            INSERT INTO audit_logs (project_id, user_id, action, resource_type, resource_id, details)
            VALUES
                (%s, 'local-dev-user', 'CREATE', 'project',    %s, '{"name": "Demo App"}'),
                (%s, 'local-dev-user', 'DEPLOY', 'deployment', %s, '{"repo_url": "https://github.com/example/demo-app.git"}')
        """, (
            DEMO_PROJECT_1_ID, DEMO_PROJECT_1_ID,
            DEMO_PROJECT_1_ID, DEMO_DEPLOY_RUN,
        ))

        conn.commit()
        print("\n✓ Seed data loaded successfully.\n")
        print("Quick test commands:")
        print('  curl -s -H "Authorization: Bearer stub-token" http://localhost:8000/projects | python -m json.tool')
        print(f'  curl -s -H "Authorization: Bearer stub-token" http://localhost:8000/projects/{DEMO_PROJECT_1_ID} | python -m json.tool')
        print(f'  curl -s -H "Authorization: Bearer stub-token" http://localhost:8000/projects/{DEMO_PROJECT_1_ID}/deployments | python -m json.tool')
        print(f'  curl -s -H "Authorization: Bearer stub-token" "http://localhost:8000/projects/{DEMO_PROJECT_1_ID}/env" | python -m json.tool')

    except Exception as e:
        conn.rollback()
        print(f"ERROR during seed: {e}")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    seed()
