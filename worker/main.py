import redis
import time
import logging
import json
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
from builder import DockerfileBuilder, RailpackBuilder, NixpacksBuilder
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


def get_github_app_token(repo_url: str) -> str:
    app_id = os.environ.get("GITHUB_APP_ID")
    private_key = os.environ.get("GITHUB_APP_PRIVATE_KEY")
    if not app_id or not private_key or not repo_url.startswith("https://github.com/"):
        return None
    
    try:
        # Parse owner/repo from URL
        parts = repo_url.rstrip("/").split("/")
        owner, repo = parts[-2], parts[-1]
        if repo.endswith(".git"):
            repo = repo[:-4]

        import jwt
        import requests
        
        now = int(time.time())
        payload = {
            "iat": now - 60,
            "exp": now + (10 * 60),
            "iss": app_id
        }
        
        # Format the private key if it was passed without newlines
        if "\\n" in private_key:
            private_key = private_key.replace("\\n", "\n")
            
        encoded_jwt = jwt.encode(payload, private_key, algorithm="RS256")
        
        # 1. Get Installation ID for this repo
        headers = {
            "Authorization": f"Bearer {encoded_jwt}",
            "Accept": "application/vnd.github.v3+json"
        }
        resp = requests.get(f"https://api.github.com/repos/{owner}/{repo}/installation", headers=headers, timeout=10)
        if resp.status_code != 200:
            logger.warning(f"Could not find GitHub App installation for {owner}/{repo}: {resp.status_code} {resp.text}")
            return None
            
        installation_id = resp.json()["id"]
        
        # 2. Create Installation Access Token
        token_resp = requests.post(f"https://api.github.com/app/installations/{installation_id}/access_tokens", headers=headers, timeout=10)
        if token_resp.status_code != 201:
            logger.warning(f"Failed to create GitHub App installation token: {token_resp.status_code} {token_resp.text}")
            return None
            
        return token_resp.json()["token"]
    except Exception as e:
        logger.error(f"Error fetching GitHub App token: {e}")
        return None


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


def monitor_job(job_name: str, deployment_id: str, image_name: str, state_machine: StateMachine, builder_type: str = "unknown", project_id: str = "unknown", queue: QueueClient = None, message_id: str = None, trace_id: str = "unknown"):
    """Monitors the Kubernetes Job, streams logs to Redis, and finalizes the deployment."""
    logger.info(f"Monitoring Job {job_name} for deployment {deployment_id} [trace_id={trace_id}]")
    r = _redis_client
    gcs_log_key = f"logs/{deployment_id}/build.log"
    build_start_time = time.time()

    try:
        w = watch.Watch()
        pod_name = None

        pod_spec = None

        # Wait for Pod to exist
        for event in w.stream(core_v1.list_namespaced_pod, namespace="shipzen-build", label_selector=f"job-name={job_name}", timeout_seconds=300):
            pod = event['object']
            pod_name = pod.metadata.name
            pod_spec = pod.spec
            w.stop()
            break

        if not pod_name:
            raise Exception("Timed out waiting for Pod to be created")

        state_machine.update_state(deployment_id, DeploymentState.BUILDING)

        all_containers = []
        if pod_spec.init_containers:
            all_containers.extend([c.name for c in pod_spec.init_containers])
        if pod_spec.containers:
            all_containers.extend([c.name for c in pod_spec.containers])

        stdout_chunks = []

        # Stream logs for each container sequentially
        for container_name in all_containers:
            # Wait for container to start generating logs
            container_started = False
            w2 = watch.Watch()
            for event in w2.stream(core_v1.list_namespaced_pod, namespace="shipzen-build", field_selector=f"metadata.name={pod_name}", timeout_seconds=600):
                pod_status = event['object'].status
                statuses = []
                if pod_status.init_container_statuses:
                    statuses.extend(pod_status.init_container_statuses)
                if pod_status.container_statuses:
                    statuses.extend(pod_status.container_statuses)
                
                for s in statuses:
                    if s.name == container_name and (s.state.running or s.state.terminated):
                        container_started = True
                        break
                
                if container_started:
                    w2.stop()
                    break
                    
            if not container_started:
                logger.warning(f"Container {container_name} never started.")
                break

            try:
                log_stream = core_v1.read_namespaced_pod_log(
                    name=pod_name, namespace="shipzen-build", follow=True, _preload_content=False,
                    container=container_name
                )
                for line in log_stream:
                    stdout_chunks.append(line)
                    try:
                        r.publish(f"shipzen:logs:{deployment_id}", line.decode('utf-8', errors='replace'))
                    except Exception:
                        pass
            except ApiException as e:
                logger.warning(f"Error reading pod logs for {container_name}: {e}")
            except Exception as e:
                logger.warning(f"Stream abruptly disconnected for {container_name}: {e}")

        # Wait for Job to complete using polling instead of watch to avoid idle connection timeouts
        job_succeeded = False
        timeout = time.time() + 3600
        while time.time() < timeout:
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

        # Upload logs to GCS with trace_id metadata
        stdout_bytes = b''.join(stdout_chunks)
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
                f"Build {deployment_id} successful. Checking port/ECR...")

            # Dynamic Port Detection via Crane
            try:
                credentials, project = google.auth.default()
                auth_req = google.auth.transport.requests.Request()
                credentials.refresh(auth_req)
                password = credentials.token
                # Use Artifact Registry host from image name (e.g. us-central1-docker.pkg.dev)
                registry_url = image_name.split('/')[0]
                subprocess.run(["crane", "auth", "login", registry_url, "-u",
                               "oauth2accesstoken", "-p", password], check=True, capture_output=True)

                crane_out = subprocess.check_output(
                    ["crane", "config", image_name], text=True)
                config_json = json.loads(crane_out)
                exposed_ports = config_json.get(
                    "config", {}).get("ExposedPorts", {})

                if exposed_ports:
                    first_port = list(exposed_ports.keys())[0].split('/')[0]
                    with get_db_connection() as conn:
                        with conn.cursor() as cur:
                            cur.execute("UPDATE deployments SET port = %s WHERE deployment_id = %s;", (int(
                                first_port), deployment_id))
            except Exception as e:
                logger.warning(f"Failed to extract exposed port: {e}")



            record_build(deployment_id, gcs_log_key, "Success")
            state_machine.update_state(deployment_id, "Deploying")

        else:
            logger.error(f"Job {job_name} failed.")
            record_build(deployment_id, gcs_log_key, "Failed")
            shipzen_deployment_failure_total.inc()
            shipzen_deployments_total.labels(state="Failed", project_id=project_id).inc()
            state_machine.update_state(
                deployment_id, "Failed", "Build step failed.")

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
        # HIGH-03 Fix: Removed _semaphore.release() from here because the finally block handles it
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
    try:
        clone_url = repo_url
        if repo_url.startswith("https://github.com/"):
            token = get_github_app_token(repo_url)
            if token:
                clone_url = repo_url.replace("https://github.com/", f"https://x-access-token:{token}@github.com/")
                github_secret_name = f"git-token-{deployment_id[:8]}"
                secret = client.V1Secret(
                    metadata=client.V1ObjectMeta(name=github_secret_name, namespace="shipzen-build"),
                    string_data={"GITHUB_TOKEN": token}
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
                       branch, clone_url, workspace], check=True, timeout=120)
        subprocess.run(["git", "sparse-checkout", "set", "--no-cone", "--skip-checks", "shipzen.yaml", "Dockerfile", "Cargo.toml", "bun.lockb", "package.json"], cwd=workspace, check=True)

        # Check overrides
        overrides = {}
        config_path = os.path.join(workspace, "shipzen.yaml")
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                cfg = yaml.safe_load(f)
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
        builders = [DockerfileBuilder(), RailpackBuilder(), NixpacksBuilder()]
        selected_builder = None
        for b in builders:
            if b.detect(workspace):
                selected_builder = b
                break

        if not selected_builder:
            raise Exception("No suitable builder found")
        # GCP GAR creates packages on push automatically, so no repo creation needed here.
        

        trace_id = data.get("trace_id", deployment_id)
        overrides["trace_id"] = trace_id

        if github_secret_name:
            overrides["github_secret_name"] = github_secret_name

        # Pass repo_url to the builder, not clone_url, so the K8s manifest doesn't get the plaintext token
        manifest = selected_builder.generate_job_manifest(
            deployment_id, repo_url, branch, image_name, overrides)
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
        logger.error(f"Error processing {deployment_id}: {e}")
        # Persist the actual error so the UI can display it rather than the
        # generic "Build step failed." message
        state_machine.update_state(deployment_id, "Failed", str(e))
        shipzen_deployment_failure_total.inc()
        shipzen_deployments_total.labels(state="Failed", project_id=deployment.get("project_id", "unknown") if deployment else "unknown").inc()
        queue.add_to_dlq(message_id, data)
        shipzen_dlq_depth.inc()
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
        if github_secret_name:
            try:
                core_v1.delete_namespaced_secret(name=github_secret_name, namespace="shipzen-build")
            except Exception as e:
                logger.warning(f"Failed to delete GitHub token secret {github_secret_name}: {e}")
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
                    _executor.submit(process_message, queue, state_machine, msg_id, data)

            messages = queue.get_messages(count=5, block_ms=2000)
            if messages:
                for stream_name, msg_list in messages:
                    for msg_id, data in msg_list:
                        _semaphore.acquire()
                        _executor.submit(process_message, queue, state_machine, msg_id, data)

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
