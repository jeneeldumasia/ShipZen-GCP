"""Projects, project members, and repository analysis."""
import json
import logging
import re
import secrets
import uuid
from typing import Literal, Optional

import psycopg2
from psycopg2.extras import DictCursor
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, field_validator

from audit import log_audit_event
from auth import User, evict_user_token_cache, get_current_user
from database import assert_project_owner, get_connection, verify_project_access, verify_project_write_access
from crypto_box import encrypt_value
from github_access import check_repo_access, download_snapshot
from helpers import _serialize
from platform_clients import _redis_client
from ratelimit import limiter
from secret_store import delete_project_secret, ensure_project_secret
from shipzen_common.hostnames import vanity_hostname, vanity_problem
from validation import (_NAMESPACE_RE, _PROJECT_NAME_RE, _REPO_URL_RE, _RESERVED_NS_EXACT, _RESERVED_NS_PREFIXES)

logger = logging.getLogger('api')
router = APIRouter()


class CreateProjectRequest(BaseModel):
    name: str
    namespace: str
    repo_url: Optional[str] = None
    branch: Optional[str] = "main"

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        # The name is rendered into GitOps YAML (labels, hostnames) by the
        # controller. Quotes, newlines or '---' would let a tenant inject extra
        # Kubernetes objects that ArgoCD then applies cluster-wide.
        if not _PROJECT_NAME_RE.match(v):
            raise ValueError(
                "name may contain letters, digits, spaces, '.', '_' and '-' "
                "(max 63 chars) and must start with a letter or digit"
            )
        return v

    @field_validator("namespace")
    @classmethod
    def validate_namespace(cls, v: str) -> str:
        if not _NAMESPACE_RE.match(v):
            raise ValueError(
                "namespace must be lowercase alphanumeric with hyphens, 3–63 chars, "
                "and cannot start or end with a hyphen"
            )
        # Reject reserved platform/infra namespaces — both exact names and prefixes.
        # This prevents users from colliding with cluster-level infrastructure
        # that is never stored in the projects table.
        if v in _RESERVED_NS_EXACT or any(v.startswith(p) for p in _RESERVED_NS_PREFIXES):
            raise ValueError(
                f"The namespace '{v}' is reserved for platform use and cannot be "
                "used for tenant projects. Please choose a different namespace."
            )
        return v


# ── Projects ──────────────────────────────────────────────────────────────────


@router.post("/projects", status_code=201, tags=["Projects"])
@limiter.limit("10/minute")
def create_project(request: Request, body: CreateProjectRequest, current_user: User = Depends(get_current_user)):
    """
    Create a new project. The controller picks up status=Provisioning
    and creates the tenant namespace + RBAC in Kubernetes.
    """
    # C3: a project may only name a GitHub repository the user can read.
    repo = check_repo_access(current_user, body.repo_url) if body.repo_url else None
    project_id = str(uuid.uuid4())
    webhook_secret = secrets.token_hex(32)
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO projects (id, owner_id, name, namespace, status, webhook_secret, repo_url, branch,
                                          github_repo_id, github_repo_full_name)
                    VALUES (%s, %s, %s, %s, 'Provisioning', %s, %s, %s, %s, %s)
                    RETURNING *;
                    """,
                    (project_id, current_user.user_id,
                     body.name, body.namespace, encrypt_value(webhook_secret),
                     body.repo_url, body.branch,
                     repo["id"] if repo else None, repo["full_name"] if repo else None),
                )
                project = dict(cur.fetchone())

                cur.execute(
                    "INSERT INTO project_members (project_id, user_id, role) VALUES (%s, %s, 'owner')",
                    (project_id, current_user.user_id)
                )

            conn.commit()
    except psycopg2.errors.UniqueViolation as e:
        if "namespace" in str(e):
            raise HTTPException(
                status_code=409, detail="A project with this namespace already exists")
        raise HTTPException(
            status_code=409, detail="A project with this ID already exists")
    except Exception as e:
        logger.error(f"Failed to create project: {e}")
        raise HTTPException(status_code=500, detail="Failed to create project")

    log_audit_event(
        project_id=project_id,
        user_id=current_user.user_id,
        action="CREATE",
        resource_type="project",
        resource_id=project_id,
        details={"name": body.name, "namespace": body.namespace},
    )

    ensure_project_secret(project_id)

    try:
        _redis_client.publish("shipzen:events:project_reconcile", json.dumps({"project_id": project_id, "event": "project_created"}))
    except Exception as pub_err:
        logger.warning(f"Failed to publish project_reconcile event: {pub_err}")

    return _serialize(project)


@router.get("/projects", tags=["Projects"])
@limiter.limit("100/minute")
def list_projects(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user)
):
    """List all non-deleted (non-Terminating) projects."""
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                if current_user.is_admin:
                    cur.execute(
                        """
                        SELECT p.*, u.email as owner_email,
                               (SELECT COUNT(*) FROM deployments d WHERE d.project_id = p.id) as deployments_count
                        FROM projects p
                        LEFT JOIN users u ON p.owner_id = u.id
                        WHERE p.deleted_at IS NULL 
                        ORDER BY p.created_at DESC
                        LIMIT %s OFFSET %s;
                        """, (limit, offset)
                    )
                else:
                    # HIGH-15 Fix: Include projects where user is a member, not just owner
                    cur.execute(
                        """
                        SELECT DISTINCT p.*, u.email as owner_email,
                               (SELECT COUNT(*) FROM deployments d WHERE d.project_id = p.id) as deployments_count
                        FROM projects p
                        LEFT JOIN users u ON p.owner_id = u.id
                        LEFT JOIN project_members pm ON p.id = pm.project_id
                        WHERE p.deleted_at IS NULL 
                          AND (p.owner_id = %s OR pm.user_id = %s)
                        ORDER BY p.created_at DESC
                        LIMIT %s OFFSET %s;
                        """,
                        (current_user.user_id, current_user.user_id, limit, offset)
                    )
                return [_serialize(dict(r)) for r in cur.fetchall()]
    except Exception as e:
        logger.error(f"Failed to list projects: {e}")
        raise HTTPException(status_code=500, detail="Failed to list projects")


@router.get("/projects/{project_id}", tags=["Projects"])
@limiter.limit("100/minute")
def get_project(request: Request, project_id: str, project: dict = Depends(verify_project_access)):
    """Get a single project by ID."""
    return _serialize(project)


class SetSubdomainRequest(BaseModel):
    # None or "" removes the vanity name.
    subdomain: Optional[str] = None


@router.put("/projects/{project_id}/subdomain", tags=["Projects"])
@limiter.limit("10/minute")
def set_project_subdomain(request: Request, project_id: str, body: SetSubdomainRequest,
                          project: dict = Depends(verify_project_write_access),
                          current_user: User = Depends(get_current_user)):
    """Give the project a free vanity hostname, <subdomain>-shipzen.jeneeldumasia.codes,
    that always points at its live release (or remove it)."""
    sub = (body.subdomain or "").strip().lower() or None
    if sub:
        problem = vanity_problem(sub)
        if problem:
            raise HTTPException(status_code=422, detail=problem)
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute("UPDATE projects SET subdomain = %s WHERE id = %s RETURNING *;", (sub, project_id))
                row = dict(cur.fetchone())
            conn.commit()
    except psycopg2.errors.UniqueViolation:
        raise HTTPException(status_code=409, detail=f"'{sub}' is already taken. Try another name.")

    log_audit_event(
        project_id=project_id,
        user_id=current_user.user_id,
        action="SET_SUBDOMAIN",
        resource_type="project",
        resource_id=project_id,
        details={"subdomain": sub},
    )
    try:
        _redis_client.publish("shipzen:events:project_reconcile",
                              json.dumps({"project_id": project_id, "event": "subdomain_changed"}))
    except Exception as pub_err:
        logger.warning(f"Failed to publish project_reconcile event: {pub_err}")

    out = _serialize(row)
    out["vanity_url"] = f"https://{vanity_hostname(sub)}" if sub else None
    return out


@router.delete("/projects/{project_id}", status_code=202, tags=["Projects"])
@limiter.limit("10/minute")
def delete_project(request: Request, project_id: str, project: dict = Depends(verify_project_access), current_user: User = Depends(get_current_user)):
    """
    Soft-delete a project — sets status to Terminating.
    The controller will delete the Kubernetes namespace and then
    hard-delete the row once the namespace is gone.
    """
    assert_project_owner(project_id, current_user, "Only project owners can delete projects")

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE projects SET status = 'Terminating', deleted_at = NOW() WHERE id = %s;",
                    (project_id,),
                )
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to delete project {project_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete project")

    log_audit_event(
        project_id=project_id,
        user_id=current_user.user_id,
        action="DELETE",
        resource_type="project",
        resource_id=project_id,
        details={},
    )

    delete_project_secret(project_id)

    try:
        _redis_client.publish("shipzen:events:project_reconcile", json.dumps({"project_id": project_id, "event": "project_deleted"}))
    except Exception as pub_err:
        logger.warning(f"Failed to publish project_reconcile event: {pub_err}")

    return {"message": f"Project {project_id} marked for termination"}


class AddMemberRequest(BaseModel):
    email: str
    role: Literal['editor', 'viewer']


@router.get("/projects/{project_id}/members", tags=["Members"])
@limiter.limit("100/minute")
def list_project_members(
    request: Request,
    project_id: str,
    project: dict = Depends(verify_project_access),
    current_user: User = Depends(get_current_user)
):
    assert_project_owner(project_id, current_user, "Only project owners can manage members")
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute("""
                    SELECT u.id as user_id, u.email, pm.role, pm.created_at 
                    FROM project_members pm
                    JOIN users u ON pm.user_id = u.id
                    WHERE pm.project_id = %s
                    ORDER BY pm.created_at ASC;
                """, (project_id,))
                return [_serialize(dict(r)) for r in cur.fetchall()]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list members: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to list project members")


@router.post("/projects/{project_id}/members", status_code=201, tags=["Members"])
@limiter.limit("20/minute")
def add_project_member(
    request: Request,
    project_id: str,
    body: AddMemberRequest,
    project: dict = Depends(verify_project_access),
    current_user: User = Depends(get_current_user)
):
    assert_project_owner(project_id, current_user, "Only project owners can manage members")
    with get_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            # Find user by email
            cur.execute(
                "SELECT id, email FROM users WHERE email = %s;", (body.email,))
            target_user = cur.fetchone()
            if not target_user:
                raise HTTPException(status_code=404, detail="User not found")

            try:
                cur.execute("""
                    INSERT INTO project_members (project_id, user_id, role) 
                    VALUES (%s, %s, %s) RETURNING role, created_at;
                """, (project_id, target_user['id'], body.role))
                new_member = cur.fetchone()
                conn.commit()
                return _serialize({
                    "user_id": target_user['id'],
                    "email": target_user['email'],
                    "role": new_member['role'],
                    "created_at": new_member['created_at']
                })
            except psycopg2.errors.UniqueViolation:
                conn.rollback()
                raise HTTPException(
                    status_code=409, detail="User is already a member of this project")


@router.delete("/projects/{project_id}/members/{target_user_id}", tags=["Members"])
@limiter.limit("20/minute")
def remove_project_member(
    request: Request,
    project_id: str,
    target_user_id: str,
    project: dict = Depends(verify_project_access),
    current_user: User = Depends(get_current_user)
):
    if target_user_id == current_user.user_id:
        raise HTTPException(
            status_code=403, detail="Cannot remove yourself from a project")

    assert_project_owner(project_id, current_user, "Only project owners can manage members")
    with get_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("SELECT role FROM project_members WHERE project_id = %s AND user_id = %s;",
                        (project_id, target_user_id))
            target_member = cur.fetchone()

            if not target_member:
                raise HTTPException(status_code=404, detail="Member not found")

            if target_member['role'] == 'owner':
                raise HTTPException(
                    status_code=403, detail="Cannot remove the project owner")

            cur.execute("DELETE FROM project_members WHERE project_id = %s AND user_id = %s;",
                        (project_id, target_user_id))
            conn.commit()

            # Instantly evict cached permissions for removed user
            evict_user_token_cache(target_user_id)
            try:
                _redis_client.publish("shipzen:events:cache_evict", target_user_id)
            except Exception as e:
                logger.warning(f"Failed to publish cache_evict event: {e}")

            return {"message": "Member removed"}


class AnalyzeRequest(BaseModel):
    repo_url: str
    branch: str = "main"

    @field_validator("repo_url")
    @classmethod
    def validate_repo_url(cls, v: str) -> str:
        if not _REPO_URL_RE.match(v):
            raise ValueError(
                "repo_url must be an https:// URL or git@host:org/repo.git SSH URL"
            )
        return v


@router.post("/projects/analyze", tags=["Projects"])
@limiter.limit("5/minute")
async def analyze_repo(request: Request, body: AnalyzeRequest, current_user: User = Depends(get_current_user)):
    """Analyze a Git repository and detect deployable services."""
    import asyncio
    import tempfile
    from analyzer import RepoAnalyzer

    # Validate branch name to prevent shell injection
    if not re.match(r'^[a-zA-Z0-9_.-]{1,100}$', body.branch):
        raise HTTPException(status_code=400, detail="Invalid branch name")

    def _clone_and_analyze():
        with tempfile.TemporaryDirectory() as tmpdir:
            # A size-capped snapshot from the GitHub API with the user's token,
            # not `git clone` of an arbitrary URL from the API pod (H3).
            download_snapshot(current_user, body.repo_url, body.branch, tmpdir)
            analyzer = RepoAnalyzer(
                repo_path=tmpdir,
                repo_name=body.repo_url.split('/')[-1].replace('.git', ''))
            return analyzer.analyze()

    try:
        services = await asyncio.to_thread(_clone_and_analyze)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to read repo for analysis: {type(e).__name__}")
        raise HTTPException(
            status_code=400, detail="Failed to read the repository")

    return {"services": [s.__dict__ for s in services]}
