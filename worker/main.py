import redis
import time
import logging
import json
import re
import os
import subprocess
import shutil
import uuid
from google.cloud import storage
import google.auth
import google.auth.transport.requests
import base64
import signal
import yaml
from concurrent.futures import ThreadPoolExecutor
from kubernetes import client, config as k8s_config, watch
from kubernetes.client.rest import ApiException

from config import config
from queue_client import QueueClient
from state_machine import StateMachine, DeploymentState
from builder import DockerfileBuilder, NixpacksBuilder
from metrics import (
    start_metrics_server,
    shipzen_build_duration_seconds,
    shipzen_queue_latency_seconds,
    shipzen_retry_total,
    shipzen_deployment_failure_total,
    shipzen_dlq_depth,
    shipzen_deployments_total
)

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('worker')


from shipzen_common.github_app import get_github_app_token, git_auth_env, git_auth_header
from shipzen_common.repo_config import parse_repo_config, RepoConfigError
from shipzen_common.redact import redact


try:
    k8s_config.load_incluster_config()
except k8s_config.ConfigException:
    k8s_config.load_kube_config()

batch_v1 = client.BatchV1Api()
core_v1 = client.CoreV1Api()


GCS_LOG_BUCKET = os.environ.get("GCS_LOG_BUCKET", "")

# Limit concurrent monitoring threads to prevent unbounded thread exhaustion
import threading
# MED-07 Fix: Reduce MAX_WORKERS from 200 to 20 to match DB pool size and prevent OOM
MAX_WORKERS = 20
_executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
_semaphore = threading.Semaphore(MAX_WORKERS)

# PERF-04 Fix: Shared module-level Redis client
_redis_client = redis.Redis(host=config.REDIS_HOST, port=config.REDIS_PORT, password=config.REDIS_PASSWORD)

# Health check: tracks when the main loop last successfully iterated.
# Liveness probe will fail if this hasn't been updated in >120s (stuck loop).
_last_loop_tick = time.time()

from database import get_db_connection


def _start_health_server(port: int = 8000):
    """
    Start an HTTP server on `port` that serves:
      GET /healthz  — 200 if Redis ping succeeds, 503 otherwise.
      GET /metrics  — Prometheus text format (delegated to prometheus_client).
    This replaces the bare prometheus_client.start_http_server() so that
    liveness/readiness probes can hit /healthz and get a meaningful status
    instead of always-200 Prometheus text regardless of queue health.
    """
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

    class HealthHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # Suppress noisy access logs from probe traffic

        def do_GET(self):
            if self.path == "/healthz":
                try:
                    _redis_client.ping()
                    # Also check that main loop is alive (not stuck)
                    stuck = (time.time() - _last_loop_tick) > 120
                    if stuck:
                        self.send_response(503)
                        self.end_headers()
                        self.wfile.write(b"ERROR: main loop stuck")
                    else:
                        self.send_response(200)
                        self.end_headers()
                        self.wfile.write(b"OK")
                except Exception as e:
                    self.send_response(503)
                    self.end_headers()
                    self.wfile.write(f"ERROR: {e}".encode())
            elif self.path in ("/metrics", "/"):
                output = generate_latest()
                self.send_response(200)
                self.send_header("Content-Type", CONTENT_TYPE_LATEST)
                self.end_headers()
                self.wfile.write(output)
            else:
                self.send_response(404)
                self.end_headers()

    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    logger.info(f"Health+metrics server started on port {port} (/healthz, /metrics)")


# ── Build output: staging → verified registry (security finding C4) ───────────
# Builds run untrusted Dockerfiles, so they never get credentials for the
# registry apps run from. Kaniko pushes to shipzen-staging with a 1-hour token
# that can do nothing else, and reports the digest of what it pushed in its
# termination message. The worker copies exactly that digest into
# shipzen-builds, and the controller deploys it by digest, so no other build can
# swap the content under a tag.

_DIGEST_RE = re.compile(r"\Asha256:[0-9a-f]{64}\Z")


def staging_uri_for(image_name: str) -> str:
    """Where a build pushes before verification: shipzen-builds -> shipzen-staging."""
    return image_name.replace("/shipzen-builds/", "/shipzen-staging/", 1)


def _builder_push_token(image_name: str) -> str:
    """1-hour token for the push-only builder identity, minted by the worker's own identity."""
    from google.auth import impersonated_credentials
    project = image_name.split("/")[1]
    target = os.environ.get("BUILDER_SA_EMAIL") or f"shipzen-builder-sa@{project}.iam.gserviceaccount.com"
    source, _ = google.auth.default()
    creds = impersonated_credentials.Credentials(
        source_credentials=source, target_principal=target,
        target_scopes=["https://www.googleapis.com/auth/cloud-platform"], lifetime=3600)
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token


def create_registry_secret(deployment_id: str, image_name: str):
    """Per-build Docker config that lets Kaniko push to shipzen-staging. None in local dev."""
    if image_name.startswith("local/"):
        return None
    registry = image_name.split("/")[0]
    token = _builder_push_token(image_name)
    auth = base64.b64encode(f"oauth2accesstoken:{token}".encode()).decode()
    name = f"registry-{deployment_id[:8]}"
    secret = client.V1Secret(
        metadata=client.V1ObjectMeta(name=name, namespace="shipzen-build"),
        string_data={"config.json": json.dumps({"auths": {registry: {"auth": auth}}})},
    )
    try:
        core_v1.create_namespaced_secret(namespace="shipzen-build", body=secret)
    except ApiException as e:
        if e.status != 409:
            raise
        core_v1.replace_namespaced_secret(name=name, namespace="shipzen-build", body=secret)
    return name


def _build_digest(pod_name: str) -> str:
    """The digest Kaniko reported (--digest-file=/dev/termination-log)."""
    pod = core_v1.read_namespaced_pod(name=pod_name, namespace="shipzen-build")
    for status in pod.status.container_statuses or []:
        if status.name == "kaniko" and status.state and status.state.terminated:
            digest = (status.state.terminated.message or "").strip()
            if _DIGEST_RE.match(digest):
                return digest
    raise RuntimeError("The build finished but didn't report the digest of the image it pushed")


def _crane_login(image_name: str, deployment_id: str) -> dict:
    """crane env logged in to Artifact Registry with the worker's own identity."""
    credentials, _ = google.auth.default()
    credentials.refresh(google.auth.transport.requests.Request())
    # The root filesystem is read-only, so crane can't write ~/.docker; give it
    # a per-build config dir under the writable /tmp mount. The token goes in on
    # stdin: as an argv entry it ended up in the error text and the worker log.
    env = {**os.environ, "DOCKER_CONFIG": f"/tmp/crane_{deployment_id}"}
    login = subprocess.run(
        ["crane", "auth", "login", image_name.split("/")[0], "-u", "oauth2accesstoken", "--password-stdin"],
        input=credentials.token, text=True, capture_output=True, env=env)
    if login.returncode != 0:
        shutil.rmtree(env["DOCKER_CONFIG"], ignore_errors=True)
        raise RuntimeError(f"crane auth login failed (exit {login.returncode}): {login.stderr.strip()[:300]}")
    return env


def promote_image(staging_uri: str, digest: str, image_name: str, crane_env: dict) -> None:
    """Copy staging@digest to image_name (in shipzen-builds), byte for byte."""
    source = f"{staging_uri.split('@')[0].rsplit(':', 1)[0]}@{digest}"
    cp = subprocess.run(["crane", "copy", source, image_name], text=True, capture_output=True, env=crane_env)
    if cp.returncode != 0:
        raise RuntimeError(f"Copying the built image failed (exit {cp.returncode}): {cp.stderr.strip()[:300]}")


def record_commit(deployment_id: str, workspace: str, repo_url: str) -> None:
    """Store which commit this deployment builds (unless a push payload already did)."""
    try:
        out = subprocess.run(["git", "log", "-1", "--format=%H%x00%an%x00%s"], cwd=workspace,
                             capture_output=True, text=True, timeout=15)
        sha, author, subject = (out.stdout.strip().split("\x00") + ["", "", ""])[:3]
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            return
        url = None
        if repo_url.startswith("https://github.com/"):
            url = f"{repo_url.rstrip('/').removesuffix('.git')}/commit/{sha}"
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE deployments SET commit_sha = COALESCE(commit_sha, %s), "
                    "commit_message = COALESCE(commit_message, %s), commit_author = COALESCE(commit_author, %s), "
                    "commit_url = COALESCE(commit_url, %s) WHERE deployment_id = %s;",
                    (sha, redact(subject[:500]), author[:255], url, deployment_id))
    except Exception as e:
        logger.warning(f"Could not record the commit for {deployment_id}: {type(e).__name__}")


def bound_repo_mismatch(project_id: str, repo_url: str):
    """The project's linked GitHub repository if repo_url is a different one, else None.

    The API already refuses repositories the user can't read and checks the
    project's binding (security finding C3); this is the worker's own check,
    so it never fetches a GitHub App token for another repository.
    """
    if not project_id or not repo_url.startswith("https://github.com/"):
        return None
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT github_repo_full_name FROM projects WHERE id = %s;", (project_id,))
            row = cur.fetchone()
    bound = row[0] if row else None
    if not bound:
        return None
    named = repo_url.rstrip("/").removesuffix(".git").split("github.com/", 1)[1]
    return bound if named.lower() != bound.lower() else None


def record_build(deployment_id: str, gcs_key: str, status: str):
    build_id = str(uuid.uuid4())
    if not GCS_LOG_BUCKET:
        logger.warning(
            f"GCS_LOG_BUCKET not set — skipping build record for {deployment_id}")
        return
    gcs_uri = f"gs://{GCS_LOG_BUCKET}/{gcs_key}"
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO builds (build_id, deployment_id, gcs_log_uri, status)
                    VALUES (%s, %s, %s, %s);
                """, (build_id, deployment_id, gcs_uri, status))
    except Exception as e:
        logger.error(f"Failed to record build for {deployment_id}: {e}")


def _build_containers(pod_name: str) -> list:
    """Init containers then main containers of the build pod, in run order."""
    try:
        pod = core_v1.read_namespaced_pod(name=pod_name, namespace="shipzen-build")
        names = [c.name for c in (pod.spec.init_containers or [])]
        return names + [c.name for c in pod.spec.containers]
    except Exception as e:
        logger.warning(f"Could not read containers of {pod_name}: {e}")
        return ["kaniko"]


def _read_container_log(pod_name: str, container: str) -> str:
    """Whole log of one container so far; empty if it hasn't started yet."""
    try:
        return core_v1.read_namespaced_pod_log(
            name=pod_name, namespace="shipzen-build", container=container,
            follow=False, _preload_content=True, timestamps=False,
        ) or ""
    except Exception:
        return ""  # container not started yet, or pod gone


def _publish_line(r, deployment_id: str, line: str):
    try:
        r.publish(f"shipzen:logs:{deployment_id}", line)
    except Exception:
        pass


def monitor_job(job_name: str, deployment_id: str, image_name: str, state_machine: StateMachine, builder_type: str = "unknown", project_id: str = "unknown", queue: QueueClient = None, message_id: str = None, trace_id: str = "unknown"):
    """Monitors the Kubernetes Job, streams logs to Redis, and finalizes the deployment.

    This implementation avoids long-lived HTTP watch/follow streams that get killed
    by GCP's infrastructure idle timeout (~5 min). Instead it:
      1. Polls for the builder pod to appear.
      2. Polls for the job to reach a terminal state (succeeded/failed).
      3. Publishes incremental log tails to Redis while polling.
      4. Collects full logs after job completion.
    """
    logger.info(f"Monitoring Job {job_name} for deployment {deployment_id} [trace_id={trace_id}]")
    r = _redis_client
    gcs_log_key = f"logs/{deployment_id}/build.log"
    build_start_time = time.time()

    try:
        # ── Step 1: Wait for the builder Pod to exist (polling) ──────────
        pod_name = None
        deadline = time.time() + 300  # 5 min
        while time.time() < deadline:
            try:
                pods = core_v1.list_namespaced_pod(
                    namespace="shipzen-build",
                    label_selector=f"job-name={job_name}",
                )
                if pods.items:
                    pod_name = pods.items[0].metadata.name
                    break
            except Exception as e:
                logger.warning(f"Error listing pods for {job_name}: {e}")
            time.sleep(3)

        if not pod_name:
            raise Exception("Timed out waiting for Pod to be created")

        state_machine.update_state(deployment_id, DeploymentState.BUILDING)

        # ── Step 2: Poll job status until terminal, streaming log tails ──
        # Read every container in order (init containers first). Reading only the
        # pod's default container returned nothing while the git-clone / Nixpacks
        # init containers ran, so the UI showed no logs for the first minutes.
        job_succeeded = False
        containers = _build_containers(pod_name)
        sent = {c: 0 for c in containers}   # characters already published, per container
        timeout = time.time() + 3600  # 1 hour hard cap

        while time.time() < timeout:
            # --- publish incremental logs to Redis ---
            for c in containers:
                raw_log = _read_container_log(pod_name, c)
                if raw_log and len(raw_log) > sent[c]:
                    if sent[c] == 0 and len(containers) > 1:
                        _publish_line(r, deployment_id, f"── {c} ──")
                    for line in raw_log[sent[c]:].splitlines():
                        _publish_line(r, deployment_id, line)
                    sent[c] = len(raw_log)

            # --- check job terminal state ---
            try:
                job = batch_v1.read_namespaced_job(name=job_name, namespace="shipzen-build")
                if job.status.succeeded and job.status.succeeded >= 1:
                    job_succeeded = True
                    break
                if job.status.failed and job.status.failed >= 1:
                    break
            except ApiException as e:
                if e.status == 404:
                    break
                logger.warning(f"Error checking job status: {e}")
            except Exception as e:
                logger.warning(f"Error checking job status: {e}")

            time.sleep(5)

        # ── Step 3: Collect final complete logs (all containers) ─────────
        parts = []
        try:
            for c in containers:
                raw_log = _read_container_log(pod_name, c)
                if not raw_log:
                    continue
                if len(raw_log) > sent[c]:
                    for line in raw_log[sent[c]:].splitlines():
                        _publish_line(r, deployment_id, line)
                    sent[c] = len(raw_log)
                parts.append(f"--- {c} ---\n{raw_log}")
        except Exception as e:
            logger.warning(f"Failed to collect final logs: {e}")
        stdout_bytes = "\n".join(parts).encode("utf-8")

        # ── Step 4: Upload logs to GCS ───────────────────────────────────
        try:
            if GCS_LOG_BUCKET:
                storage_client = storage.Client()
                bucket = storage_client.bucket(GCS_LOG_BUCKET)
                blob = bucket.blob(gcs_log_key)
                blob.metadata = {"trace_id": str(trace_id), "deployment_id": str(deployment_id)}
                blob.upload_from_string(stdout_bytes, content_type="text/plain")
        except Exception as e:
            logger.error(f"GCS upload failed: {e}")

        # Observe build duration
        build_duration = time.time() - build_start_time
        shipzen_build_duration_seconds.labels(
            project_id=project_id, builder_type=builder_type).observe(build_duration)

        if job_succeeded:
            logger.info(
                f"Build {deployment_id} successful. Reading the image config...")

            # C4: copy exactly what this build reported pushing from staging
            # into shipzen-builds (only the platform can write there), and pin
            # the deployment to that digest. Raises, failing the deployment, if
            # anything doesn't check out.
            digest = _build_digest(pod_name)
            crane_env = _crane_login(image_name, deployment_id)
            try:
                promote_image(staging_uri_for(image_name), digest, image_name, crane_env)
                with get_db_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("UPDATE deployments SET image_digest = %s WHERE deployment_id = %s;",
                                    (digest, deployment_id))

                # Dynamic port detection from the image's EXPOSE (best effort).
                try:
                    cfg = subprocess.run(["crane", "config", f"{image_name}@{digest}"], text=True,
                                         capture_output=True, env=crane_env)
                    if cfg.returncode != 0:
                        raise RuntimeError(f"crane config failed (exit {cfg.returncode}): {cfg.stderr.strip()[:300]}")
                    exposed_ports = json.loads(cfg.stdout).get("config", {}).get("ExposedPorts", {})
                    if exposed_ports:
                        first_port = list(exposed_ports.keys())[0].split('/')[0]
                        with get_db_connection() as conn:
                            with conn.cursor() as cur:
                                cur.execute("UPDATE deployments SET port = %s WHERE deployment_id = %s;",
                                            (int(first_port), deployment_id))
                except Exception as e:
                    logger.warning(f"Failed to extract exposed port: {e}")
            finally:
                shutil.rmtree(crane_env["DOCKER_CONFIG"], ignore_errors=True)

            record_build(deployment_id, gcs_log_key, "Success")
            state_machine.update_state(deployment_id, "Deploying")

        else:
            logger.error(f"Job {job_name} failed.")
            record_build(deployment_id, gcs_log_key, "Failed")
            shipzen_deployment_failure_total.inc()
            shipzen_deployments_total.labels(state="Failed", project_id=project_id).inc()
            error_msg = "Build step failed."
            if stdout_bytes:
                # Convert to string and split lines
                log_str = stdout_bytes.decode('utf-8', errors='replace')
                lines = [line.strip() for line in log_str.splitlines() if line.strip()]
                if lines:
                    # Take the last 5 lines for context
                    error_msg = f"Build failed: {' | '.join(lines[-5:])}"[:1000]
            
            state_machine.update_state(
                deployment_id, "Failed", error_msg)

    except Exception as e:
        logger.error(f"Error monitoring job {job_name}: {e}")
        record_build(deployment_id, gcs_log_key, "Failed")
        shipzen_deployment_failure_total.inc()
        shipzen_deployments_total.labels(state="Failed", project_id=project_id).inc()
        state_machine.update_state(deployment_id, "Failed", str(e))
    finally:
        # Cleanup Job
        try:
            batch_v1.delete_namespaced_job(
                job_name, "shipzen-build", propagation_policy="Background")
        except Exception:
            pass
        pass


def process_message(queue: QueueClient, state_machine: StateMachine, message_id: str, data: dict):
    deployment_id = data.get("deployment_id")
    repo_url = data.get("repo_url")
    branch = data.get("branch", "main")
    image_name = data.get("image_name")

    if not deployment_id or not repo_url or not image_name:
        queue.add_to_dlq(message_id, data)
        return
        
    # CRIT-01 Fix: Additional branch name validation at worker level
    import re
    if not re.match(r'^[a-zA-Z0-9_.\-/]{1,200}$', branch):
        logger.error(f"Invalid branch name received: {branch}")
        queue.add_to_dlq(message_id, data)
        return

    deployment = state_machine.get_deployment(deployment_id)
    if deployment and deployment.get("state") in [DeploymentState.DEPLOYING, DeploymentState.RUNNING]:
        queue.ack_message(message_id)
        return

    # Fix 1: Skip building if this is a rollback, just advance state
    if data.get("is_rollback") == "true":
        logger.info(
            f"Deployment {deployment_id} is a rollback, skipping build.")
        state_machine.update_state(deployment_id, "Deploying")
        queue.ack_message(message_id)
        return

    logger.info(f"Processing deployment {deployment_id}")
    shipzen_deployments_total.labels(state="Processing", project_id=deployment.get("project_id", "unknown") if deployment else "unknown").inc()

    # Calculate queue latency from Redis stream ID
    try:
        if isinstance(message_id, bytes):
            msg_id_str = message_id.decode("utf-8")
        else:
            msg_id_str = str(message_id)
        timestamp_ms = int(msg_id_str.split("-")[0])
        queue_latency = time.time() - (timestamp_ms / 1000.0)
        shipzen_queue_latency_seconds.observe(queue_latency)
    except Exception:
        pass

    # Fix 8: Workspace directory leaks on clone failure, moved creation inside try and cleanup to finally
    workspace = f"/tmp/workspace_{deployment_id}"
    # HIGH-11 Fix: Initialize before try block to prevent UnboundLocalError in finally
    github_secret_name = None
    registry_secret_name = None
    try:
        # The token never goes into a URL or a command line: git reads it from
        # GIT_CONFIG_* env vars, so it can't leak through exception messages
        # (which become last_error, visible to every project member) or end up
        # in the cloned repo's .git/config and from there in the built image.
        git_env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        bound = bound_repo_mismatch(deployment.get("project_id") if deployment else data.get("project_id"), repo_url)
        if bound:
            raise RepoConfigError(f"This project deploys {bound}; it can't build {repo_url}.")
        if repo_url.startswith("https://github.com/"):
            token = get_github_app_token(repo_url)
            if token:
                git_env.update(git_auth_env(token))
                github_secret_name = f"git-token-{deployment_id[:8]}"
                secret = client.V1Secret(
                    metadata=client.V1ObjectMeta(name=github_secret_name, namespace="shipzen-build"),
                    string_data={"GIT_AUTH_HEADER": git_auth_header(token)}
                )
                try:
                    core_v1.create_namespaced_secret(namespace="shipzen-build", body=secret)
                except ApiException as e:
                    if e.status == 409:
                        core_v1.replace_namespaced_secret(name=github_secret_name, namespace="shipzen-build", body=secret)
                    else:
                        raise

        # Shallow clone to detect builder (worker local)
        os.makedirs(workspace, exist_ok=True)
        subprocess.run(["git", "clone", "--depth=1", "--filter=blob:none", "--sparse", "--branch",
                       branch, repo_url, workspace], check=True, timeout=120, env=git_env)
        record_commit(deployment_id, workspace, repo_url)
        subprocess.run(["git", "sparse-checkout", "set", "--no-cone", "shipzen.yaml", "deployhub.yml", "Dockerfile", "Cargo.toml", "bun.lockb", "package.json"], cwd=workspace, check=True)

        # Check overrides
        overrides = {}
        config_path = os.path.join(workspace, "shipzen.yaml")
        if not os.path.exists(config_path):
            config_path = os.path.join(workspace, "deployhub.yml")
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                # Untrusted: only validated keys come back (see repo_config.py).
                cfg = parse_repo_config(yaml.safe_load(f))
                if cfg:
                    overrides = cfg
                    new_port = cfg.get("port")
                    new_health = cfg.get("health_check_path")
                    if new_port or new_health:
                        with get_db_connection() as conn:
                            with conn.cursor() as cur:
                                if new_port and new_health:
                                    cur.execute("UPDATE deployments SET port = %s, health_check_path = %s WHERE deployment_id = %s;", (
                                        new_port, new_health, deployment_id))
                                elif new_port:
                                    cur.execute(
                                        "UPDATE deployments SET port = %s WHERE deployment_id = %s;", (new_port, deployment_id))
                                elif new_health:
                                    cur.execute(
                                        "UPDATE deployments SET health_check_path = %s WHERE deployment_id = %s;", (new_health, deployment_id))

        # SPA detection
        package_json_path = os.path.join(workspace, "package.json")
        if os.path.exists(package_json_path):
            if os.path.getsize(package_json_path) > 1024 * 1024:
                logger.warning(f"package.json too large to parse for {deployment_id}")
            else:
                try:
                    with open(package_json_path, 'r') as f:
                        pj = json.load(f)
                    scripts = pj.get("scripts", {})
                    deps = {**pj.get("dependencies", {}), **pj.get("devDependencies", {})}
                    if "start" not in scripts:
                        if any(m in deps for m in ["vite", "react-scripts", "vue", "svelte", "astro"]) or ("build" in scripts):
                            overrides["inject_server_js"] = True
                    if "build" in scripts:
                        overrides["bp_node_run_scripts"] = "build"
                except json.JSONDecodeError:
                    pass

        # Builder detection
        builders = [DockerfileBuilder(), NixpacksBuilder()]
        selected_builder = None
        for b in builders:
            if b.detect(workspace, overrides):
                selected_builder = b
                break

        if not selected_builder:
            raise Exception("No suitable builder found")
        # GCP GAR creates packages on push automatically, so no repo creation needed here.
        

        trace_id = data.get("trace_id", deployment_id)
        overrides["trace_id"] = trace_id

        if github_secret_name:
            overrides["github_secret_name"] = github_secret_name

        # The Job gets the GitHub token only through the git-token-* Secret (as a
        # git header), and a push token for staging only through registry-*.
        registry_secret_name = create_registry_secret(deployment_id, image_name)
        if registry_secret_name:
            overrides["registry_secret_name"] = registry_secret_name
        manifest = selected_builder.generate_job_manifest(
            deployment_id, repo_url, branch, staging_uri_for(image_name), overrides)
        job_name = manifest["metadata"]["name"]

        # Create Job
        try:
            batch_v1.create_namespaced_job(
                namespace="shipzen-build", body=manifest)
            logger.info(f"Created Job {job_name} for deployment {deployment_id} [trace_id={trace_id}]")
        except ApiException as e:
            if e.status == 409:
                logger.info(f"Job {job_name} already exists (XAUTOCLAIM redelivery). Continuing to monitor.")
            else:
                raise Exception(f"Kubernetes Job creation failed (HTTP {e.status}): {e.reason}. Body: {e.body}")

        # Call monitor_job synchronously in this thread
        builder_type = selected_builder.name if hasattr(
            selected_builder, 'name') else type(selected_builder).__name__
        project_id_db = deployment.get(
            "project_id", "unknown") if deployment else "unknown"
        monitor_job(job_name, deployment_id, image_name, state_machine, builder_type, project_id_db, queue, message_id, trace_id=trace_id)
        queue.ack_message(message_id)

    except Exception as e:
        # Persist the actual error so the UI can display it rather than the
        # generic "Build step failed." message. Every project member can read it,
        # so credentials are scrubbed first.
        if isinstance(e, RepoConfigError):
            message = str(e)
        elif isinstance(e, subprocess.CalledProcessError) and e.cmd and e.cmd[:2] == ["git", "clone"]:
            message = (f"Could not clone {repo_url} (branch '{branch}'). Check that the "
                       "repository and branch exist and that the ShipZen GitHub App can access it.")
        else:
            message = redact(str(e))
        logger.error(f"Error processing {deployment_id}: {redact(str(e))}")
        state_machine.update_state(deployment_id, "Failed", message)
        shipzen_deployment_failure_total.inc()
        shipzen_deployments_total.labels(state="Failed", project_id=deployment.get("project_id", "unknown") if deployment else "unknown").inc()
        queue.add_to_dlq(message_id, data)
        shipzen_dlq_depth.inc()
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
        for secret_name in (github_secret_name, registry_secret_name):
            if not secret_name:
                continue
            try:
                core_v1.delete_namespaced_secret(name=secret_name, namespace="shipzen-build")
            except Exception as e:
                logger.warning(f"Failed to delete build secret {secret_name}: {e}")


def _process_and_release(queue: QueueClient, state_machine: StateMachine, message_id: str, data: dict):
    """Run process_message and always give the worker slot back.

    process_message has several early returns (rollbacks, duplicate deliveries,
    invalid payloads) that happen before its try/finally. Releasing the slot
    there meant each of those leaked one of the MAX_WORKERS slots; after 20 the
    main loop blocked forever in _semaphore.acquire().
    """
    try:
        process_message(queue, state_machine, message_id, data)
    except Exception:
        logger.exception(f"Unhandled error processing message {message_id}")
    finally:
        _semaphore.release()


def main():
    # HIGH-10 Fix: Graceful shutdown flag
    _shutdown = False

    def handle_sigterm(signum, frame):
        nonlocal _shutdown
        logger.info("Received SIGTERM, initiating graceful shutdown...")
        _shutdown = True

    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    _start_health_server(port=8000)
    queue = QueueClient()
    state_machine = StateMachine()

    logger.info(
        f"Worker {config.CONSUMER_NAME} started. Listening on stream {config.STREAM_NAME}")

    # REL-02 Fix: Track backoff state
    error_backoff = 2

    while not _shutdown:
        global _last_loop_tick
        try:
            claimed = queue.recover_pending_messages()
            if claimed:
                for msg_id, data in claimed:
                    shipzen_retry_total.inc()
                    _semaphore.acquire()
                    try:
                        _executor.submit(_process_and_release, queue, state_machine, msg_id, data)
                    except Exception:
                        _semaphore.release()
                        raise

            messages = queue.get_messages(count=5, block_ms=2000)
            if messages:
                for stream_name, msg_list in messages:
                    for msg_id, data in msg_list:
                        _semaphore.acquire()
                        try:
                            _executor.submit(_process_and_release, queue, state_machine, msg_id, data)
                        except Exception:
                            _semaphore.release()
                            raise

            # Heartbeat: update the liveness timestamp on every successful iteration
            _last_loop_tick = time.time()
            # Reset backoff on success
            error_backoff = 2
        except Exception:
            logger.exception("Queue read error")
            time.sleep(error_backoff)
            error_backoff = min(60, error_backoff * 2)  # Exponential backoff up to 60s
            
    logger.info("Worker main loop exited. Waiting for running threads to finish...")
    _executor.shutdown(wait=True, cancel_futures=False)
    logger.info("Shutdown complete.")


if __name__ == "__main__":
    main()
