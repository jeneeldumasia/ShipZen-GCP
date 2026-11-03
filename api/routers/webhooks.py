"""GitHub push webhooks (per-project and GitHub App)."""
import hashlib
import hmac
import logging
import os
import time
import uuid

from psycopg2.extras import DictCursor
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from audit import log_audit_event
from database import get_connection
from helpers import image_uri_for, queue_deployment
from ratelimit import limiter

logger = logging.getLogger('api')
router = APIRouter()


# ── Webhooks ──────────────────────────────────────────────────────────────────


@router.post("/webhooks/github/{project_id}", tags=["Webhooks"])
@limiter.limit("60/minute")
async def github_webhook(request: Request, project_id: str):
    # Verify signature
    signature_header = request.headers.get("x-hub-signature-256")
    if not signature_header:
        raise HTTPException(status_code=400, detail="Missing signature")

    # Fix 2: Only trigger on push events
    if request.headers.get("X-GitHub-Event") != "push":
        return JSONResponse(status_code=200, content={"message": "event ignored"})

    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute(
                    "SELECT webhook_secret, branch, github_repo_id FROM projects WHERE id = %s AND deleted_at IS NULL;", (project_id,))
                row = cur.fetchone()
                if not row or not row["webhook_secret"]:
                    raise HTTPException(
                        status_code=404, detail="Webhook secret not found")
                webhook_secret = row["webhook_secret"]
                target_branch = row.get("branch") or "main"
                bound_repo_id = row.get("github_repo_id")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get webhook secret: {e}")
        raise HTTPException(status_code=500, detail="Database error")

    # Validation logic requires raw body
    body_bytes = await request.body()
    expected_mac = hmac.new(webhook_secret.encode(),
                            body_bytes, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(f"sha256={expected_mac}", signature_header):
        raise HTTPException(status_code=401, detail="Invalid signature")

    import json
    try:
        payload = json.loads(body_bytes)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # CRIT-01 Fix: Only deploy if the pushed branch matches the project's configured branch
    ref = payload.get("ref", "")
    if ref != f"refs/heads/{target_branch}":
        return JSONResponse(status_code=200, content={"message": f"Ignored push to {ref}, expecting {target_branch}"})

    branch = target_branch

    # We need repo URL
    repo_url = payload.get("repository", {}).get("clone_url")
    if not repo_url:
        raise HTTPException(
            status_code=400, detail="Missing repository clone_url")
    # C3: a project bound to a repository only deploys pushes from that repository.
    if bound_repo_id and str(payload.get("repository", {}).get("id")) != str(bound_repo_id):
        raise HTTPException(
            status_code=403, detail="Webhook repository does not match project's repository")

    deployment_id = str(uuid.uuid4())
    queued_at = str(time.time())
    image_uri = image_uri_for(project_id, deployment_id)

    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                # CRIT-02: Guard against duplicate webhook deliveries
                cur.execute(
                    "SELECT 1 FROM deployments WHERE project_id = %s AND state IN ('Queued', 'Building', 'Deploying', 'Verifying') LIMIT 1;",
                    (project_id,)
                )
                if cur.fetchone():
                    return JSONResponse(status_code=200, content={"message": "deployment already in-flight, webhook ignored"})

                cur.execute(
                    "SELECT repo_url, port FROM deployments WHERE project_id = %s ORDER BY updated_at DESC LIMIT 1;",
                    (project_id,)
                )
                last_deploy = cur.fetchone()

                if not last_deploy:
                    # Fallback for the first deployment
                    port = 8080
                else:
                    if last_deploy["repo_url"] != repo_url:
                        raise HTTPException(
                            status_code=403, detail="Webhook repository does not match project's repository")
                    port = last_deploy["port"]

                cur.execute(
                    """
                    INSERT INTO deployments (deployment_id, project_id, repo_url, image_uri, replicas, port, state)
                    VALUES (%s, %s, %s, %s, %s, %s, 'Queued')
                    """,
                    (deployment_id, project_id, repo_url, image_uri, 1, port)
                )
                # Transactional outbox — atomic with deployment INSERT.
                outbox_payload = {
                    "deployment_id": deployment_id,
                    "project_id":    project_id,
                    "repo_url":      repo_url,
                    "branch":        branch,
                    "image_name":    image_uri,
                    "queued_at":     queued_at,
                    "retries":       "0",
                }
                queue_deployment(cur, outbox_payload)
            conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Failed to process webhook DB insert for {project_id}: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to process webhook")

    log_audit_event(
        project_id=project_id,
        user_id="webhook",
        action="WEBHOOK_DEPLOY",
        resource_type="deployment",
        resource_id=deployment_id,
        details={"repo_url": repo_url, "branch": branch},
    )

    return {"message": "Deployment triggered", "deployment_id": deployment_id}


@router.post("/webhooks/github-app", tags=["Webhooks"])
@limiter.limit("120/minute")
async def github_app_webhook(request: Request):
    """Global webhook receiver for the ShipZen GitHub App."""
    signature_header = request.headers.get("x-hub-signature-256")
    if not signature_header:
        raise HTTPException(status_code=400, detail="Missing signature")

    if request.headers.get("X-GitHub-Event") != "push":
        return JSONResponse(status_code=200, content={"message": "event ignored"})

    app_secret = os.getenv("GITHUB_APP_WEBHOOK_SECRET")
    if not app_secret:
        logger.error("GITHUB_APP_WEBHOOK_SECRET is not set")
        raise HTTPException(
            status_code=500, detail="Server configuration error")

    body_bytes = await request.body()
    expected_mac = hmac.new(app_secret.encode(),
                            body_bytes, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(f"sha256={expected_mac}", signature_header):
        raise HTTPException(status_code=401, detail="Invalid signature")

    import json
    try:
        payload = json.loads(body_bytes)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    branch = "main"
    if "ref" in payload:
        branch = payload["ref"].split("/")[-1]

    # payload['repository']['clone_url'] gives https://github.com/owner/repo.git
    # payload['repository']['html_url'] gives https://github.com/owner/repo
    repo_url = payload.get("repository", {}).get("clone_url")
    html_url = payload.get("repository", {}).get("html_url")
    if not repo_url and not html_url:
        raise HTTPException(
            status_code=400, detail="Missing repository URL in payload")

    # Find matching projects
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                # Find all active projects that use this repo and track this branch
                cur.execute(
                    """
                    SELECT id as project_id, branch, github_repo_id
                    FROM projects
                    WHERE (repo_url = %s OR repo_url = %s) AND deleted_at IS NULL;
                    """,
                    (repo_url, html_url)
                )
                all_matching_projects = cur.fetchall()

                # Filter by branch
                projects_to_deploy = []
                pushed_repo_id = str(payload.get("repository", {}).get("id"))
                for p in all_matching_projects:
                    # C3: a bound project only follows its own repository, even
                    # if another repository later takes over the same URL.
                    if p.get("github_repo_id") and str(p["github_repo_id"]) != pushed_repo_id:
                        continue
                    target_branch = p.get("branch") or "main"
                    if payload.get("ref", "") == f"refs/heads/{target_branch}":
                        projects_to_deploy.append(p)

                if not projects_to_deploy:
                    logger.info(
                        f"Ignored push event for {repo_url} on {payload.get('ref', '')} - no matching ShipZen project tracking this branch.")
                    return JSONResponse(status_code=200, content={"message": "No matching project tracking this branch, event ignored"})

    except Exception as e:
        logger.error(f"Failed to lookup project for github app webhook: {e}")
        raise HTTPException(
            status_code=500, detail="Database error during project lookup")

    deployed_ids = []

    for row in projects_to_deploy:
        project_id = row["project_id"]
        matched_repo_url = repo_url
        branch = row.get("branch") or "main"

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    # Get the port from the last deployment, default to 8080
                    cur.execute(
                        "SELECT port FROM deployments WHERE project_id = %s ORDER BY created_at DESC LIMIT 1;", 
                        (project_id,)
                    )
                    port_row = cur.fetchone()
                    port = port_row[0] if port_row else 8080

        except Exception as e:
            logger.error(f"Failed to lookup port for {project_id}: {e}")
            port = 8080

        deployment_id = str(uuid.uuid4())
        queued_at = str(time.time())
        image_uri = image_uri_for(project_id, deployment_id)

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    # CRIT-02: Guard against in-flight deployments from concurrent webhook deliveries
                    cur.execute(
                        "SELECT 1 FROM deployments WHERE project_id = %s AND state IN ('Queued', 'Building', 'Deploying', 'Verifying') LIMIT 1;",
                        (project_id,)
                    )
                    if cur.fetchone():
                        logger.info(f"Skipping GitHub App webhook for {project_id}: deployment already in-flight")
                        continue

                    cur.execute(
                        """
                        INSERT INTO deployments (deployment_id, project_id, repo_url, image_uri, replicas, port, state)
                        VALUES (%s, %s, %s, %s, %s, %s, 'Queued')
                        """,
                        (deployment_id, project_id, matched_repo_url, image_uri, 1, port)
                    )
                    # Transactional outbox — atomic with the deployment INSERT.
                    outbox_payload = {
                        "deployment_id": deployment_id,
                        "project_id":    project_id,
                        "repo_url":      matched_repo_url,
                        "branch":        branch,
                        "image_name":    image_uri,
                        "queued_at":     queued_at,
                        "retries":       "0",
                    }
                    queue_deployment(cur, outbox_payload)
                conn.commit()
        except Exception as e:
            logger.error(
                f"Failed to process webhook DB insert for {project_id}: {e}")
            continue

        log_audit_event(
            project_id=project_id,
            user_id="github-app",
            action="WEBHOOK_DEPLOY",
            resource_type="deployment",
            resource_id=deployment_id,
            details={"repo_url": matched_repo_url,
                     "branch": branch, "via": "github-app"},
        )
        deployed_ids.append(deployment_id)

    return {"message": "Deployments triggered via GitHub App", "deployment_ids": deployed_ids}
