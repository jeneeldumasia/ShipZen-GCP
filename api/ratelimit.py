"""Rate limiting: one limiter shared by every router."""
import hashlib
import os
from urllib.parse import quote

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

def _user_id_or_ip(request: Request) -> str:
    """Rate-limit key.

    External traffic only reaches the gateway through Cloudflare (the load
    balancer is restricted to Cloudflare's ranges), and Cloudflare overwrites
    CF-Connecting-IP with the real client address, so it can't be spoofed.
    Keying on it means a client can't escape its limit by sending random bearer
    tokens (each of which also cost a GitHub API call) or a fake
    X-Forwarded-For, which the previous key trusted.

    In-cluster calls (the UI's server-side requests) carry no Cloudflare header;
    those keep a per-token key so users of the UI don't share one bucket.
    """
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        return f"ip:{cf_ip.strip()}"
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return "tok:" + hashlib.sha256(auth_header[7:].encode()).hexdigest()[:32]
    return f"ip:{get_remote_address(request)}"


def _storage_uri() -> str:
    """Redis URI for the limit counters.

    In memory, every uvicorn worker in every API replica kept its own counters
    (2 replicas x 4 workers = 8 buckets), so a client got up to 8x each limit.
    Redis gives one shared count per client and limit.
    """
    host = os.getenv("REDIS_HOST", "redis-master.shipzen-system.svc.cluster.local")
    port = os.getenv("REDIS_PORT", "6379")
    password = os.getenv("REDIS_PASSWORD")
    auth = f":{quote(password, safe='')}@" if password else ""
    return f"redis://{auth}{host}:{port}"


# If Redis is unreachable, limits fall back to per-process memory (and switch
# back once it returns) instead of failing requests.
limiter = Limiter(
    key_func=_user_id_or_ip,
    storage_uri=_storage_uri(),
    storage_options={"socket_connect_timeout": 1, "socket_timeout": 1},
    in_memory_fallback_enabled=True,
    swallow_errors=True,
)
