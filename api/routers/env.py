"""Environment variables and secrets.

/env and /secrets are two views of the same thing: one Secret Manager secret
per project (secret_store.py), synced into the project's pods. /env lists key
names; /secrets lists keys with masked values. Values are never returned.
Every change is written to the audit log.
"""
import datetime
import functools
import inspect
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator

from audit import log_audit_event
from auth import User, get_current_user
from database import get_connection, verify_project_access, verify_project_write_access
from platform_clients import apps_v1
from ratelimit import limiter
from secret_store import env_write_lock, is_not_found, load_env, save_env
from validation import _ENV_KEY_RE, _ENV_VALUE_MAX

logger = logging.getLogger('api')
router = APIRouter()


class PutEnvVarRequest(BaseModel):
    key: str
    value: str

    @field_validator('key')
    @classmethod
    def validate_key(cls, v: str) -> str:
        if not _ENV_KEY_RE.match(v):
            raise ValueError(
                "key must be a valid env var name: uppercase letters, digits, and underscores only, "
                "starting with a letter or underscore, max 255 characters"
            )
        return v

    @field_validator('value')
    @classmethod
    def validate_value(cls, v: str) -> str:
        if len(v.encode('utf-8')) > _ENV_VALUE_MAX:
            raise ValueError("value must not exceed 32 KB")
        return v


# Same shape and rules; kept as a name for the /secrets endpoints.
PutSecretRequest = PutEnvVarRequest


def _serialized(endpoint):
    """Run a write endpoint under the project's env lock (M2).

    Each write reads the project's whole KEY: value object, changes one key and
    stores a new version. Two at once used to lose one of the changes.
    """
    sig = inspect.signature(endpoint)

    @functools.wraps(endpoint)
    def wrapper(*args, **kwargs):
        project = sig.bind_partial(*args, **kwargs).arguments["project"]
        with env_write_lock(project["id"]):
            return endpoint(*args, **kwargs)
    return wrapper


def _audit(project_id: str, user: User, action: str, key: str):
    log_audit_event(project_id=project_id, user_id=user.user_id, action=action,
                    resource_type="project", resource_id=project_id, details={"key": key})


# ── /env ─────────────────────────────────────────────────────────────────────

@router.get("/projects/{project_id}/env", tags=["Environment"])
@limiter.limit("100/minute")
def get_env_vars(request: Request, project_id: str, project: dict = Depends(verify_project_access)):
    # Only the keys, never the values.
    try:
        return {"keys": list(load_env(project['id']).keys())}
    except Exception as e:
        if is_not_found(e):
            return {"keys": []}
        logger.error(f"Failed to fetch env vars for {project_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch env vars")


@router.put("/projects/{project_id}/env", tags=["Environment"])
@limiter.limit("20/minute")
@_serialized
def put_env_var(request: Request, project_id: str, body: PutEnvVarRequest, project: dict = Depends(verify_project_write_access), current_user: User = Depends(get_current_user)):
    """Add or update an environment variable for a project."""
    try:
        try:
            values = load_env(project['id'])
        except Exception as e:
            if not is_not_found(e):
                raise
            values = {}
        values[body.key] = body.value
        save_env(project['id'], values)
        _audit(project_id, current_user, "UPDATE_ENV", body.key)
        return {"message": "Updated successfully"}
    except Exception as e:
        logger.error(f"Failed to update env var for {project_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to update env var")


@router.delete("/projects/{project_id}/env/{key}", tags=["Environment"])
@limiter.limit("20/minute")
@_serialized
def delete_env_var(request: Request, project_id: str, key: str, project: dict = Depends(verify_project_write_access), current_user: User = Depends(get_current_user)):
    try:
        values = load_env(project['id'])
        if key in values:
            del values[key]
            save_env(project['id'], values)
            _audit(project_id, current_user, "DELETE_ENV", key)
        return {"message": "Deleted successfully"}
    except Exception as e:
        if is_not_found(e):
            return {"message": "Deleted successfully"}
        logger.error(f"Failed to delete env var for {project_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete env var")


# ── /secrets ─────────────────────────────────────────────────────────────────

@router.get("/projects/{project_id}/secrets", tags=["Secrets"])
@limiter.limit("50/minute")
def list_secrets(request: Request, project_id: str, project: dict = Depends(verify_project_access)):
    """List all secret keys for a project (values are redacted)."""
    try:
        return {"secrets": [{"key": k, "value": "********"} for k in load_env(project['id']).keys()]}
    except Exception as e:
        if is_not_found(e):
            return {"secrets": []}
        logger.error(f"Failed to list secrets: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve secrets")


@router.post("/projects/{project_id}/secrets", status_code=200, tags=["Secrets"])
@limiter.limit("20/minute")
@_serialized
def put_secret(request: Request, project_id: str, body: PutSecretRequest, project: dict = Depends(verify_project_write_access), current_user: User = Depends(get_current_user)):
    """Add or update a secret for a project."""
    try:
        values = load_env(project['id'])
    except Exception as e:
        if not is_not_found(e):
            logger.error(f"Failed to fetch secrets for update: {e}")
            raise HTTPException(status_code=500, detail="Failed to update secrets")
        values = {}

    values[body.key] = body.value
    try:
        save_env(project['id'], values)
    except Exception as e:
        logger.error(f"Failed to save secret: {e}")
        raise HTTPException(status_code=500, detail="Failed to save secret")
    _audit(project_id, current_user, "UPDATE_SECRET", body.key)
    return {"message": "Secret updated successfully", "key": body.key}


@router.delete("/projects/{project_id}/secrets/{key}", status_code=200, tags=["Secrets"])
@limiter.limit("20/minute")
@_serialized
def delete_secret(request: Request, project_id: str, key: str, project: dict = Depends(verify_project_write_access), current_user: User = Depends(get_current_user)):
    """Delete a secret key from a project."""
    try:
        values = load_env(project['id'])
        if key in values:
            del values[key]
            save_env(project['id'], values)
            _audit(project_id, current_user, "DELETE_SECRET", key)
        return {"message": "Secret deleted successfully"}
    except Exception as e:
        if is_not_found(e):
            raise HTTPException(status_code=404, detail="Secret not found")
        logger.error(f"Failed to delete secret: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete secret")


# ── Apply env changes to the running app ─────────────────────────────────────

@router.post("/projects/{project_id}/env/apply", tags=["Environment"])
@limiter.limit("5/minute")
def apply_env(request: Request, project_id: str, project: dict = Depends(verify_project_write_access),
              current_user: User = Depends(get_current_user)):
    """Make the live release pick up env/secret changes now.

    Env vars reach pods through an ExternalSecret that refreshes hourly and is
    read when a pod starts, so: force a refresh, then restart the pods.
    """
    from kubernetes import client as k8s
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT deployment_id FROM deployments WHERE project_id = %s AND kind = 'production' AND state = 'Running' "
                "AND replicas > 0 ORDER BY (deployment_id = %s) DESC, created_at DESC LIMIT 1;",
                (project_id, project.get("live_deployment_id") or ""))
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=409, detail="Nothing is running yet; changes apply to the next deploy.")
    dep = row[0]
    ns = project["namespace"]
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        k8s.CustomObjectsApi().patch_namespaced_custom_object(
            group="external-secrets.io", version="v1beta1", namespace=ns, plural="externalsecrets",
            name=f"{dep}-secrets", body={"metadata": {"annotations": {"force-sync": now}}})
        time.sleep(3)  # let ESO rewrite the Kubernetes Secret before pods restart
        apps_v1.patch_namespaced_deployment(
            name=dep, namespace=ns,
            body={"spec": {"template": {"metadata": {"annotations": {"kubectl.kubernetes.io/restartedAt": now}}}}})
    except Exception as e:
        logger.error(f"Failed to apply env for {project_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to apply the changes; try again or redeploy.")
    log_audit_event(project_id=project_id, user_id=current_user.user_id, action="APPLY_ENV",
                    resource_type="deployment", resource_id=dep, details={})
    return {"message": "Restarting with the new values", "deployment_id": dep}
