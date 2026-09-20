import os
import logging
import hashlib
from dataclasses import dataclass
from typing import Optional
import asyncio

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from cachetools import TTLCache
from collections import defaultdict
import threading

logger = logging.getLogger(__name__)

GITHUB_ENABLED = (
    os.getenv("GITHUB_ENABLED", "false").lower() == "true" or
    os.getenv("SHIPZEN_GITHUB_ENABLED", "false").lower() == "true" or
    bool(os.getenv("SHIPZEN_OAUTH_CLIENT_ID")) or
    bool(os.getenv("OAUTH_CLIENT_ID"))
)

# M-6 Fix: Reusable httpx.AsyncClient singleton to avoid per-request overhead
_http_client = httpx.AsyncClient(
    limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
    timeout=30.0
)

_bearer = HTTPBearer(auto_error=False)

# HIGH-01 Fix: Reduce token cache TTL from 5 minutes to 60 seconds
# to minimize the window where revoked access remains valid
_token_cache = TTLCache(maxsize=1000, ttl=60)
_user_to_cache_keys = defaultdict(set)
_cache_lock = threading.Lock()


def evict_user_token_cache(user_id: str):
    """Instantly evicts all cached tokens for a user when roles/permissions change."""
    with _cache_lock:
        keys_to_remove = _user_to_cache_keys.pop(user_id, set())
        for k in keys_to_remove:
            _token_cache.pop(k, None)
        for k, u in list(_token_cache.items()):
            if getattr(u, 'user_id', None) == user_id:
                _token_cache.pop(k, None)
        logger.info(f"Evicted auth token cache for user {user_id}")


# REL-01 Fix: Circuit breaker state for GitHub API
# Protected by _github_cb_lock — async handlers run concurrently and can race.
_github_cb_lock = threading.Lock()
_github_cb_failures = 0
_github_cb_last_failure = 0.0
_github_cb_open = False


@dataclass
class User:
    user_id: str
    role: str = 'user'

    @property
    def is_admin(self) -> bool:
        return self.role == 'admin'


async def get_current_user_from_token(token: str) -> User:
    return await get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token))


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    # Local Dev Bypass
    # MED-09 Fix: Explicitly deny local stub auth if ENVIRONMENT == "production"
    if token == "stub-token":
        if os.getenv("ENABLE_LOCAL_STUB_AUTH", "false").lower() != "true" or os.getenv("ENVIRONMENT", "development") == "production":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Stub authentication is disabled.",
            )

        from database import get_or_create_user

        db_user = await asyncio.to_thread(get_or_create_user, "local-dev-user", "local-dev@example.com")
        user = User(user_id="local-dev-user", role=db_user["role"])
        cache_key = hashlib.sha256(token.encode()).hexdigest()
        with _cache_lock:
            _token_cache[cache_key] = user
            _user_to_cache_keys[user.user_id].add(cache_key)
        return user

    if not GITHUB_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured. Set GITHUB_ENABLED=true.",
        )

    # Fix 12: Token cache key is the raw bearer token, hash it
    cache_key = hashlib.sha256(token.encode()).hexdigest()

    # Check cache
    with _cache_lock:
        if cache_key in _token_cache:
            return _token_cache[cache_key]

    # Verify token with GitHub
    
    # REL-01 Fix: Circuit breaker logic for GitHub API
    global _github_cb_failures, _github_cb_last_failure, _github_cb_open
    import time

    with _github_cb_lock:
        cb_open = _github_cb_open
        cb_last_failure = _github_cb_last_failure

    if cb_open:
        if time.time() - cb_last_failure < 30:
            raise HTTPException(
                status_code=503, detail="Auth service temporarily unavailable (circuit breaker open)")
        else:
            # Half-open state: let one request through to test
            with _github_cb_lock:
                _github_cb_open = False

    try:
        resp = await _http_client.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {token}",
                     "Accept": "application/vnd.github+json"},
            timeout=5
        )
        if resp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid GitHub token",
            )

        gh_user = resp.json()
        # Fetch emails because primary email might be private
        email_resp = await _http_client.get(
            "https://api.github.com/user/emails",
            headers={"Authorization": f"Bearer {token}",
                     "Accept": "application/vnd.github+json"},
            timeout=5
        )
        email = None
        if email_resp.status_code == 200:
            for e in email_resp.json():
                if e.get("primary"):
                    email = e.get("email")
                    break

        user_info = {
            "id": str(gh_user["id"]),
            "login": gh_user["login"],
            "email": email or gh_user.get("email")
        }
    except httpx.RequestError as e:
        logger.error(f"GitHub API request failed: {e}")
        # Update circuit breaker state atomically
        with _github_cb_lock:
            _github_cb_failures += 1
            _github_cb_last_failure = time.time()
            if _github_cb_failures >= 5:
                _github_cb_open = True
                logger.warning("GitHub API circuit breaker opened")

        raise HTTPException(
            status_code=503, detail="Auth service unavailable")

    # Reset circuit breaker on success — clear failure count AND stale timestamp
    with _github_cb_lock:
        _github_cb_failures = 0
        _github_cb_last_failure = 0.0
        _github_cb_open = False

    from database import get_or_create_user
    db_user = await asyncio.to_thread(get_or_create_user, user_info["id"], user_info["email"])
    user = User(user_id=user_info["id"], role=db_user["role"])
    with _cache_lock:
        _token_cache[cache_key] = user
        _user_to_cache_keys[user.user_id].add(cache_key)
    return user
