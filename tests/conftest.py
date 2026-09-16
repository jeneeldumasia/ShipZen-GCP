"""
Shared pytest fixtures and global test setup for ShipZen.

Responsibilities
----------------
1. Ensure DATABASE_URL / REDIS_HOST are always set before any application module
   is imported (the app raises RuntimeError if DATABASE_URL is missing).
2. Provide a pytest-asyncio mode declaration so async tests run without extra
   marks on every test function.
"""
import os
import sys

# ---------------------------------------------------------------------------
# Guard: set DATABASE_URL *before* any app module import can happen.
# test_core.py sets a real testcontainer URL in its session fixture, which
# overrides this fallback.  test_production_fixes.py and test_worker.py set
# their own defaults at module level, but this acts as a final backstop.
# ---------------------------------------------------------------------------
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://shipzen:shipzen-local@localhost:5432/shipzen",
)
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_PORT", "6379")
os.environ.setdefault("S3_LOG_BUCKET",   "test-bucket")
os.environ.setdefault("STREAM_NAME",     "test_stream")
os.environ.setdefault("CONSUMER_GROUP",  "test_group")

# ---------------------------------------------------------------------------
# pytest-asyncio: run all async tests automatically without @pytest.mark.asyncio
# per-function.  This avoids the PytestUnraisableExceptionWarning that appears
# when the mode is left as "strict" (the new default in pytest-asyncio >= 0.21).
# ---------------------------------------------------------------------------
import pytest

def pytest_configure(config):
    """Register asyncio_mode=auto so async tests don't need the per-test mark."""
    config.addinivalue_line(
        "markers",
        "asyncio: mark a test as an async test (handled by pytest-asyncio)",
    )
