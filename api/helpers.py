"""Small helpers shared by several routers."""
import json
import logging
import os

from fastapi import HTTPException
from psycopg2.extras import DictCursor

from database import get_connection
from platform_clients import GAR_REGISTRY_URL, STREAM_NAME

logger = logging.getLogger('api')


def image_uri_for(project_id: str, deployment_id: str) -> str:
    """Where the build for a deployment is pushed: <registry>/shipzen-builds/<project>:<deployment>.

    Users never see or choose this. The deployment id as tag makes every image
    unique and traceable.
    """
    if GAR_REGISTRY_URL:
        # Base registry: hostname + GCP project ID (e.g. us-central1-docker.pkg.dev/<project>)
        base_registry = "/".join(GAR_REGISTRY_URL.split("/")[:2])
        return f"{base_registry}/shipzen-builds/{project_id}:{deployment_id}"
    # Local dev / testing fallback: no registry configured
    return f"local/shipzen-builds/{project_id}:{deployment_id}"


# Abuse limits (security finding H7). Builds run arbitrary code on the cluster
# for up to 30 minutes each, so cap how many one user can have going and how
# many a project may start per month.
MAX_ACTIVE_DEPLOYS_PER_USER = int(os.getenv("MAX_ACTIVE_DEPLOYS_PER_USER", "3"))
MAX_DEPLOYS_PER_PROJECT_PER_MONTH = int(os.getenv("MAX_DEPLOYS_PER_PROJECT_PER_MONTH", "300"))


def check_deploy_limits(project_id: str, user_id: str = None) -> None:
    """Refuse a new deploy: 423 while an admin has paused deploys, 403 when the
    project owner is suspended, 429 if the project used up this month's deploys
    or the user has too many in progress."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM platform_settings WHERE key = 'deploy_freeze';")
            row = cur.fetchone()
            freeze = row[0] if row else None
            if freeze and freeze.get("paused"):
                reason = freeze.get("reason")
                raise HTTPException(
                    status_code=423,
                    detail="Deploys are paused by a platform admin" + (f": {reason}" if reason else "."))
            cur.execute(
                "SELECT u.suspended_at IS NOT NULL FROM projects p JOIN users u ON u.id = p.owner_id "
                "WHERE p.id = %s;", (project_id,))
            row = cur.fetchone()
            if row and row[0]:
                raise HTTPException(
                    status_code=403, detail="This project's owner is suspended, so it can't deploy.")
            cur.execute(
                "SELECT count(*) FROM deployments "
                "WHERE project_id = %s AND created_at >= date_trunc('month', NOW());",
                (project_id,))
            if cur.fetchone()[0] >= MAX_DEPLOYS_PER_PROJECT_PER_MONTH:
                raise HTTPException(
                    status_code=429,
                    detail=f"This project has used its {MAX_DEPLOYS_PER_PROJECT_PER_MONTH} deploys for this month.")
            if user_id:
                cur.execute(
                    """SELECT count(*) FROM deployments d
                       JOIN project_members pm ON pm.project_id = d.project_id
                       WHERE pm.user_id = %s AND pm.role IN ('owner', 'editor')
                         AND d.state IN ('Queued', 'Building', 'Deploying', 'Verifying');""",
                    (user_id,))
                if cur.fetchone()[0] >= MAX_ACTIVE_DEPLOYS_PER_USER:
                    raise HTTPException(
                        status_code=429,
                        detail=(f"You already have {MAX_ACTIVE_DEPLOYS_PER_USER} deployments in progress "
                                "across your projects. Wait for one to finish."))


def queue_deployment(cur, payload: dict) -> None:
    """Add the deploy message to the transactional outbox, in the caller's
    transaction, so a deployment row is never committed without its queue
    message (or the reverse). background.outbox_relay moves it to Redis."""
    cur.execute(
        "INSERT INTO outbox_events (stream_name, event_type, payload) VALUES (%s, %s, %s);",
        (STREAM_NAME, "deploy", json.dumps(payload))
    )


def _get_deployment_or_404(project_id: str, deployment_id: str) -> dict:
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute(
                    "SELECT * FROM deployments WHERE deployment_id = %s AND project_id = %s;",
                    (deployment_id, project_id),
                )
                row = cur.fetchone()
    except Exception as e:
        logger.error(f"DB error fetching deployment {deployment_id}: {e}")
        raise HTTPException(status_code=500, detail="Database error")

    if not row:
        raise HTTPException(
            status_code=404, detail=f"Deployment '{deployment_id}' not found")
    return dict(row)


# SEC-06 Fix: Fields to exclude from API responses
_SERIALIZE_EXCLUDE = {'webhook_secret'}

def _serialize(obj: dict) -> dict:
    """Convert non-JSON-serializable types (datetime) to strings.
    Excludes sensitive fields like webhook_secret."""
    return {
        k: v.isoformat() if hasattr(v, "isoformat") else v
        for k, v in obj.items()
        if k not in _SERIALIZE_EXCLUDE
    }
