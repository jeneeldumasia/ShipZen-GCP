"""Is a Docker daemon available? Database tests skip without one."""
import functools


@functools.lru_cache(maxsize=None)
def is_docker_running() -> bool:
    try:
        import docker
        docker.from_env().ping()
        return True
    except Exception:
        return False
