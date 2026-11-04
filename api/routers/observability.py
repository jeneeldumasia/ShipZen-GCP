"""Runtime logs and metrics of a project's apps, for the app page.

Logs come from Loki, metrics from Prometheus (observability_client.py); both
are scoped to the project's namespace server-side. Log lines are redacted.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from auth import User, get_current_user
from database import verify_project_access
from helpers import _get_deployment_or_404
from observability_client import ObservabilityError, project_metrics, runtime_logs
from ratelimit import limiter
from shipzen_common.redact import redact

logger = logging.getLogger('api')
router = APIRouter()


@router.get("/projects/{project_id}/deployments/{deployment_id}/runtime-logs", tags=["Observability"])
@limiter.limit("60/minute")
def get_runtime_logs(request: Request, project_id: str, deployment_id: str,
                     since: Optional[int] = Query(None, ge=0, description="Only lines after this timestamp (ns)"),
                     limit: int = Query(500, ge=1, le=1000),
                     q: Optional[str] = Query(None, max_length=200, description="Only lines containing this text"),
                     project: dict = Depends(verify_project_access),
                     current_user: User = Depends(get_current_user)):
    """What the app printed (stdout/stderr), newest `limit` lines, oldest first."""
    _get_deployment_or_404(project_id, deployment_id)
    try:
        lines = runtime_logs(project["namespace"], deployment_id, since_ns=since, limit=limit, search=q or None)
    except ObservabilityError as e:
        logger.warning(f"runtime logs for {deployment_id}: {e}")
        raise HTTPException(status_code=503, detail="Logs are temporarily unavailable.")
    except ValueError:
        raise HTTPException(status_code=404, detail="No logs for this deployment.")
    for entry in lines:
        entry["line"] = redact(entry["line"])
    return {"lines": lines, "last": lines[-1]["ts"] if lines else since}


@router.get("/projects/{project_id}/metrics", tags=["Observability"])
@limiter.limit("30/minute")
def get_metrics(request: Request, project_id: str,
                range: str = Query("1h", pattern="^(1h|6h|24h)$"),
                project: dict = Depends(verify_project_access),
                current_user: User = Depends(get_current_user)):
    """CPU, memory, instances, restarts, requests, errors and p95 latency over time."""
    try:
        return project_metrics(project["namespace"], range)
    except ObservabilityError as e:
        logger.warning(f"metrics for {project_id}: {e}")
        raise HTTPException(status_code=503, detail="Metrics are temporarily unavailable.")
    except ValueError:
        raise HTTPException(status_code=404, detail="No metrics for this project.")
