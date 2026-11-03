"""The signed-in user, and platform admin endpoints."""
import datetime
import logging
from typing import Optional

from psycopg2.extras import DictCursor
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from kubernetes import client as k8s_client

from audit import log_audit_event
from auth import User, evict_user_token_cache, get_current_user
from database import get_connection
from helpers import _serialize
from platform_clients import _redis_client, apps_v1, get_redis
from ratelimit import limiter

logger = logging.getLogger('api')
router = APIRouter()


# ── Users & Admin ─────────────────────────────────────────────────────────────


@router.get("/users/me", tags=["Users"])
@limiter.limit("100/minute")
def get_me(request: Request, current_user: User = Depends(get_current_user)):
    """Get the currently logged-in user's profile and role."""
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute("SELECT id, email, role FROM users WHERE id = %s;", (current_user.user_id,))
                row = cur.fetchone()
    except Exception as e:
        logger.error(f"Failed to fetch user profile: {e}")
        raise HTTPException(status_code=500, detail="Database error")
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user_id": row["id"], "email": row["email"], "role": row["role"], "is_admin": current_user.is_admin}


class UpdateRoleRequest(BaseModel):
    role: str


@router.get("/admin/users", tags=["Admin"])
@limiter.limit("100/minute")
def list_users(request: Request, current_user: User = Depends(get_current_user)):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute(
                    "SELECT id, email, role, created_at FROM users ORDER BY created_at DESC;")
                return [_serialize(dict(r)) for r in cur.fetchall()]
    except Exception as e:
        logger.error(f"Failed to list users: {e}")
        raise HTTPException(status_code=500, detail="Database error")


@router.put("/admin/users/{user_id}/role", tags=["Admin"])
@limiter.limit("50/minute")
def update_user_role(request: Request, user_id: str, body: UpdateRoleRequest, current_user: User = Depends(get_current_user)):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Forbidden")
    if body.role not in ["admin", "user"]:
        raise HTTPException(
            status_code=400, detail="Invalid role. Must be 'admin' or 'user'.")

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE users SET role = %s WHERE id = %s RETURNING id;", (body.role, user_id))
                if not cur.fetchone():
                    raise HTTPException(
                        status_code=404, detail="User not found")
            conn.commit()
            
        # Instantly evict the demoted/promoted user's tokens to prevent stale access
        evict_user_token_cache(user_id)
        try:
            _redis_client.publish("shipzen:events:cache_evict", user_id)
        except Exception as e:
            logger.warning(f"Failed to publish cache_evict event: {e}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update user role: {e}")
        raise HTTPException(status_code=500, detail="Database error")

    log_audit_event(
        project_id=None,
        user_id=current_user.user_id,
        action="UPDATE_ROLE",
        resource_type="user",
        resource_id=user_id,
        details={"new_role": body.role},
    )
    return {"message": f"User {user_id} role updated to {body.role}"}


@router.get("/admin/audit-logs", tags=["Admin"])
@limiter.limit("100/minute")
def list_global_audit_logs(request: Request, limit: int = Query(50, le=200), current_user: User = Depends(get_current_user)):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute(
                    "SELECT * FROM audit_logs ORDER BY timestamp DESC LIMIT %s;",
                    (limit,)
                )
                return [_serialize(dict(r)) for r in cur.fetchall()]
    except Exception as e:
        logger.error(f"Failed to fetch global audit logs: {e}")
        raise HTTPException(status_code=500, detail="Database error")


@router.get("/admin/deployments", tags=["Admin"])
@limiter.limit("100/minute")
def list_global_deployments(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: Optional[str] = Query(default=None, description="cursor format: <updated_at>|<deployment_id>"),
    current_user: User = Depends(get_current_user)
):
    """List all deployments across the platform, with project and owner info."""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    query = """
        SELECT d.deployment_id, d.project_id, d.repo_url, d.image_uri,
               d.replicas, d.port, d.state, d.updated_at, d.last_error,
               p.name AS project_name, p.namespace AS project_namespace,
               u.email AS owner_email
        FROM deployments d
        JOIN projects p ON d.project_id = p.id
        LEFT JOIN users u ON p.owner_id = u.id
    """
    params: list = []

    if cursor:
        try:
            cursor_updated_at, cursor_deployment_id = cursor.split("|", 1)
            query += " WHERE (d.updated_at, d.deployment_id) < (%s, %s)"
            params.extend([cursor_updated_at, cursor_deployment_id])
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid cursor format")

    query += " ORDER BY d.updated_at DESC, d.deployment_id DESC LIMIT %s;"
    params.append(limit)

    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute(query, tuple(params))
                return [_serialize(dict(r)) for r in cur.fetchall()]
    except Exception as e:
        logger.error(f"Failed to list global deployments: {e}")
        raise HTTPException(status_code=500, detail="Failed to list global deployments")


@router.post("/admin/system/restart", tags=["Admin"])
@limiter.limit("2/minute")
def restart_system(request: Request, current_user: User = Depends(get_current_user)):
    """Restart ShipZen system pods (worker and api)."""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    patch = {
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {
                        "kubectl.kubernetes.io/restartedAt": now_str
                    }
                }
            }
        }
    }
    
    errors = []
    for deploy_name in ["shipzen-worker", "shipzen-api"]:
        try:
            apps_v1.patch_namespaced_deployment(
                name=deploy_name,
                namespace="shipzen-system",
                body=patch
            )
        except Exception as e:
            logger.error(f"Failed to restart {deploy_name}: {e}")
            errors.append(str(e))
            
    if errors:
        raise HTTPException(status_code=500, detail=f"Failed to restart some system pods: {', '.join(errors)}")
        
    return {"status": "restarting"}


@router.get("/admin/metrics", tags=["Admin"])
@limiter.limit("30/minute")
def admin_metrics(request: Request, current_user: User = Depends(get_current_user)):
    """Fetch real-time cluster metrics for the admin dashboard."""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
        
    metrics = {
        "nodes": {"total": 0, "active": 0, "cpu_usage_pct": 0},
        "db": {"storage_pct": 0, "text": "0% (0GB/100GB)"},
        "redis": {"hit_rate_pct": 0},
        "argocd": {"status": "Unknown"}
    }
    
    # 1. K8s Nodes CPU
    try:
        core_v1 = k8s_client.CoreV1Api()
        custom_api = k8s_client.CustomObjectsApi()
        
        nodes = core_v1.list_node().items
        metrics["nodes"]["total"] = len(nodes)
        
        try:
            node_metrics = custom_api.list_cluster_custom_object('metrics.k8s.io', 'v1beta1', 'nodes')
            total_cpu_capacity = 0
            total_cpu_usage = 0
            active = 0
            
            for node in nodes:
                alloc = node.status.allocatable.get('cpu', '1')
                capacity_m = int(alloc) * 1000 if not alloc.endswith('m') else int(alloc.replace('m', ''))
                total_cpu_capacity += capacity_m
                
                for nm in node_metrics.get('items', []):
                    if nm['metadata']['name'] == node.metadata.name:
                        usage_str = nm['usage']['cpu']
                        try:
                            usage_m = int(usage_str.replace('n', '')) / 1000000 if usage_str.endswith('n') else (int(usage_str.replace('m', '')) if usage_str.endswith('m') else int(usage_str) * 1000)
                        except ValueError:
                            usage_m = 0
                        total_cpu_usage += usage_m
                        active += 1
                        break
            
            metrics["nodes"]["active"] = active
            if total_cpu_capacity > 0:
                metrics["nodes"]["cpu_usage_pct"] = int((total_cpu_usage / total_cpu_capacity) * 100)
        except Exception as e:
            logger.warning(f"Failed to fetch node metrics (metrics server might not be running): {e}")
            metrics["nodes"]["active"] = len([n for n in nodes if any(c.type == 'Ready' and c.status == 'True' for c in n.status.conditions)])
            metrics["nodes"]["cpu_usage_pct"] = 0
    except Exception as e:
        logger.warning(f"Failed to fetch nodes: {e}")

    # 2. Database Storage
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_database_size(current_database());")
                size_bytes = cur.fetchone()[0]
                size_gb = size_bytes / (1024**3)
                metrics["db"]["storage_pct"] = int((size_gb / 100.0) * 100) if size_gb < 100 else 100
                metrics["db"]["text"] = f"{size_gb:.1f}GB / 100GB"
    except Exception as e:
        logger.warning(f"Failed to fetch DB size: {e}")

    # 3. Redis Hit Rate
    try:
        r = get_redis()
        info = r.info("stats")
        hits = int(info.get("keyspace_hits", 0))
        misses = int(info.get("keyspace_misses", 0))
        if hits + misses > 0:
            metrics["redis"]["hit_rate_pct"] = int((hits / (hits + misses)) * 100)
        else:
            metrics["redis"]["hit_rate_pct"] = 100
    except Exception as e:
        logger.warning(f"Failed to fetch Redis stats: {e}")
        
    # 4. ArgoCD Sync
    try:
        custom_api = k8s_client.CustomObjectsApi()
        apps = custom_api.list_cluster_custom_object('argoproj.io', 'v1alpha1', 'applications')
        if apps.get('items'):
            app = next((a for a in apps['items'] if a['metadata']['name'] == 'shipzen-platform'), apps['items'][0])
            status = app.get('status', {}).get('sync', {}).get('status', 'Unknown')
            metrics["argocd"]["status"] = status
        else:
            metrics["argocd"]["status"] = "Unknown"
    except Exception as e:
        # Don't report "Synced" when we couldn't actually check: a healthy-looking
        # status that's really an error hides problems from whoever reads it.
        logger.warning(f"Failed to fetch ArgoCD status: {e}")
        metrics["argocd"]["status"] = "Unknown"

    return metrics
