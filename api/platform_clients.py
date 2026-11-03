"""Clients for the services the API talks to, created once per process.

Redis (queue + pub/sub), Secret Manager, GCS (build logs) and the Kubernetes
apps API, plus the settings they need.
"""
import logging
import os

import redis as redis_lib
import redis.asyncio as aioredis
from google.cloud import secretmanager
from google.cloud import storage as gcs_storage
from kubernetes import client, config as k8s_config

logger = logging.getLogger('api')

try:
    k8s_config.load_incluster_config()
except Exception:
    pass
apps_v1 = client.AppsV1Api()

# ── Config ────────────────────────────────────────────────────────────────────

REDIS_HOST = os.getenv(
    "REDIS_HOST", "redis-master.shipzen-system.svc.cluster.local")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
STREAM_NAME = os.getenv("STREAM_NAME", "deploy_stream")

# GAR registry URL — injected by Terraform at deploy time.
# The API constructs the full image URI as: <GAR_REGISTRY_URL>/<project_id>:<deployment_id>
# Users never see or input this value.
GAR_REGISTRY_URL = os.getenv("GAR_REGISTRY_URL", "")

# PERF-01 Fix: Module-level GCP Secret Manager client singleton
try:
    _sm_client = secretmanager.SecretManagerServiceClient()
except Exception:
    _sm_client = None
# H-6 Fix: Module-level GCS client singleton — avoids per-request connection overhead
try:
    _gcs_client = gcs_storage.Client()
except Exception:
    _gcs_client = None
GCP_PROJECT = os.getenv('GCP_PROJECT', '')

REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")

_redis_pool = redis_lib.ConnectionPool(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD, decode_responses=True)
_redis_client = redis_lib.Redis(connection_pool=_redis_pool)
_aioredis_client = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD, decode_responses=True)
def get_redis() -> redis_lib.Redis:
    return _redis_client
