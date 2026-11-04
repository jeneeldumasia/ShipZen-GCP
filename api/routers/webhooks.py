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
from crypto_box import decrypt_value
from helpers import check_deploy_limits, image_uri_for, queue_deployment
from ratelimit import limiter

logger = logging.getLogger('api')
router = APIRouter()


def _head_commit(payload: dict) -> tuple:
    """(sha, message, author, url) of the pushed head commit, as GitHub reports it."""
    head = payload.get("head_commit") or {}
    sha = head.get("id") if isinstance(head.get("id"), str) and len(head.get("id")) <= 40 else None
    message = (head.get("message") or "")[:500] or None
    author = ((head.get("author") or {}).get("name") or "")[:255] or None
    url = head.get("url") if str(head.get("url") or "").startswith("https://github.com/") else None
    return sha, message, author, url


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
                webhook_secret = decrypt_value(row["webhook_secret"])
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
    check_deploy_limits(project_id)

    deployment_id = str(uuid.uuid4())
    queued_at = str(time.time())
    image_uri = image_uri_for(project_id, deployment_id)

    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                # CRIT-02: Guard against duplicate webhook deliveries
                cur.execute(
                    "SELECT 1 FROM deployments WHERE project_id = %s AND kind = 'production' AND state IN ('Queued', 'Building', 'Deploying', 'Verifying') LIMIT 1;",
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
                    INSERT INTO deployments (deployment_id, project_id, repo_url, image_uri, replicas, port, state,
                                             branch, triggered_by, commit_sha, commit_message, commit_author, commit_url,
                                             build_context)
                    VALUES (%s, %s, %s, %s, %s, %s, 'Queued', %s, 'push', %s, %s, %s, %s,
                            (SELECT build_context FROM deployments WHERE project_id = %s AND kind = 'production' AND build_context IS NOT NULL ORDER BY created_at DESC LIMIT 1))
                    """,
                    (deployment_id, project_id, repo_url, image_uri, 1, port, branch, *_head_commit(payload), project_id)
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

    event = request.headers.get("X-GitHub-Event")
    if event not in ("push", "pull_request"):
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

    if event == "pull_request":
        return _handle_pull_request(payload)

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
        try:
            check_deploy_limits(project_id)
        except HTTPException as limit:
            logger.info(f"Skipping GitHub App webhook for {project_id}: {limit.detail}")
            continue
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
                        "SELECT 1 FROM deployments WHERE project_id = %s AND kind = 'production' AND state IN ('Queued', 'Building', 'Deploying', 'Verifying') LIMIT 1;",
                        (project_id,)
                    )
                    if cur.fetchone():
                        logger.info(f"Skipping GitHub App webhook for {project_id}: deployment already in-flight")
                        continue

                    cur.execute(
                        """
                        INSERT INTO deployments (deployment_id, project_id, repo_url, image_uri, replicas, port, state,
                                                 branch, triggered_by, commit_sha, commit_message, commit_author, commit_url,
                                                 build_context)
                        VALUES (%s, %s, %s, %s, %s, %s, 'Queued', %s, 'push', %s, %s, %s, %s,
                                (SELECT build_context FROM deployments WHERE project_id = %s AND kind = 'production' AND build_context IS NOT NULL ORDER BY created_at DESC LIMIT 1))
                        """,
                        (deployment_id, project_id, matched_repo_url, image_uri, 1, port, branch, *_head_commit(payload),
                         project_id)
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


# ── Preview deploys for pull requests ────────────────────────────────────────

MAX_PREVIEWS_PER_PROJECT = 3
_PR_BUILD_ACTIONS = {"opened", "synchronize", "reopened"}
_ACTIVE = "('Queued', 'Building', 'Deploying', 'Verifying', 'Running')"


def _handle_pull_request(payload: dict) -> dict:
    """Build a preview of an open pull request; remove its previews when it closes.

    Only pull requests whose branch lives in the project's own repository get a
    preview: a fork's code is untrusted and could be anyone's.
    """
    action = payload.get("action")
    pr = payload.get("pull_request") or {}
    number = pr.get("number")
    base_repo = (pr.get("base") or {}).get("repo") or {}
    head = pr.get("head") or {}
    head_repo = head.get("repo") or {}
    if not isinstance(number, int) or not base_repo.get("id"):
        return {"message": "event ignored"}

    with get_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("SELECT id, repo_url FROM projects WHERE github_repo_id = %s "
                        "AND deleted_at IS NULL AND status = 'Ready';", (int(base_repo["id"]),))
            projects = cur.fetchall()
            if not projects:
                return {"message": "No project for this repository, event ignored"}
            if action == "closed":
                cur.execute(
                    "UPDATE deployments SET state = 'Superseded', updated_at = NOW() "
                    "WHERE project_id = ANY(%s) AND kind = 'preview' AND pr_number = %s "
                    "AND state IN ('Running', 'Failed');",
                    ([p["id"] for p in projects], number))
                conn.commit()
                return {"message": f"Previews of PR #{number} removed"}
    if action not in _PR_BUILD_ACTIONS:
        return {"message": "event ignored"}
    if head_repo.get("id") != base_repo.get("id"):
        logger.info(f"Ignored pull request #{number} from a fork: no preview for untrusted code")
        return {"message": "Pull requests from forks don't get previews"}
    sha, ref = head.get("sha"), head.get("ref")
    if not isinstance(ref, str) or not ref or not isinstance(sha, str) or len(sha) > 40:
        return {"message": "event ignored"}

    created = []
    for project in projects:
        project_id = project["id"]
        try:
            check_deploy_limits(project_id)
        except HTTPException as limit:
            logger.info(f"No preview for {project_id}: {limit.detail}")
            continue
        deployment_id = str(uuid.uuid4())
        image_uri = image_uri_for(project_id, deployment_id)
        title = (pr.get("title") or "")[:500] or None
        author = ((pr.get("user") or {}).get("login") or "")[:255] or None
        pr_url = pr.get("html_url") if str(pr.get("html_url") or "").startswith("https://github.com/") else None
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT 1 FROM deployments WHERE project_id = %s AND kind = 'preview' AND pr_number = %s "
                        "AND state IN ('Queued', 'Building', 'Deploying', 'Verifying') LIMIT 1;",
                        (project_id, number))
                    if cur.fetchone():
                        continue
                    cur.execute(
                        f"SELECT count(DISTINCT pr_number) FROM deployments WHERE project_id = %s "
                        f"AND kind = 'preview' AND pr_number <> %s AND state IN {_ACTIVE};",
                        (project_id, number))
                    if cur.fetchone()[0] >= MAX_PREVIEWS_PER_PROJECT:
                        logger.info(f"No preview for {project_id} PR #{number}: "
                                    f"{MAX_PREVIEWS_PER_PROJECT} pull requests already have one")
                        continue
                    cur.execute("SELECT port FROM deployments WHERE project_id = %s AND kind = 'production' "
                                "ORDER BY created_at DESC LIMIT 1;", (project_id,))
                    port_row = cur.fetchone()
                    port = port_row[0] if port_row and port_row[0] else 8080
                    cur.execute(
                        """
                        INSERT INTO deployments (deployment_id, project_id, repo_url, image_uri, replicas, port, state,
                                                 branch, triggered_by, commit_sha, commit_message, commit_author,
                                                 commit_url, kind, pr_number, build_context)
                        VALUES (%s, %s, %s, %s, 1, %s, 'Queued', %s, 'preview', %s, %s, %s, %s, 'preview', %s,
                                (SELECT build_context FROM deployments WHERE project_id = %s AND kind = 'production' AND build_context IS NOT NULL ORDER BY created_at DESC LIMIT 1))
                        """,
                        (deployment_id, project_id, project["repo_url"], image_uri, port, ref,
                         sha, title, author, pr_url, number, project_id))
                    queue_deployment(cur, {
                        "deployment_id": deployment_id, "project_id": project_id,
                        "repo_url": project["repo_url"], "branch": ref, "image_name": image_uri,
                        "queued_at": str(time.time()), "retries": "0",
                    })
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to queue the preview for {project_id} PR #{number}: {e}")
            continue
        log_audit_event(project_id=project_id, user_id="github-app", action="PREVIEW_DEPLOY",
                        resource_type="deployment", resource_id=deployment_id,
                        details={"pr_number": number, "branch": ref})
        created.append(deployment_id)
    return {"message": "Preview deployments triggered", "deployment_ids": created}
