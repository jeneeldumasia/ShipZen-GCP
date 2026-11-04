"""
ShipZen API Server
FastAPI service that is the sole HTTP entry point for the platform.
All state-changing operations write to PostgreSQL and enqueue to Redis.
The controller and worker drive everything asynchronously from there.

This module only assembles the app: middleware, lifespan, /metrics and
/healthz. The endpoints live in routers/, one module per area.
"""
import asyncio
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address  # noqa: F401 (tests patch it on main)

from background import cache_eviction_listener, outbox_relay
from database import get_connection, init_db
from platform_clients import _aioredis_client, _redis_client
from ratelimit import limiter
from secret_store import ensure_project_secret
from routers import admin, audit, deployments, env, github, observability, operations, projects, webhooks

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('api')


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    def _bootstrap_secrets():
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id FROM projects WHERE deleted_at IS NULL;")
                    for row in cur.fetchall():
                        ensure_project_secret(row[0])
        except Exception as err:
            logger.warning(f"Failed to bootstrap project secrets: {err}")
    asyncio.create_task(asyncio.to_thread(_bootstrap_secrets))
    task = asyncio.create_task(outbox_relay())
    evict_task = asyncio.create_task(cache_eviction_listener())
    yield
    task.cancel()
    evict_task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    await _aioredis_client.aclose()
    _redis_client.close()

app = FastAPI(
    title="ShipZen API",
    description="Internal Developer Platform — deploy any repo to Kubernetes",
    version="1.0.0",
    lifespan=lifespan,
)


app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS — allow the Next.js dev server and any deployed UI origin.
# In production, replace "*" with the actual UI domain.
_UI_ORIGINS = [os.getenv("UI_ORIGIN")] if os.getenv("UI_ORIGIN") else []
if os.getenv("ENVIRONMENT") == "development":
    _UI_ORIGINS.extend([
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ])
_UI_ORIGINS = list(filter(None, _UI_ORIGINS))

app.add_middleware(
    CORSMiddleware,
    allow_origins=_UI_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Trace-ID", "X-Request-ID"],
)


# ── Prometheus metrics ────────────────────────────────────────────────────────
# Request rate, errors and latency per route. The ServiceMonitor scraped /metrics
# but the API never served it, so the user-facing service had no golden signals.
from prometheus_client import (Counter as _PromCounter, Histogram as _PromHistogram,
                               CollectorRegistry as _PromRegistry, generate_latest as _prom_latest,
                               CONTENT_TYPE_LATEST as _PROM_CT)
from prometheus_client import multiprocess as _prom_mp

HTTP_REQUESTS = _PromCounter(
    "shipzen_api_requests_total", "API requests", ["method", "route", "status"])
HTTP_LATENCY = _PromHistogram(
    "shipzen_api_request_duration_seconds", "API request latency", ["method", "route"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0))


@app.middleware("http")
async def prometheus_middleware(request: Request, call_next):
    start = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        route = getattr(request.scope.get("route"), "path", None) or "unmatched"
        if route != "/metrics":
            HTTP_REQUESTS.labels(request.method, route, str(status_code)).inc()
            HTTP_LATENCY.labels(request.method, route).observe(time.perf_counter() - start)


@app.get("/metrics", include_in_schema=False)
def metrics(request: Request):
    # In-cluster only. Every external request arrives through Cloudflare, which
    # always sets CF-Connecting-IP; Prometheus scrapes the pod directly.
    if request.headers.get("CF-Connecting-IP"):
        raise HTTPException(status_code=404, detail="Not Found")
    if os.getenv("PROMETHEUS_MULTIPROC_DIR"):
        registry = _PromRegistry()
        _prom_mp.MultiProcessCollector(registry)
    else:
        # The registry the metrics above were created in (not prometheus_client.REGISTRY,
        # which some tests rebind).
        from prometheus_client.registry import REGISTRY as registry
    return Response(_prom_latest(registry), media_type=_PROM_CT)


@app.middleware("http")
async def trace_id_middleware(request: Request, call_next):
    """Propagates X-Trace-ID across all requests for end-to-end distributed tracing."""
    trace_id = request.headers.get("X-Trace-ID") or request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.trace_id = trace_id
    response = await call_next(request)
    response.headers["X-Trace-ID"] = trace_id
    return response


# ── Health ────────────────────────────────────────────────────────────────────


@app.get("/healthz", tags=["Health"])
@limiter.limit("100/minute")
def healthz(request: Request):
    """Liveness probe endpoint. Always returns 200."""
    return {"status": "ok"}


# Order matters only where paths overlap; it is the order the endpoints had
# when they were all in this file.
for _router in (projects.router, deployments.router, audit.router, env.router,
                github.router, webhooks.router, admin.router, observability.router, operations.router):
    app.include_router(_router)


# Names other code and the tests still import from main (they lived here
# before the routers were split out).
from auth import User, get_current_user  # noqa: E402,F401
from background import _relay_outbox_once  # noqa: E402,F401
from platform_clients import _sm_client  # noqa: E402,F401
from ratelimit import _user_id_or_ip  # noqa: E402,F401
from routers.projects import (AddMemberRequest, AnalyzeRequest, CreateProjectRequest,  # noqa: E402,F401
                              analyze_repo, create_project, delete_project, list_projects)
from routers.deployments import (CreateDeploymentRequest, create_deployment, restart_deployment,  # noqa: E402,F401
                                 stream_logs)
from routers.env import PutEnvVarRequest, PutSecretRequest, put_env_var, put_secret  # noqa: E402,F401
from routers.webhooks import github_app_webhook, github_webhook  # noqa: E402,F401
