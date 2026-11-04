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


# ---------------------------------------------------------------------------
# Tests re-import api/, worker/ and controller/ modules (sometimes more than
# once). Each import registers its Prometheus metrics in the global registry,
# and a second registration raised DuplicateTimeseries, failing unrelated tests.
# In tests, let a re-registration replace the earlier collector instead.
# ---------------------------------------------------------------------------
import prometheus_client.registry as _prom_registry

_orig_register = _prom_registry.CollectorRegistry.register


def _register_replacing(self, collector):
    try:
        names = self._get_names(collector)
    except Exception:
        names = []
    with self._lock:
        stale = {self._names_to_collectors[n] for n in names if n in self._names_to_collectors}
    for old in stale:
        self.unregister(old)
    return _orig_register(self, collector)


_prom_registry.CollectorRegistry.register = _register_replacing


# ---------------------------------------------------------------------------
# Throwaway Postgres and Redis for the database tests (needs Docker). Defined
# once here so every test module shares the same containers: importing these
# fixtures into several modules used to start one container per module, while
# application modules kept talking to the first one.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def postgres_container():
    from _docker import is_docker_running
    if not is_docker_running():
        pytest.skip("Docker daemon is not running")
    import psycopg2
    from testcontainers.postgres import PostgresContainer
    with PostgresContainer("mirror.gcr.io/library/postgres:15-alpine", dbname="shipzen") as postgres:
        os.environ["DATABASE_URL"] = postgres.get_connection_url().replace("+psycopg2", "")
        from _component import apply_migrations
        apply_migrations(os.environ["DATABASE_URL"])
        yield postgres


@pytest.fixture(scope="session")
def redis_container():
    from _docker import is_docker_running
    if not is_docker_running():
        pytest.skip("Docker daemon is not running")
    from testcontainers.redis import RedisContainer
    with RedisContainer("mirror.gcr.io/library/redis:7-alpine") as redis_server:
        os.environ["REDIS_HOST"] = redis_server.get_container_host_ip()
        os.environ["REDIS_PORT"] = str(redis_server.get_exposed_port(6379))
        yield redis_server
