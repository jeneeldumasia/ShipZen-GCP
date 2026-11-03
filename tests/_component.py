"""Load api/, worker/ or controller/ main.py side by side in one test session.

All three components have a top-level ``main`` module and share sibling module
names (``database``, ``metrics``, ...), so a plain ``import main`` only ever
gets one of them. ``load("worker")`` imports that component's main.py with its
own siblings, then clears the shared names so the next component can load its
own. Kubernetes config loading is stubbed so no cluster or kubeconfig is needed.
"""
import functools
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
_SHARED = ["main", "database", "metrics", "models", "config", "auth", "audit",
           "analyzer", "queue_client", "state_machine", "builder",
           # api/ modules split out of main.py
           "background", "helpers", "platform_clients", "ratelimit", "secret_store",
           "validation", "routers", "migrate"]


def _forget_shared_modules():
    for name in list(sys.modules):
        if name in _SHARED or name.split(".")[0] == "routers":
            sys.modules.pop(name, None)

os.environ.setdefault("DATABASE_URL", "postgresql://shipzen:shipzen-local@localhost:5432/shipzen")
os.environ.setdefault("REDIS_HOST", "localhost")


@functools.lru_cache(maxsize=None)
def load(component: str):
    import kubernetes.config
    kubernetes.config.load_incluster_config = MagicMock()
    kubernetes.config.load_kube_config = MagicMock()

    _forget_shared_modules()
    comp_dir = str(ROOT / component)
    sys.path[:0] = [comp_dir, str(ROOT)]
    cwd = os.getcwd()
    os.chdir(comp_dir)  # controller resolves its templates/ relative to cwd
    try:
        import main  # noqa: E402
        return main
    finally:
        os.chdir(cwd)
        sys.path.remove(comp_dir)
        sys.path.remove(str(ROOT))
        _forget_shared_modules()


def apply_migrations(dsn: str):
    """Create the schema the way the API does at startup (api/migrate.py)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("shipzen_api_migrate", ROOT / "api" / "migrate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.apply_migrations(dsn)


def postgres_available() -> bool:
    try:
        import psycopg2
        psycopg2.connect(os.environ["DATABASE_URL"], connect_timeout=2).close()
        return True
    except Exception:
        return False
