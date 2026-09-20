import os
import time
import logging
import yaml
import psycopg2
import datetime
import queue
import threading
import signal
import sys
import json
import socket
from psycopg2.extras import DictCursor
from psycopg2.pool import ThreadedConnectionPool
from jinja2 import Environment, FileSystemLoader
from kubernetes import client, config as k8s_config
from kubernetes.client.rest import ApiException
from kubernetes.client.models import V1Lease, V1LeaseSpec, V1ObjectMeta
from kubernetes.utils import create_from_yaml

import redis
from models import ProjectStatus, ProjectSchema
from metrics import (
    shipzen_drift_total,
    shipzen_reconciliation_duration_seconds,
    shipzen_deployment_success_total,
    shipzen_active_deployments,
    start_metrics_server
)

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('controller')

try:
    k8s_config.load_incluster_config()
except k8s_config.ConfigException:
    k8s_config.load_kube_config()

k8s_client = client.ApiClient()
k8s_core_api = client.CoreV1Api()
k8s_apps_api = client.AppsV1Api()
k8s_custom_api = client.CustomObjectsApi()
k8s_coordination_api = client.CoordinationV1Api()

# Leader Election Implementation using Kubernetes Lease coordination.k8s.io
class LeaderElector:
    def __init__(self, lease_name="shipzen-controller-leader", lease_namespace="shipzen-system", lease_duration=15, renew_deadline=10):
        self.lease_name = lease_name
        self.lease_namespace = os.getenv("POD_NAMESPACE", lease_namespace)
        self.holder_identity = os.getenv("POD_NAME", socket.gethostname())
        self.lease_duration = lease_duration
        self.renew_deadline = renew_deadline
        self.is_leader = False

    def try_acquire_or_renew(self) -> bool:
        now = datetime.datetime.now(datetime.timezone.utc)
        try:
            lease = k8s_coordination_api.read_namespaced_lease(name=self.lease_name, namespace=self.lease_namespace)
            spec = lease.spec
            if spec.holder_identity == self.holder_identity:
                spec.renew_time = now
                spec.lease_duration_seconds = self.lease_duration
                k8s_coordination_api.replace_namespaced_lease(name=self.lease_name, namespace=self.lease_namespace, body=lease)
                self.is_leader = True
                return True
            else:
                renew_time = spec.renew_time or spec.acquire_time
                if renew_time:
                    if renew_time.tzinfo is None:
                        renew_time = renew_time.replace(tzinfo=datetime.timezone.utc)
                    age = (now - renew_time).total_seconds()
                    if age > (spec.lease_duration_seconds or self.lease_duration):
                        logger.info(f"Lease {self.lease_name} expired ({age:.1f}s old). Taking over leadership as {self.holder_identity} from {spec.holder_identity}.")
                        spec.holder_identity = self.holder_identity
                        spec.acquire_time = now
                        spec.renew_time = now
                        spec.lease_duration_seconds = self.lease_duration
                        spec.lease_transitions = (spec.lease_transitions or 0) + 1
                        k8s_coordination_api.replace_namespaced_lease(name=self.lease_name, namespace=self.lease_namespace, body=lease)
                        self.is_leader = True
                        return True
                self.is_leader = False
                return False
        except ApiException as e:
            if e.status == 404:
                new_lease = V1Lease(
                    metadata=V1ObjectMeta(name=self.lease_name, namespace=self.lease_namespace),
                    spec=V1LeaseSpec(
                        holder_identity=self.holder_identity,
                        lease_duration_seconds=self.lease_duration,
                        acquire_time=now,
                        renew_time=now,
                        lease_transitions=1
                    )
                )
                try:
                    k8s_coordination_api.create_namespaced_lease(namespace=self.lease_namespace, body=new_lease)
                    logger.info(f"Acquired new leader lease {self.lease_name} as {self.holder_identity}")
                    self.is_leader = True
                    return True
                except ApiException:
                    self.is_leader = False
                    return False
            else:
                logger.warning(f"Error accessing lease {self.lease_name}: {e}")
                self.is_leader = False
                return False
        except Exception as e:
            logger.warning(f"Unexpected error during leader election: {e}")
            self.is_leader = False
            return False

    def release(self):
        if self.is_leader:
            try:
                lease = k8s_coordination_api.read_namespaced_lease(name=self.lease_name, namespace=self.lease_namespace)
                if lease.spec.holder_identity == self.holder_identity:
                    lease.spec.holder_identity = None
                    k8s_coordination_api.replace_namespaced_lease(name=self.lease_name, namespace=self.lease_namespace, body=lease)
                    logger.info(f"Successfully released leader lease {self.lease_name}")
            except Exception as e:
                logger.warning(f"Failed to release lease cleanly: {e}")
        self.is_leader = False


# Workqueue for event-driven reconciliations
_work_queue = queue.Queue()

def event_listener_loop():
    """Subscribes to Redis state change events and enqueues project IDs for instant reconciliation."""
    while True:
        try:
            pubsub = _redis_client.pubsub()
            pubsub.subscribe("shipzen:events:project_reconcile")
            logger.info("Event listener subscribed to 'shipzen:events:project_reconcile'")
            for msg in pubsub.listen():
                if msg["type"] == "message":
                    try:
                        data = json.loads(msg["data"])
                        project_id = data.get("project_id")
                        if project_id:
                            logger.info(f"Event received for project {project_id} -> enqueued for immediate reconciliation")
                            _work_queue.put(project_id)
                    except Exception as parse_e:
                        logger.warning(f"Failed to parse event message: {parse_e}")
        except Exception as conn_e:
            logger.warning(f"Redis event listener connection error: {conn_e}, reconnecting in 5s...")
            time.sleep(5)

# Fix #20: raise if env var is missing rather than silently falling back to
# a hardcoded plaintext credential that will never work in-cluster.
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set")

RECONCILIATION_INTERVAL = int(os.getenv("RECONCILIATION_INTERVAL", "15"))

# GCP Artifact Registry hostname — used when rendering the tenant namespace template
# so each tenant namespace gets an Artifact Registry pull secret via ESO.
# Format: us-central1-docker.pkg.dev/PROJECT_ID/REPO_ID
GAR_REGISTRY = os.getenv("GAR_REGISTRY", "")
GCP_PROJECT = os.getenv("GCP_PROJECT", "")
GCP_REGION = os.getenv("GCP_REGION", "us-central1")

REDIS_HOST = os.getenv("REDIS_HOST", "redis-master.shipzen-system.svc.cluster.local")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")

# Module-level Redis singleton — created once, reused across all reconcile ticks.
_redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD, decode_responses=True)

jinja_env = Environment(loader=FileSystemLoader("templates"))

# H-8 Fix: Module-level declaration — avoids lazy globals() check on every reconcile tick.
# Keys are project IDs; values are consecutive failure counts.
# Entries for terminated projects are pruned during each full reconcile sweep.
_project_failures: dict = {}


def ensure_gar_repository(project_id: str):
    # GCP Artifact Registry handles package creation automatically on push
    pass

def delete_gar_repository(project_id: str):
    # TODO: Implement GAR package deletion if needed for cleanup
    # Currently a no-op for GCP migration
    pass


db_pool = None
_db_pool_lock = threading.Lock()

def get_db_connection():
    global db_pool
    if db_pool is None:
        with _db_pool_lock:
            if db_pool is None:  # Re-check after acquiring lock
                db_pool = ThreadedConnectionPool(1, 30, DATABASE_URL)
    conn = db_pool.getconn()
    conn.autocommit = False
    return conn

def close_db_connection(conn):
    if db_pool:
        db_pool.putconn(conn)
    else:
        conn.close()


def _wait_for_schema(max_attempts: int = 30, delay: int = 10):
    """
    Block until the schema bootstrap Job has run and the projects table exists.
    On a fresh cluster the Job runs as an ArgoCD PostSync hook — this can take
    30-60s after the controller pod starts. Without this guard the controller
    would crash-loop with 'relation "projects" does not exist'.
    """
    for attempt in range(1, max_attempts + 1):
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM projects LIMIT 1;")
            logger.info("Database schema is ready.")
            return
        except psycopg2.OperationalError as e:
            logger.warning(
                f"DB not reachable yet (attempt {attempt}/{max_attempts}): {e}")
        except psycopg2.errors.UndefinedTable:
            logger.warning(
                f"Schema not ready yet (attempt {attempt}/{max_attempts}), waiting {delay}s...")
        except Exception as e:
            logger.warning(
                f"Unexpected DB error (attempt {attempt}/{max_attempts}): {e}")
        finally:
            if conn is not None:
                try:
                    close_db_connection(conn)
                except Exception:
                    pass
        time.sleep(delay)
    raise RuntimeError(
        f"Database schema not ready after {max_attempts * delay}s — aborting")


def apply_manifests(manifest_str: str):
    """
    Parses the multi-document YAML and applies each document via the
    kubernetes Python client. If the resource already exists, it is patched.
    """
    logger.info("Applying K8s manifests via Python client...")
    docs = list(yaml.safe_load_all(manifest_str))
    for doc in docs:
        if doc is None:
            continue

        kind = doc.get("kind")
        name = doc.get("metadata", {}).get("name")
        namespace = doc.get("metadata", {}).get("namespace", "default")

        try:
            if kind == "HTTPRoute":
                k8s_custom_api.create_namespaced_custom_object(
                    "gateway.networking.k8s.io", "v1", namespace, "httproutes", doc)
                logger.info(f"Applied: {kind} / {name}")
                continue
            elif kind == "ExternalSecret":
                k8s_custom_api.create_namespaced_custom_object(
                    "external-secrets.io", "v1beta1", namespace, "externalsecrets", doc)
                logger.info(f"Applied: {kind} / {name}")
                continue

            create_from_yaml(k8s_client, yaml_objects=[doc], verbose=False)
            logger.info(f"Applied: {kind} / {name}")
        except ApiException as e:
            if e.status == 409:
                try:
                    if kind == "Deployment":
                        k8s_apps_api.patch_namespaced_deployment(
                            name, namespace, doc)
                    elif kind == "Service":
                        k8s_core_api.patch_namespaced_service(
                            name, namespace, doc)
                    elif kind == "HTTPRoute":
                        k8s_custom_api.patch_namespaced_custom_object(
                            "gateway.networking.k8s.io", "v1", namespace, "httproutes", name, doc)
                    elif kind == "ExternalSecret":
                        k8s_custom_api.patch_namespaced_custom_object(
                            "external-secrets.io", "v1beta1", namespace, "externalsecrets", name, doc)
                    elif kind == "PodDisruptionBudget":
                        client.PolicyV1Api().patch_namespaced_pod_disruption_budget(name, namespace, doc)
                    elif kind == "NetworkPolicy":
                        client.NetworkingV1Api().patch_namespaced_network_policy(name, namespace, doc)
                    elif kind == "ResourceQuota":
                        k8s_core_api.patch_namespaced_resource_quota(
                            name, namespace, doc)
                    elif kind == "LimitRange":
                        k8s_core_api.patch_namespaced_limit_range(
                            name, namespace, doc)
                    elif kind == "Role":
                        client.RbacAuthorizationV1Api().patch_namespaced_role(name, namespace, doc)
                    elif kind == "RoleBinding":
                        client.RbacAuthorizationV1Api().patch_namespaced_role_binding(name, namespace, doc)
                    else:
                        logger.warning(f"Patching not implemented for {kind}")
                        continue
                    logger.info(f"Patched: {kind} / {name}")
                except Exception as patch_e:
                    logger.error(f"Failed to patch {kind} {name}: {patch_e}")
            else:
                logger.warning(f"apply_manifests API error for {kind}: {e}")
        except Exception as e:
            logger.warning(f"apply_manifests error for {kind}: {e}")


def check_namespace_exists(namespace: str) -> bool:
    try:
        k8s_core_api.read_namespace(name=namespace)
        return True
    except ApiException as e:
        if e.status == 404:
            return False
        raise


def delete_namespace(namespace: str):
    try:
        k8s_core_api.delete_namespace(name=namespace)
    except ApiException as e:
        if e.status != 404:
            raise


@shipzen_reconciliation_duration_seconds.time()
def reconcile():
    logger.info("Starting reconciliation loop...")
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            # Sweeper: Fail deployments stuck in Queued or Building for over an hour
            cur.execute("""
                UPDATE deployments 
                SET state = 'Failed', last_error = 'Deployment timed out in Queued/Building state' 
                WHERE state IN ('Queued', 'Building') 
                AND updated_at < NOW() - INTERVAL '60 minutes';
            """)
            conn.commit()

            # HIGH-08 Fix: Filter out terminated projects to prevent loop slowdown
            cur.execute("SELECT * FROM projects WHERE status != 'Terminated';")
            projects = [dict(row) for row in cur.fetchall()]
    finally:
        close_db_connection(conn)

    # 1. Fetch Global Kubernetes State (O(1) API calls instead of O(N))
    global_deps = {}
    global_svcs = {}
    global_routes = {}
    try:
        _continue = None
        while True:
            all_deps = k8s_apps_api.list_deployment_for_all_namespaces(_continue=_continue)
            for d in all_deps.items:
                global_deps.setdefault(d.metadata.namespace, {})[d.metadata.name] = d
            _continue = all_deps.metadata._continue
            if not _continue:
                break

        _continue = None
        while True:
            all_svcs = k8s_core_api.list_service_for_all_namespaces(_continue=_continue)
            for s in all_svcs.items:
                global_svcs.setdefault(s.metadata.namespace, set()).add(s.metadata.name)
            _continue = all_svcs.metadata._continue
            if not _continue:
                break

        try:
            _continue = None
            while True:
                all_routes = k8s_custom_api.list_cluster_custom_object(
                    "gateway.networking.k8s.io", "v1", "httproutes", _continue=_continue)
                for r in all_routes.get("items", []):
                    global_routes.setdefault(r['metadata']['namespace'], set()).add(r['metadata']['name'])
                _continue = all_routes.get("metadata", {}).get("continue")
                if not _continue:
                    break
        except ApiException:
            pass

        global_ext_secrets = {}
        try:
            _continue = None
            while True:
                all_secrets = k8s_custom_api.list_cluster_custom_object(
                    "external-secrets.io", "v1beta1", "externalsecrets", _continue=_continue)
                for r in all_secrets.get("items", []):
                    global_ext_secrets.setdefault(r['metadata']['namespace'], set()).add(r['metadata']['name'])
                _continue = all_secrets.get("metadata", {}).get("continue")
                if not _continue:
                    break
        except ApiException:
            pass

    except Exception as e:
        logger.error(f"Failed to fetch global K8s state: {e}")
        return

    # Prune _project_failures entries for projects no longer in the active set
    # to prevent unbounded memory growth over time (H-8 fix).
    active_ids = {row['id'] for row in projects}
    stale_keys = [k for k in _project_failures if k not in active_ids]
    for k in stale_keys:
        del _project_failures[k]

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = {}
        for row in projects:
            p_id = row['id']
            if _project_failures.get(p_id, 0) >= 3:
                logger.warning(f"Skipping project {p_id} due to {_project_failures[p_id]} consecutive failures")
                continue
            futures[executor.submit(_reconcile_project, dict(row), global_deps, global_svcs, global_routes, global_ext_secrets)] = p_id

        for future in concurrent.futures.as_completed(futures):
            p_id = futures[future]
            try:
                future.result()
                _project_failures[p_id] = 0
            except Exception as e:
                _project_failures[p_id] = _project_failures.get(p_id, 0) + 1
                logger.error(f"Project {p_id} failed reconciliation: {e}")


def _reconcile_project(project_data: dict, global_deps: dict, global_svcs: dict, global_routes: dict, global_ext_secrets: dict):
    project_data["_id"] = project_data.pop("id")

    # Per-project connection — failure here cannot affect other projects
    project_conn = get_db_connection()
    try:
        project = ProjectSchema(**project_data)

        with project_conn.cursor(cursor_factory=DictCursor) as project_cur:
            if project.status == ProjectStatus.PROVISIONING:
                logger.info(
                    f"Provisioning project: {project.name} ({project.namespace})")
                template = jinja_env.get_template("tenant.yaml.j2")
                manifests = template.render(
                    namespace=project.namespace,
                    project_id=project.id,
                    gar_registry=GAR_REGISTRY,
                    gcp_project=GCP_PROJECT,
                )
                apply_manifests(manifests)

                if check_namespace_exists(project.namespace):
                    ensure_gar_repository(project.id)
                    project_cur.execute(
                        "UPDATE projects SET status = %s WHERE id = %s;",
                        (ProjectStatus.READY.value, project.id)
                    )
                    project_conn.commit()
                    logger.info(
                        f"Project {project.name} provisioned and Ready.")
                else:
                    project_conn.rollback()
                    logger.info(
                        f"Namespace {project.namespace} not yet visible; will retry.")

            elif project.status == ProjectStatus.TERMINATING:
                logger.info(
                    f"Terminating project: {project.name} ({project.namespace})")
                if check_namespace_exists(project.namespace):
                    delete_namespace(project.namespace)
                    logger.info(
                        f"Namespace {project.namespace} deletion triggered.")
                    project_conn.commit()
                else:
                    delete_gar_repository(project.id)
                    # HIGH-08 Fix: Update status to Terminated instead of hard-deleting the row
                    # to preserve audit log foreign keys and history
                    project_cur.execute(
                        "UPDATE projects SET status = 'Terminated' WHERE id = %s;", (project.id,))
                    project_conn.commit()
                    logger.info(
                        f"Project {project.name} permanently cleaned up.")

            elif project.status == ProjectStatus.READY:
                if not check_namespace_exists(project.namespace):
                    shipzen_drift_total.inc()
                    logger.warning(
                        f"Drift detected! Namespace {project.namespace} missing for Ready project.")
                    project_cur.execute(
                        "UPDATE projects SET status = %s WHERE id = %s;",
                        (ProjectStatus.PROVISIONING.value, project.id)
                    )
                    project_conn.commit()
                else:
                    reconcile_deployments(
                        project_conn, project_cur, project, global_deps, global_svcs, global_routes, global_ext_secrets)

    except Exception as e:
        # HIGH-02 Fix: Use project_data['_id'] since 'id' was popped
        logger.error(f"Error reconciling project {project_data['_id']}: {e}")
        try:
            # Fix 3: Re-use project_conn to set FAILED state and avoid Connection Pool Exhaustion Deadlock
            with project_conn.cursor() as err_cur:
                err_cur.execute(
                    "UPDATE projects SET status = %s WHERE id = %s;",
                    (ProjectStatus.FAILED.value, project_data['_id'])
                )
            project_conn.commit()
        except Exception as rb_err:
            logger.error(f"Failed to set FAILED state: {rb_err}")
    finally:
        close_db_connection(project_conn)


def reconcile_deployments(conn, cur, project, global_deps, global_svcs, global_routes, global_ext_secrets):
    """Reconciles Deployments, Services, and HTTPRoutes for a ready project namespace."""
    cur.execute("SELECT * FROM deployments WHERE project_id = %s;",
                (project.id,))
    db_deployments = {str(row['deployment_id']): dict(row)
                      for row in cur.fetchall()}

    try:
        k8s_dep_names = global_deps.get(project.namespace, {})
        k8s_svc_names = global_svcs.get(project.namespace, set())
        k8s_route_names = global_routes.get(project.namespace, set())

        k8s_ext_secret_names = global_ext_secrets.get(project.namespace, set())

        # 1. Missing or Drifted Deployments
        for d_id, db_dep in db_deployments.items():
            if db_dep['state'] in ['Running', 'Verifying', 'Deploying']:
                k8s_dep = k8s_dep_names.get(d_id)
                drifted = False
                
                if k8s_dep:
                    # Check for deep configuration drift
                    k8s_replicas = k8s_dep.spec.replicas if k8s_dep.spec.replicas is not None else 1
                    db_replicas = db_dep.get('replicas', 1)
                    k8s_image = k8s_dep.spec.template.spec.containers[0].image if k8s_dep.spec.template.spec.containers else None
                    if k8s_replicas != db_replicas or k8s_image != db_dep.get('image_uri'):
                        drifted = True
                
                # Handle deployments without a Kubernetes Deployment
                if not k8s_dep:
                    if db_dep['state'] in ("Building", "Queued", "Verifying", "Failed"):
                        continue
                    # HIGH-23 Fix: If state is Deploying or Running but no K8s Deployment exists, drift reconciliation below will create it.

                missing_resources = (
                    not k8s_dep or
                    f"{d_id}-svc" not in k8s_svc_names or
                    f"{d_id}-route" not in k8s_route_names or
                    f"{d_id}-secrets" not in k8s_ext_secret_names
                )
                
                if missing_resources or drifted:
                    shipzen_drift_total.inc()
                    logger.warning(
                        f"Drift: Deployment {d_id} is missing or drifted in K8s. Reconciling...")
                    template = jinja_env.get_template("app-deployment.yaml.j2")
                    manifests = template.render(
                        deployment_name=d_id,
                        deployment_id=d_id,
                        namespace=project.namespace,
                        project_name=project.name,
                        image_uri=db_dep.get('image_uri', 'nginx:latest'),
                        port=db_dep.get('port', 8080),
                        replicas=db_dep.get('replicas', 1),
                        health_check_path=db_dep.get('health_check_path', '/')
                    )
                    apply_manifests(manifests)
                    
                    if not k8s_dep:
                        continue # Can't check replicas yet
                
                if k8s_dep:
                    k8s_dep = k8s_dep_names[d_id]
                    ready_replicas = k8s_dep.status.ready_replicas or 0
                    if ready_replicas == 0 and db_dep['state'] == 'Running':
                        shipzen_drift_total.inc()
                        logger.warning(
                            f"Drift: Deployment {d_id} is failing in K8s.")
                        cur.execute(
                            "UPDATE deployments SET state = %s, last_error = %s WHERE deployment_id = %s;",
                            ('Failed', 'Kubernetes Deployment Failed/CrashLoopBackOff', d_id)
                        )
                        conn.commit()
                        try:
                            _redis_client.publish(f"shipzen:status:{d_id}", json.dumps(
                                {"state": "Failed", "last_error": "Kubernetes Deployment Failed/CrashLoopBackOff"}))
                        except Exception as pub_e:
                            logger.warning(
                                f"Failed to publish to Redis: {pub_e}")
                    elif ready_replicas == 0 and db_dep['state'] in ['Deploying', 'Verifying']:
                        import datetime
                        time_since_update = (datetime.datetime.now(datetime.timezone.utc) - db_dep['updated_at'].astimezone(datetime.timezone.utc)).total_seconds()
                        if time_since_update > 300:
                            shipzen_drift_total.inc()
                            logger.warning(f"Drift: Deployment {d_id} timed out in {db_dep['state']} state.")
                            cur.execute(
                                "UPDATE deployments SET state = %s, last_error = %s WHERE deployment_id = %s;",
                                ('Failed', 'Deployment timed out / CrashLoopBackOff', d_id)
                            )
                            conn.commit()
                            try:
                                _redis_client.publish(f"shipzen:status:{d_id}", json.dumps(
                                    {"state": "Failed", "last_error": "Deployment timed out / CrashLoopBackOff"}))
                            except Exception as pub_e:
                                logger.warning(f"Failed to publish to Redis: {pub_e}")
                    elif ready_replicas > 0 and db_dep['state'] in ['Deploying', 'Verifying']:
                        logger.info(
                            f"Deployment {d_id} is now Running (Ready Replicas: {ready_replicas})")
                        cur.execute(
                            "UPDATE deployments SET state = %s, last_error = NULL WHERE deployment_id = %s;",
                            ('Running', d_id)
                        )
                        cur.execute(
                            "UPDATE deployments SET replicas = 0 WHERE project_id = %s AND deployment_id != %s AND state = 'Running' AND replicas > 0;",
                            (project.id, d_id)
                        )
                        conn.commit()
                        shipzen_deployment_success_total.inc()
                        try:
                            _redis_client.publish(f"shipzen:status:{d_id}", json.dumps(
                                {"state": "Running", "last_error": None}))
                        except Exception as pub_e:
                            logger.warning(
                                f"Failed to publish to Redis: {pub_e}")

        # 2. Orphan Resources Cleanup
        # States that indicate a live or in-flight deployment — never garbage collect these.
        _LIVE_STATES = {'Running', 'Verifying', 'Deploying', 'Queued', 'Building'}
        for k8s_name in k8s_dep_names.keys():
            if k8s_name not in db_deployments or db_deployments[k8s_name]['state'] not in _LIVE_STATES:
                shipzen_drift_total.inc()
                logger.warning(
                    f"Drift: Orphan Deployment {k8s_name} found in K8s. Cleaning up...")
                k8s_apps_api.delete_namespaced_deployment(
                    name=k8s_name, namespace=project.namespace)
                try:
                    k8s_core_api.delete_namespaced_service(
                        name=f"{k8s_name}-svc", namespace=project.namespace)
                    k8s_custom_api.delete_namespaced_custom_object(
                        group="gateway.networking.k8s.io",
                        version="v1",
                        namespace=project.namespace,
                        plural="httproutes",
                        name=f"{k8s_name}-route"
                    )
                except ApiException:
                    pass

        # 3. Update active_deployments metric
        running_count = sum(
            1 for d_id, db_dep in db_deployments.items()
            if db_dep['state'] == 'Running' and d_id in k8s_dep_names and (k8s_dep_names[d_id].status.ready_replicas or 0) > 0
        )
        shipzen_active_deployments.labels(
            namespace=project.namespace).set(running_count)

    except Exception as e:
        logger.error(f"Error reconciling deployments for {project.name}: {e}")


def reconcile_single_project_by_id(project_id: str, global_deps: dict = None, global_svcs: dict = None, global_routes: dict = None, global_ext_secrets: dict = None):
    """Targeted reconciliation for a single project triggered by real-time events."""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("SELECT * FROM projects WHERE id = %s AND status != 'Terminated';", (project_id,))
            row = cur.fetchone()
            if not row:
                return
            project_data = dict(row)
    finally:
        close_db_connection(conn)

    namespace = project_data.get("namespace", "default")
    if global_deps is None:
        global_deps = {}
        try:
            deps = k8s_apps_api.list_namespaced_deployment(namespace=namespace)
            for d in deps.items:
                global_deps.setdefault(namespace, {})[d.metadata.name] = d
        except Exception:
            pass

    if global_svcs is None:
        global_svcs = {}
        try:
            svcs = k8s_core_api.list_namespaced_service(namespace=namespace)
            for s in svcs.items:
                global_svcs.setdefault(namespace, set()).add(s.metadata.name)
        except Exception:
            pass

    if global_routes is None:
        global_routes = {}
        try:
            routes = k8s_custom_api.list_namespaced_custom_object(
                "gateway.networking.k8s.io", "v1", namespace, "httproutes")
            for r in routes.get("items", []):
                global_routes.setdefault(namespace, set()).add(r['metadata']['name'])
        except Exception:
            pass

    if global_ext_secrets is None:
        global_ext_secrets = {}
        try:
            secrets = k8s_custom_api.list_namespaced_custom_object(
                "external-secrets.io", "v1beta1", namespace, "externalsecrets")
            for r in secrets.get("items", []):
                global_ext_secrets.setdefault(namespace, set()).add(r['metadata']['name'])
        except Exception:
            pass

    _reconcile_project(project_data, global_deps, global_svcs, global_routes, global_ext_secrets)
    logger.info(f"Targeted event-driven reconciliation finished for project {project_id}")


def main():
    start_metrics_server(port=9090)
    _wait_for_schema()

    # Start event listener thread for real-time Redis pub/sub
    event_thread = threading.Thread(target=event_listener_loop, daemon=True)
    event_thread.start()

    elector = LeaderElector()

    def handle_shutdown(signum, frame):
        logger.info("Shutdown signal received. Stepping down and releasing lease...")
        elector.release()
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    last_full_reconcile = 0.0
    standby_logged = False

    logger.info("ShipZen Controller started. Entering Leader Election & Event Loop.")

    while True:
        try:
            is_leader = elector.try_acquire_or_renew()
            if is_leader:
                if standby_logged:
                    logger.info("Promoted to Leader! Running active reconciliation.")
                    standby_logged = False

                # 1. Drain immediate event-driven workqueue items
                while not _work_queue.empty():
                    try:
                        p_id = _work_queue.get_nowait()
                        reconcile_single_project_by_id(p_id)
                        _work_queue.task_done()
                    except queue.Empty:
                        break
                    except Exception as q_err:
                        logger.error(f"Error processing workqueue item {p_id}: {q_err}")

                # 2. Periodic full cluster self-healing sweep
                now = time.time()
                if now - last_full_reconcile >= RECONCILIATION_INTERVAL:
                    reconcile()
                    last_full_reconcile = time.time()
            else:
                if not standby_logged:
                    logger.info("Pod is currently in Standby (follower mode). Active leader holds lease.")
                    standby_logged = True

            time.sleep(2)
        except Exception as loop_e:
            logger.error(f"Error in controller main loop: {loop_e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
