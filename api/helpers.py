"""Small helpers shared by several routers."""
import json
import logging

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
