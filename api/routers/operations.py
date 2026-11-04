"""Platform operations for admins: announcement banner, deploy freeze, user
suspension, and what the running cluster is costing right now."""
import datetime
import logging
import os
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from kubernetes import client as k8s_client
from psycopg2.extras import Json
from pydantic import BaseModel, Field

from audit import log_audit_event
from auth import User, evict_user_token_cache, get_current_user
from database import get_connection
from platform_clients import _redis_client
from ratelimit import limiter

logger = logging.getLogger('api')
router = APIRouter()


def _require_admin(user: User) -> None:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")


def _get_settings(cur, *keys) -> dict:
    cur.execute("SELECT key, value, updated_at FROM platform_settings WHERE key = ANY(%s);", (list(keys),))
    return {r[0]: {**r[1], "updated_at": r[2].isoformat()} for r in cur.fetchall()}


def _put_setting(cur, key: str, value: Optional[dict], user_id: str) -> None:
    if value is None:
        cur.execute("DELETE FROM platform_settings WHERE key = %s;", (key,))
        return
    cur.execute(
        "INSERT INTO platform_settings (key, value, updated_by, updated_at) VALUES (%s, %s, %s, NOW()) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_by = EXCLUDED.updated_by, "
        "updated_at = NOW();", (key, Json(value), user_id))


# ── Announcement and deploy freeze ───────────────────────────────────────────

@router.get("/platform/status", tags=["Platform"])
@limiter.limit("120/minute")
def platform_status(request: Request, current_user: User = Depends(get_current_user)):
    """What every signed-in user should see: the admin announcement and whether deploys are paused."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            s = _get_settings(cur, "announcement", "deploy_freeze")
    freeze = s.get("deploy_freeze") or {}
    return {
        "announcement": s.get("announcement"),
        "deploys_paused": bool(freeze.get("paused")),
        "pause_reason": freeze.get("reason") if freeze.get("paused") else None,
    }


class AnnouncementRequest(BaseModel):
    # Empty message removes the banner.
    message: str = Field("", max_length=300)
    level: Literal["info", "warning", "critical"] = "info"


@router.put("/admin/platform/announcement", tags=["Admin"])
@limiter.limit("20/minute")
def set_announcement(request: Request, body: AnnouncementRequest,
                     current_user: User = Depends(get_current_user)):
    """Show a banner to every user (or clear it with an empty message)."""
    _require_admin(current_user)
    message = body.message.strip()
    value = {"message": message, "level": body.level} if message else None
    with get_connection() as conn:
        with conn.cursor() as cur:
            _put_setting(cur, "announcement", value, current_user.user_id)
        conn.commit()
    log_audit_event(project_id=None, user_id=current_user.user_id,
                    action="SET_ANNOUNCEMENT" if value else "CLEAR_ANNOUNCEMENT",
                    resource_type="platform", resource_id="announcement", details=value or {})
    return {"announcement": value}


class DeployFreezeRequest(BaseModel):
    paused: bool
    reason: str = Field("", max_length=200)


@router.put("/admin/platform/deploy-freeze", tags=["Admin"])
@limiter.limit("20/minute")
def set_deploy_freeze(request: Request, body: DeployFreezeRequest,
                      current_user: User = Depends(get_current_user)):
    """Pause or resume new deploys platform-wide (manual, push and preview).

    Running apps and builds already in progress are not touched."""
    _require_admin(current_user)
    value = {"paused": True, "reason": body.reason.strip() or None} if body.paused else None
    with get_connection() as conn:
        with conn.cursor() as cur:
            _put_setting(cur, "deploy_freeze", value, current_user.user_id)
        conn.commit()
    log_audit_event(project_id=None, user_id=current_user.user_id,
                    action="PAUSE_DEPLOYS" if body.paused else "RESUME_DEPLOYS",
                    resource_type="platform", resource_id="deploy_freeze", details=value or {})
    return {"deploys_paused": body.paused, "pause_reason": value["reason"] if value else None}


# ── User suspension ──────────────────────────────────────────────────────────

class SuspensionRequest(BaseModel):
    suspended: bool
    reason: str = Field("", max_length=300)


@router.put("/admin/users/{user_id}/suspension", tags=["Admin"])
@limiter.limit("30/minute")
def set_user_suspension(request: Request, user_id: str, body: SuspensionRequest,
                        current_user: User = Depends(get_current_user)):
    """Suspend a user: they are signed out of the API within seconds and their
    projects can't start deploys. Their running apps keep serving. Admins can't
    be suspended (demote first), and nobody can suspend themselves."""
    _require_admin(current_user)
    if user_id == current_user.user_id:
        raise HTTPException(status_code=400, detail="You can't suspend yourself.")
    reason = body.reason.strip() or None
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT role FROM users WHERE id = %s FOR UPDATE;", (user_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="User not found")
            if body.suspended and row[0] == "admin":
                raise HTTPException(status_code=409, detail="Demote this admin before suspending them.")
            if body.suspended:
                cur.execute("UPDATE users SET suspended_at = COALESCE(suspended_at, NOW()), suspended_reason = %s "
                            "WHERE id = %s;", (reason, user_id))
            else:
                cur.execute("UPDATE users SET suspended_at = NULL, suspended_reason = NULL WHERE id = %s;",
                            (user_id,))
        conn.commit()

    # Cached sign-ins (60 s) would otherwise keep working: drop them here and on
    # the other API replicas.
    evict_user_token_cache(user_id)
    try:
        _redis_client.publish("shipzen:events:cache_evict", user_id)
    except Exception as e:
        logger.warning(f"Failed to publish cache_evict event: {e}")

    log_audit_event(project_id=None, user_id=current_user.user_id,
                    action="SUSPEND_USER" if body.suspended else "UNSUSPEND_USER",
                    resource_type="user", resource_id=user_id, details={"reason": reason} if reason else {})
    return {"user_id": user_id, "suspended": body.suspended, "reason": reason if body.suspended else None}


# ── Session cost ─────────────────────────────────────────────────────────────

# On-demand list prices (USD per hour, us-central1). Spot nodes are billed
# much less; they're shown at the on-demand price so the figure is an upper bound.
NODE_PRICES = {
    "e2-micro": 0.0084, "e2-small": 0.0168, "e2-medium": 0.0335,
    "e2-standard-2": 0.0670, "e2-standard-4": 0.1340, "e2-standard-8": 0.2680,
    "e2-highmem-2": 0.0904, "e2-highmem-4": 0.1807,
}
MAX_UPTIME_HOURS = float(os.getenv("MAX_UPTIME_HOURS", "9"))
HARD_CAP_HOURS = float(os.getenv("HARD_CAP_HOURS", "12"))


def _list_nodes() -> list:
    return k8s_client.CoreV1Api().list_node().items


def session_cost(nodes: list, now: datetime.datetime) -> dict:
    """Uptime, per-hour node cost, and a rough total for this cluster session.

    The session starts at the oldest node (the platform node lives the whole
    session); each node is charged from its own creation time, so tenant nodes
    the autoscaler added later count only while they've existed."""
    rows, started = [], None
    for n in nodes:
        labels = n.metadata.labels or {}
        created = n.metadata.creation_timestamp
        machine = labels.get("node.kubernetes.io/instance-type") or labels.get("beta.kubernetes.io/instance-type")
        price = NODE_PRICES.get(machine)
        hours = max((now - created).total_seconds() / 3600, 0) if created else 0
        started = created if created and (started is None or created < started) else started
        rows.append({
            "name": n.metadata.name,
            "pool": labels.get("cloud.google.com/gke-nodepool"),
            "machine_type": machine,
            "spot": labels.get("cloud.google.com/gke-spot") == "true",
            "hourly_usd": price,
            "hours": round(hours, 2),
            "cost_usd": round(price * hours, 3) if price is not None else None,
        })
    uptime = (now - started).total_seconds() / 3600 if started else 0
    return {
        "session_started": started.isoformat() if started else None,
        "uptime_hours": round(uptime, 2),
        "hourly_usd": round(sum(r["hourly_usd"] or 0 for r in rows), 4),
        "session_usd": round(sum(r["cost_usd"] or 0 for r in rows), 2),
        "unpriced_nodes": [r["name"] for r in rows if r["hourly_usd"] is None],
        "teardown": {
            "idle_after_hours": MAX_UPTIME_HOURS,
            "hard_cap_hours": HARD_CAP_HOURS,
            "hours_to_hard_cap": round(max(HARD_CAP_HOURS - uptime, 0), 2),
        },
        "nodes": sorted(rows, key=lambda r: (r["pool"] or "", r["name"])),
    }


@router.get("/admin/cost", tags=["Admin"])
@limiter.limit("30/minute")
def admin_cost(request: Request, current_user: User = Depends(get_current_user)):
    """What this cluster session is costing in node time (approximate, nodes only)."""
    _require_admin(current_user)
    try:
        nodes = _list_nodes()
    except Exception as e:
        logger.warning(f"Failed to list nodes for cost: {e}")
        raise HTTPException(status_code=503, detail="Couldn't read the cluster's nodes")
    return session_cost(nodes, datetime.datetime.now(datetime.timezone.utc))

