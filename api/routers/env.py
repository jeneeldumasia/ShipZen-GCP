"""Environment variables and secrets.

/env and /secrets are two views of the same thing: one Secret Manager secret
per project (secret_store.py), synced into the project's pods. /env lists key
names; /secrets lists keys with masked values. Values are never returned.
Every change is written to the audit log.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator

from audit import log_audit_event
from auth import User, get_current_user
from database import verify_project_access, verify_project_write_access
from ratelimit import limiter
from secret_store import is_not_found, load_env, save_env
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
