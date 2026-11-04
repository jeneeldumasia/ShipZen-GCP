"""Admin playground: Chaos Monkey, session meter and hall of fame.

Chaos Monkey deletes one pod of a platform component (never a tenant app) and
only when that component has at least two ready replicas, so the platform keeps
serving while Kubernetes replaces it. Everything here is admin-only and audited.
"""
import datetime
import logging
import random

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from audit import log_audit_event
from auth import User, get_current_user
from database import get_connection
from platform_clients import apps_v1
from ratelimit import limiter

logger = logging.getLogger('api')
router = APIRouter()

NAMESPACE = "shipzen-system"
TARGETS = ("shipzen-api", "shipzen-ui", "shipzen-worker", "shipzen-controller")
# Approximate on-demand prices, us-central1, per node-hour (nodes only: Cloud SQL,
# load balancer and disks are extra). The zonal cluster fee is covered by GKE's free tier.
NODE_PRICES = {"e2-medium": 0.0335, "e2-standard-2": 0.0670, "e2-standard-4": 0.1340, "e2-standard-8": 0.2680}
SOFT_LIMIT_HOURS = 9    # .github/workflows/auto-destroy.yaml: torn down when idle after this
HARD_CAP_HOURS = 12     # ...and always after this


def _admin(user: User) -> None:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")


def _core():
    from kubernetes import client as k8s
    return k8s.CoreV1Api()


def platform_status() -> list[dict]:
    out = []
    for name in TARGETS:
        try:
            d = apps_v1.read_namespaced_deployment(name=name, namespace=NAMESPACE)
            out.append({"name": name, "desired": d.spec.replicas or 0,
                        "ready": d.status.ready_replicas or 0})
        except Exception as e:
            logger.warning(f"playground: reading {name} failed: {type(e).__name__}")
            out.append({"name": name, "desired": 0, "ready": 0})
    return out


def session_meter(now: datetime.datetime = None) -> dict:
    now = now or datetime.datetime.now(datetime.timezone.utc)
    core = _core()
    started = core.read_namespace("kube-system").metadata.creation_timestamp
    nodes = []
    hourly = 0.0
    for n in core.list_node().items:
        labels = n.metadata.labels or {}
        machine = labels.get("node.kubernetes.io/instance-type", "unknown")
        price = NODE_PRICES.get(machine, 0.0)
        hourly += price
        nodes.append({"name": n.metadata.name, "pool": labels.get("cloud.google.com/gke-nodepool"),
                      "machine": machine, "hourly_usd": price})
    uptime_h = max((now - started).total_seconds() / 3600, 0)
    return {
        "cluster_started_at": started.isoformat(),
        "uptime_hours": round(uptime_h, 2),
        "nodes": nodes,
        "hourly_usd": round(hourly, 4),
        # Rough: today's node count over the whole uptime (autoscaling varies it).
        "session_usd_estimate": round(hourly * uptime_h, 2),
        "soft_limit_hours": SOFT_LIMIT_HOURS,
        "hard_cap_hours": HARD_CAP_HOURS,
        "hours_to_hard_cap": round(max(HARD_CAP_HOURS - uptime_h, 0), 2),
    }


def hall_of_fame() -> dict:
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Deploy requested -> image built (builds rows are written when a build ends).
            cur.execute("""
                SELECT p.name, EXTRACT(EPOCH FROM (b.started_at - d.created_at))::int AS secs
                FROM builds b JOIN deployments d ON d.deployment_id = b.deployment_id
                JOIN projects p ON p.id = d.project_id
                WHERE b.status = 'Success' AND b.started_at > d.created_at
                ORDER BY secs ASC LIMIT 1;""")
            fastest = cur.fetchone()
            cur.execute("SELECT count(*) FROM deployments WHERE created_at >= date_trunc('day', NOW());")
            today = cur.fetchone()[0]
            cur.execute("""
                SELECT count(*) FILTER (WHERE state IN ('Running', 'Superseded')),
                       count(*) FILTER (WHERE state IN ('Running', 'Superseded', 'Failed', 'DLQ'))
                FROM deployments WHERE created_at >= NOW() - INTERVAL '7 days';""")
            ok, done = cur.fetchone()
            cur.execute("""
                SELECT p.name, count(*) FROM deployments d JOIN projects p ON p.id = d.project_id
                WHERE d.created_at >= date_trunc('month', NOW())
                GROUP BY p.name ORDER BY count(*) DESC, p.name LIMIT 3;""")
            top = cur.fetchall()
    return {
        "fastest_build": {"project": fastest[0], "seconds": fastest[1]} if fastest else None,
        "deploys_today": today,
        "success_rate_7d": round(100 * ok / done) if done else None,
        "top_projects_month": [{"project": n, "deploys": c} for n, c in top],
    }


@router.get("/admin/playground", tags=["Admin"])
@limiter.limit("60/minute")
def playground(request: Request, current_user: User = Depends(get_current_user)):
    """Platform pod health, the session meter and the hall of fame."""
    _admin(current_user)
    try:
        session = session_meter()
    except Exception as e:
        logger.warning(f"playground: session meter failed: {type(e).__name__}")
        session = None
    return {"platform": platform_status(), "session": session, "records": hall_of_fame()}


class ChaosRequest(BaseModel):
    target: str = "random"


@router.post("/admin/chaos", tags=["Admin"])
@limiter.limit("3/minute")
def chaos_monkey(request: Request, body: ChaosRequest, current_user: User = Depends(get_current_user)):
    """Delete one pod of a platform component and let Kubernetes heal it."""
    _admin(current_user)
    healthy = [s["name"] for s in platform_status() if s["ready"] >= 2]
    if body.target == "random":
        if not healthy:
            raise HTTPException(status_code=409, detail="Nothing has a spare replica right now. Try again shortly.")
        target = random.choice(healthy)
    elif body.target in TARGETS:
        if body.target not in healthy:
            raise HTTPException(status_code=409,
                                detail=f"{body.target} has fewer than 2 ready replicas; not touching it.")
        target = body.target
    else:
        raise HTTPException(status_code=422, detail=f"target must be random or one of {', '.join(TARGETS)}")

    core = _core()
    pods = [p for p in core.list_namespaced_pod(NAMESPACE, label_selector=f"app={target}").items
            if p.status.phase == "Running" and not p.metadata.deletion_timestamp]
    if not pods:
        raise HTTPException(status_code=409, detail=f"No running {target} pod found.")
    victim = random.choice(pods).metadata.name
    core.delete_namespaced_pod(victim, NAMESPACE)
    log_audit_event(project_id=None, user_id=current_user.user_id, action="CHAOS_MONKEY",
                    resource_type="pod", resource_id=victim, details={"deployment": target})
    return {"deployment": target, "pod": victim,
            "killed_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
