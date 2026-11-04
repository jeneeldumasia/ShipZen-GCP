"""Deployments: create, cancel, roll back, restart, status and log streams, builds."""
import asyncio
import datetime
import json
import logging
import os
import secrets
import time
import uuid
from collections import defaultdict
from typing import Optional

from psycopg2.extras import DictCursor
from fastapi import (APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
from kubernetes import client as k8s_client, config as k8s_config

from audit import log_audit_event
from auth import User, get_current_user
from database import get_connection, verify_project_access, verify_project_write_access
from github_access import check_repo_access, enforce_project_binding
from helpers import _get_deployment_or_404, _serialize, check_deploy_limits, image_uri_for, queue_deployment
from platform_clients import _aioredis_client, _gcs_client, _redis_client, apps_v1, get_redis
from ratelimit import limiter
from validation import _REPO_URL_RE

logger = logging.getLogger('api')
router = APIRouter()


class CreateDeploymentRequest(BaseModel):
    repo_url: str
    port: Optional[int] = 8080
    branch: Optional[str] = "main"

    @field_validator("repo_url")
    @classmethod
    def validate_repo_url(cls, v: str) -> str:
        if not _REPO_URL_RE.match(v):
            raise ValueError(
                "repo_url must be an https:// URL or git@host:org/repo.git SSH URL"
            )
        return v

    @field_validator("port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        if v < 1 or v > 65535:
            raise ValueError("port must be between 1 and 65535")
        return v


# ── Deployments ───────────────────────────────────────────────────────────────


@router.post("/projects/{project_id}/deployments", status_code=202, tags=["Deployments"])
@limiter.limit("5/minute")
def create_deployment(request: Request, project_id: str, body: CreateDeploymentRequest, project: dict = Depends(verify_project_write_access), current_user: User = Depends(get_current_user)):
    return _create_deployment(request, project_id, body, project, current_user)


def _create_deployment(request: Request, project_id: str, body: CreateDeploymentRequest, project: dict,
                       current_user: User, triggered_by: Optional[str] = None):
    """
    Submit a deployment request. Only a repo URL is required.
    - The platform generates the image URI automatically from GAR_REGISTRY_URL.
    - The platform controls replicas; the user does not set them.
    - Port defaults to 8080; override only if your app listens elsewhere.
    """
    if project["status"] not in ("Ready", "Provisioning"):
        raise HTTPException(
            status_code=409,
            detail=f"Project is in status '{project['status']}' and cannot accept deployments"
        )

    # CRIT-03 Fix: Reject if there's already an in-flight deployment for this project
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM deployments WHERE project_id = %s AND state IN ('Queued', 'Building', 'Deploying', 'Verifying') LIMIT 1;",
                    (project_id,)
                )
                if cur.fetchone():
                    raise HTTPException(
                        status_code=409,
                        detail="A deployment is already in progress for this project. Wait for it to complete or fail before deploying again."
                    )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to check in-flight deployments: {e}")
        raise HTTPException(status_code=500, detail="Failed to check deployment status")

    # C3: only a repository the user can read, and the one this project is bound to.
    repo = check_repo_access(current_user, body.repo_url)
    enforce_project_binding(project, repo)
    check_deploy_limits(project_id, current_user.user_id)

    deployment_id = str(uuid.uuid4())
    queued_at = str(time.time())

    image_uri = image_uri_for(project_id, deployment_id)

    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO deployments
                        (deployment_id, project_id, repo_url, image_uri, replicas, port, state,
                         branch, triggered_by)
                    VALUES (%s, %s, %s, %s, %s, %s, 'Queued', %s, %s)
                    RETURNING *;
                    """,
                    (
                        deployment_id, project_id,
                        body.repo_url, image_uri,
                        1,           # Platform controls scaling — initial replica count is 1
                        body.port,
                        body.branch, triggered_by or f"user:{current_user.user_id}",
                    ),
                )
                deployment = dict(cur.fetchone())

                trace_id = getattr(request.state, "trace_id", str(uuid.uuid4()))

                # Transactional outbox
                payload = {
                    "deployment_id": deployment_id,
                    "project_id":    project_id,
                    "repo_url":      body.repo_url,
                    "branch":        body.branch,
                    "image_name":    image_uri,
                    "queued_at":     queued_at,
                    "retries":       "0",
                    "trace_id":      trace_id,
                }
                queue_deployment(cur, payload)
                if repo and not project.get("github_repo_id"):
                    # First GitHub deployment: bind the project to this repository.
                    cur.execute(
                        "UPDATE projects SET github_repo_id = %s, github_repo_full_name = %s "
                        "WHERE id = %s AND github_repo_id IS NULL;",
                        (repo["id"], repo["full_name"], project_id))
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to create deployment: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to create deployment")

    log_audit_event(
        project_id=project_id,
        user_id=current_user.user_id,
        action="DEPLOY",
        resource_type="deployment",
        resource_id=deployment_id,
        details={"repo_url": body.repo_url, "branch": body.branch, "trace_id": trace_id},
    )

    try:
        _redis_client.publish("shipzen:events:project_reconcile", json.dumps({"project_id": project_id, "event": "deployment_created"}))
    except Exception as pub_err:
        logger.warning(f"Failed to publish project_reconcile event: {pub_err}")

    return _serialize(deployment)


@router.post("/projects/{project_id}/deployments/{deployment_id}/redeploy", status_code=202, tags=["Deployments"])
@limiter.limit("5/minute")
def redeploy(request: Request, project_id: str, deployment_id: str,
             project: dict = Depends(verify_project_write_access),
             current_user: User = Depends(get_current_user)):
    """Build and deploy the same repository, branch and port again (picks up new commits)."""
    source = _get_deployment_or_404(project_id, deployment_id)
    body = CreateDeploymentRequest(repo_url=source["repo_url"], port=source.get("port") or 8080,
                                   branch=source.get("branch") or project.get("branch") or "main")
    return _create_deployment(request, project_id, body, project, current_user,
                              triggered_by=f"redeploy:{current_user.user_id}")


@router.post("/projects/{project_id}/deployments/{deployment_id}/cancel", status_code=202, tags=["Deployments"])
@limiter.limit("5/minute")
def cancel_deployment(request: Request, project_id: str, deployment_id: str, project: dict = Depends(verify_project_write_access), current_user: User = Depends(get_current_user)):
    """Cancel an active deployment and kill its worker job."""
    
    with get_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute(
                "SELECT * FROM deployments WHERE deployment_id = %s AND project_id = %s",
                (deployment_id, project_id)
            )
            deployment = cur.fetchone()
            if not deployment:
                raise HTTPException(status_code=404, detail="Deployment not found")
            
            if deployment["state"] not in ("Queued", "Building", "Deploying", "Verifying"):
                raise HTTPException(status_code=400, detail="Cannot cancel a deployment that is not active")

            # Update DB state with optimistic concurrency
            cur.execute(
                "UPDATE deployments SET state = 'Failed', last_error = 'Cancelled by user', updated_at = NOW() WHERE deployment_id = %s AND state IN ('Queued', 'Building', 'Deploying', 'Verifying')",
                (deployment_id,)
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=409, detail="Deployment state changed before cancellation could complete")
        conn.commit()

    # Attempt to kill Kubernetes Job
    try:
        try:
            k8s_config.load_incluster_config()
        except Exception:
            # Fallback for local development if needed, though mostly API runs in cluster
            pass 
        batch_v1 = k8s_client.BatchV1Api()
        job_name = f"build-{deployment_id[:8]}"
        batch_v1.delete_namespaced_job(name=job_name, namespace="shipzen-build", propagation_policy="Background")
        logger.info(f"Killed builder job {job_name} for cancelled deployment {deployment_id}")
    except Exception as e:
        logger.warning(f"Failed to delete kubernetes job for cancelled deployment (may have already completed): {e}")

    log_audit_event(
        project_id=project_id,
        user_id=current_user.user_id,
        action="CANCEL_DEPLOY",
        resource_type="deployment",
        resource_id=deployment_id,
        details={}
    )

    return {"status": "cancelled"}


# Must match the controller's RELEASE_GRACE_MINUTES (same env var, same default).
RELEASE_GRACE_MINUTES = int(os.getenv("RELEASE_GRACE_MINUTES", "10"))


@router.post("/projects/{project_id}/rollback", status_code=202, tags=["Deployments"])
@limiter.limit("5/minute")
def rollback_deployment(request: Request, project_id: str, project: dict = Depends(verify_project_write_access), current_user: User = Depends(get_current_user)):
    """Re-deploy the last known-good image without rebuilding."""

    with get_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            # Find the previous good release. When a release goes live the controller
            # leaves older releases in state 'Running' but scales them to replicas=0,
            # so "previous good" = newest scaled-down Running release whose image is
            # not the one currently serving traffic. (Picking the newest 'Running' row,
            # as before, just re-deployed the live image.)
            # The live release: the one the project points at, else the newest
            # running one. "Previous good" = the newest other Running release
            # with a different image, whether still in its blue-green grace
            # period (replicas > 0) or already scaled to 0.
            cur.execute("""
                SELECT deployment_id, image_uri FROM deployments
                WHERE project_id = %s AND state = 'Running' AND replicas > 0
                ORDER BY (deployment_id = %s) DESC, created_at DESC LIMIT 1;
            """, (project_id, project.get("live_deployment_id") or ""))
            live = cur.fetchone()
            cur.execute("""
                SELECT * FROM deployments
                WHERE project_id = %s AND state = 'Running'
                  AND deployment_id IS DISTINCT FROM %s
                  AND image_uri IS DISTINCT FROM %s
                ORDER BY created_at DESC LIMIT 1;
            """, (project_id, live["deployment_id"] if live else None, live["image_uri"] if live else None))
            last_good = cur.fetchone()

            if not last_good:
                raise HTTPException(
                    status_code=409, detail="No previous successful deployment found to rollback to.")

            if last_good["replicas"] and last_good["replicas"] > 0:
                # Still running (blue-green grace period): switch back instantly by
                # making it the live release again. The release we leave gets its
                # own grace period before the controller scales it down.
                cur.execute("UPDATE projects SET live_deployment_id = %s WHERE id = %s;",
                            (last_good["deployment_id"], project_id))
                cur.execute("UPDATE deployments SET scale_down_after = NULL WHERE deployment_id = %s;",
                            (last_good["deployment_id"],))
                if live:
                    cur.execute(
                        "UPDATE deployments SET scale_down_after = NOW() + make_interval(mins => %s) "
                        "WHERE deployment_id = %s;", (RELEASE_GRACE_MINUTES, live["deployment_id"]))
                conn.commit()
                log_audit_event(
                    project_id=project_id, user_id=current_user.user_id, action="ROLLBACK",
                    resource_type="deployment", resource_id=last_good["deployment_id"],
                    details={"from_image": last_good["image_uri"], "instant": True})
                try:
                    _redis_client.publish("shipzen:events:project_reconcile",
                                          json.dumps({"project_id": project_id, "event": "rollback"}))
                except Exception as pub_err:
                    logger.warning(f"Failed to publish project_reconcile event: {pub_err}")
                return {"message": "Rolled back instantly", "deployment_id": last_good["deployment_id"],
                        "status": "Running", "instant": True}

            deployment_id = str(uuid.uuid4())
            cur.execute("""
                INSERT INTO deployments
                    (deployment_id, project_id, repo_url, image_uri, image_digest, replicas, port, state,
                     branch, commit_sha, commit_message, commit_author, commit_url, triggered_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'Queued', %s, %s, %s, %s, %s, 'rollback')
                RETURNING *;
            """, (
                deployment_id, project_id, last_good['repo_url'],
                # Same image, pinned to the same digest (C4).
                last_good['image_uri'], last_good.get('image_digest'),
                # Old releases were scaled to 0 by the controller; copying that
                # value made the rollback wait for a ready pod that never came.
                1, last_good['port'],
                last_good.get('branch'), last_good.get('commit_sha'), last_good.get('commit_message'),
                last_good.get('commit_author'), last_good.get('commit_url'),
            ))
            cur.fetchone()

            # Transactional outbox
            payload = {
                "deployment_id": deployment_id,
                "project_id":    project_id,
                "repo_url":      last_good['repo_url'],
                "branch":        last_good.get('branch') or "main",
                "image_name":    last_good['image_uri'],
                "queued_at":     str(time.time()),
                "retries":       "0",
                "is_rollback":   "true",
            }
            queue_deployment(cur, payload)
        conn.commit()

    # Publish state update to Redis for websocket (xadd is handled by outbox_relay)
    try:
        r = get_redis()
        r.publish(f"shipzen:status:{deployment_id}", json.dumps(
            {"state": "Queued", "last_error": None}))
    except Exception as e:
        logger.warning(f"Failed to publish status to Redis: {e}")

    log_audit_event(
        project_id=project_id,
        user_id=current_user.user_id,
        action="ROLLBACK",
        resource_type="deployment",
        resource_id=deployment_id,
        details={"from_image": last_good['image_uri']},
    )
    return {"message": "Rollback queued", "deployment_id": deployment_id, "status": "Queued"}


@router.get("/projects/{project_id}/deployments", tags=["Deployments"])
@limiter.limit("100/minute")
def list_deployments(
    request: Request,
    project_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: Optional[str] = Query(
        default=None, description="cursor format: <updated_at>|<deployment_id>"),
    project: dict = Depends(verify_project_access),
):
    """
    List deployments for a project with keyset pagination.
    Pass the `<updated_at>|<deployment_id>` value of the last item as `cursor` to get the next page.
    """

    query = """
        SELECT deployment_id, project_id, repo_url, image_uri, replicas, port, state, updated_at, last_error,
               created_at, branch, commit_sha, commit_message, commit_author, commit_url, triggered_by
        FROM deployments
        WHERE project_id = %s
    """
    params = [project_id]

    if cursor:
        try:
            cursor_updated_at, cursor_deployment_id = cursor.split("|", 1)
            query += " AND (updated_at, deployment_id) < (%s, %s)"
            params.extend([cursor_updated_at, cursor_deployment_id])
        except ValueError:
            raise HTTPException(
                status_code=400, detail="Invalid cursor format")

    query += " ORDER BY updated_at DESC, deployment_id DESC LIMIT %s;"
    params.append(limit)

    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute(query, tuple(params))
                return [_serialize(dict(r)) for r in cur.fetchall()]
    except Exception as e:
        logger.error(f"Failed to list deployments: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to list deployments")


@router.get("/projects/{project_id}/deployments/{deployment_id}", tags=["Deployments"])
@limiter.limit("100/minute")
def get_deployment(request: Request, project_id: str, deployment_id: str, project: dict = Depends(verify_project_access)):
    """Get a single deployment by ID."""
    deployment = _get_deployment_or_404(project_id, deployment_id)
    return _serialize(deployment)


# ── WebSockets: one-time tickets, connection caps, lifetime ──────────────────
# Browsers no longer hold the user's GitHub token (security finding H1), so a
# socket authenticates with a ticket: the UI's server asks POST /ws-tickets
# (with the token) for a random value that is valid once, for 60 seconds. Each
# user may hold WS_MAX_PER_USER sockets per API process, each for at most
# WS_MAX_SECONDS (M5).

WS_TICKET_TTL = 60
WS_MAX_PER_USER = int(os.getenv("WS_MAX_PER_USER", "10"))
WS_MAX_SECONDS = int(os.getenv("WS_MAX_SECONDS", "3600"))
_ws_open = defaultdict(int)


@router.post("/ws-tickets", tags=["Deployments"])
@limiter.limit("60/minute")
async def create_ws_ticket(request: Request, current_user: User = Depends(get_current_user)):
    """A single-use, 60-second ticket the browser sends as its first WebSocket message."""
    ticket = secrets.token_urlsafe(32)
    await _aioredis_client.set(
        f"shipzen:wsticket:{ticket}",
        json.dumps({"user_id": current_user.user_id, "role": current_user.role}),
        ex=WS_TICKET_TTL)
    return {"ticket": ticket, "expires_in": WS_TICKET_TTL}


async def _ws_user(websocket: WebSocket):
    """The user behind a socket's first message: {"ticket": ...}, or {"token": ...} from older clients."""
    try:
        data = json.loads(await websocket.receive_text())
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    if data.get("ticket"):
        raw = await _aioredis_client.getdel(f"shipzen:wsticket:{data['ticket']}")
        if not raw:
            return None
        info = json.loads(raw)
        return User(user_id=info["user_id"], role=info["role"])
    if data.get("token"):
        from auth import get_current_user_from_token
        try:
            return await get_current_user_from_token(data["token"])
        except Exception:
            return None
    return None


async def _ws_open_for(websocket: WebSocket, project_id: str, deployment_id: str):
    """Authenticate, authorize and reserve a connection slot; None (socket closed) if refused."""
    await websocket.accept()
    user = await _ws_user(websocket)
    if user is None:
        await websocket.close(code=1008)
        return None
    try:
        await asyncio.to_thread(verify_project_access, project_id, user)
        await asyncio.to_thread(_get_deployment_or_404, project_id, deployment_id)
    except HTTPException:
        await websocket.close(code=1008)
        return None
    if _ws_open[user.user_id] >= WS_MAX_PER_USER:
        await websocket.close(code=1013)  # try again later
        return None
    _ws_open[user.user_id] += 1
    return user


def _ws_release(user) -> None:
    _ws_open[user.user_id] -= 1
    if _ws_open[user.user_id] <= 0:
        _ws_open.pop(user.user_id, None)


def _keepalive(websocket: WebSocket, send_ping):
    """Ping every 30 s; end the socket when the client is gone or WS_MAX_SECONDS have passed."""
    main_task = asyncio.current_task()
    lifetime = asyncio.get_running_loop().call_later(WS_MAX_SECONDS, main_task.cancel)

    async def ping():
        try:
            while True:
                await asyncio.sleep(30)
                try:
                    await send_ping()
                except Exception:
                    main_task.cancel()
                    break
        except asyncio.CancelledError:
            pass
    return asyncio.create_task(ping()), lifetime


@router.websocket("/ws/projects/{project_id}/deployments/{deployment_id}/status")
async def websocket_deployment_status(websocket: WebSocket, project_id: str, deployment_id: str):
    user = await _ws_open_for(websocket, project_id, deployment_id)
    if user is None:
        return

    pubsub = _aioredis_client.pubsub()
    await pubsub.subscribe(f"shipzen:status:{deployment_id}")

    def fetch_initial():
        with get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute(
                    "SELECT state, last_error FROM deployments WHERE deployment_id = %s AND project_id = %s;",
                    (deployment_id, project_id),
                )
                return cur.fetchone()

    ping_task = lifetime = None
    try:
        row = await asyncio.to_thread(fetch_initial)
        if row:
            await websocket.send_json({"state": row['state'], "last_error": row['last_error']})

        ping_task, lifetime = _keepalive(websocket, lambda: websocket.send_json({"type": "ping"}))

        async for message in pubsub.listen():
            if message["type"] == "message":
                data = json.loads(message["data"])
                await websocket.send_json(data)
                if data.get("state") in ("Running", "Failed", "DLQ"):
                    break
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for {deployment_id}")
    except Exception as e:
        logger.error(f"WS error: {e}")
    finally:
        if ping_task:
            ping_task.cancel()
        if lifetime:
            lifetime.cancel()
        _ws_release(user)
        await pubsub.unsubscribe()
        await pubsub.close()


@router.get("/projects/{project_id}/deployments/{deployment_id}/logs/stream", tags=["Deployments"])
async def stream_logs(project_id: str, deployment_id: str, project: dict = Depends(verify_project_access)):

    # HIGH-05 Fix: Add timeout to SSE Pub/Sub listen to prevent leaked subscriptions
    import asyncio

    async def event_stream():
        pubsub = _aioredis_client.pubsub()
        await pubsub.subscribe(f"shipzen:logs:{deployment_id}")
        try:
            deadline = time.time() + 300  # 5 minute max SSE session
            # listen() blocks until a message arrives, so the deadline was never
            # checked on a quiet stream. Poll with a timeout instead.
            while time.time() < deadline:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message["type"] == "message":
                    yield f"data: {message['data']}\n\n"
        finally:
            await pubsub.unsubscribe()
            await pubsub.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
    )


@router.websocket("/ws/projects/{project_id}/deployments/{deployment_id}/logs")
async def websocket_deployment_logs(
    websocket: WebSocket,
    project_id: str,
    deployment_id: str,
):
    """
    WebSocket endpoint for live build log streaming.
    Subscribes to the Redis Pub/Sub channel `shipzen:logs:{deployment_id}`
    and forwards each line to the connected client as plain text.
    """
    user = await _ws_open_for(websocket, project_id, deployment_id)
    if user is None:
        return

    pubsub = _aioredis_client.pubsub()
    await pubsub.subscribe(f"shipzen:logs:{deployment_id}")

    ping_task = lifetime = None
    try:
        ping_task, lifetime = _keepalive(websocket, lambda: websocket.send_text("ping"))
        async for message in pubsub.listen():
            if message["type"] == "message":
                await websocket.send_text(message["data"])
    except WebSocketDisconnect:
        logger.info(f"Log WS disconnected for {deployment_id}")
    except Exception as e:
        logger.error(f"Log WS error for {deployment_id}: {e}")
    finally:
        if ping_task:
            ping_task.cancel()
        if lifetime:
            lifetime.cancel()
        _ws_release(user)
        await pubsub.unsubscribe()
        await pubsub.close()

# ── Builds ────────────────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/deployments/{deployment_id}/builds", tags=["Builds"])
@limiter.limit("100/minute")
def list_builds(request: Request, project_id: str, deployment_id: str, project: dict = Depends(verify_project_access)):
    """List all builds for a deployment, most recent first."""
    _get_deployment_or_404(project_id, deployment_id)

    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute(
                    """
                    SELECT build_id, deployment_id, gcs_log_uri, status, started_at, completed_at
                    FROM builds
                    WHERE deployment_id = %s
                    ORDER BY started_at DESC;
                    """,
                    (deployment_id,),
                )
                return [_serialize(dict(r)) for r in cur.fetchall()]
    except Exception as e:
        logger.error(f"Failed to list builds: {e}")
        raise HTTPException(status_code=500, detail="Failed to list builds")


@router.get("/projects/{project_id}/deployments/{deployment_id}/builds/{build_id}/logs", tags=["Builds"])
@limiter.limit("100/minute")
def get_build_logs(request: Request, project_id: str, deployment_id: str, build_id: str, project: dict = Depends(verify_project_access)):
    """Stream build log content directly, proxied through the API to avoid CORS issues."""
    _get_deployment_or_404(project_id, deployment_id)

    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute(
                    "SELECT gcs_log_uri FROM builds WHERE build_id = %s AND deployment_id = %s;",
                    (build_id, deployment_id)
                )
                row = cur.fetchone()
                if not row or not row["gcs_log_uri"]:
                    raise HTTPException(
                        status_code=404, detail="Log not found")

                gcs_uri = row["gcs_log_uri"]
                if not gcs_uri.startswith("gs://"):
                    raise HTTPException(
                        status_code=400, detail="Invalid log URI")

                bucket = gcs_uri.split("/")[2]
                key = "/".join(gcs_uri.split("/")[3:])

                if not bucket:
                    raise HTTPException(
                        status_code=404, detail="Log storage not configured")

                try:
                    bucket_obj = _gcs_client.bucket(bucket)
                    blob = bucket_obj.blob(key)
                    if not blob.exists():
                        raise HTTPException(
                            status_code=404, detail="Log file not found in GCS")
                except Exception:
                    raise HTTPException(
                        status_code=404, detail="Log file not found in GCS")

                # HIGH-06 Fix: Stream GCS object instead of loading entirely into memory
                def stream_gcs_body():
                    with blob.open("rb") as f:
                        while True:
                            chunk = f.read(64 * 1024)  # 64KB chunks
                            if not chunk:
                                break
                            yield chunk

                return StreamingResponse(
                    stream_gcs_body(),
                    media_type="text/plain",
                    headers={
                        "Content-Disposition": f"inline; filename=build-{build_id[:8]}.log"}
                )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch build log: {e}")
        raise HTTPException(status_code=500, detail="Failed to get logs")


# ── Restarts ──────────────────────────────────────────────────────────────────

@router.post("/projects/{project_id}/deployments/{deployment_id}/restart", tags=["Deployments"])
@limiter.limit("5/minute")
def restart_deployment(request: Request, project_id: str, deployment_id: str, current_user: User = Depends(get_current_user)):
    """Restart a deployment by patching its pod template with a new restartedAt annotation."""
    project = verify_project_write_access(project_id, current_user)
    deployment = _get_deployment_or_404(project_id, deployment_id)

    # The controller names the Kubernetes Deployment after the full deployment_id
    # (controller/main.py renders app-deployment.yaml.j2 with deployment_name=d_id).
    # The old "<id[:8]>-<project-name>" name never existed, so every restart 500'd.
    deployment_name = deployment_id
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
    try:
        apps_v1.patch_namespaced_deployment(
            name=deployment_name,
            namespace=project["namespace"],
            body=patch
        )
    except Exception as e:
        logger.error(f"Failed to restart deployment {deployment_name}: {e}")
        raise HTTPException(status_code=500, detail="Failed to restart deployment")
    
    log_audit_event(
        project_id=project_id,
        user_id=current_user.user_id,
        action="RESTART",
        resource_type="deployment",
        resource_id=deployment_id,
        details={"deployment_name": deployment_name},
    )
    return {"status": "restarting"}
