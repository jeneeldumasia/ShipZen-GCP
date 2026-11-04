"""Read-only access to the cluster's Loki (logs) and Prometheus (metrics) for one project.

Every query is built here from values the API looked up itself (the project's
namespace and a deployment id from the database), never from user input, and
both are checked against a strict pattern before use. The only user-supplied
value, a log search string, is passed as a LogQL raw string with backticks
removed, so it can only filter lines, not change the selector.
"""
import os
import re
import time
from typing import Optional

import httpx

LOKI_URL = os.getenv("LOKI_URL", "http://loki-stack.shipzen-system.svc:3100")
PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://kube-prometheus-stack-prometheus.observability.svc:9090")
TIMEOUT = httpx.Timeout(8.0, connect=3.0)

_NAME = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
_RANGES = {"1h": (3600, 60), "6h": (6 * 3600, 300), "24h": (24 * 3600, 900)}
MAX_LOG_LINES = 1000


class ObservabilityError(Exception):
    """Loki or Prometheus didn't answer usefully."""


def _check(name: str) -> str:
    if not isinstance(name, str) or not _NAME.match(name):
        raise ValueError("invalid name")
    return name


def log_selector(namespace: str, deployment_id: str) -> str:
    # Pods of a release are named "<deployment_id>-<hash>-<id>".
    return f'{{namespace="{_check(namespace)}", pod=~"{_check(deployment_id)}-.*"}}'


def log_query(namespace: str, deployment_id: str, search: Optional[str] = None) -> str:
    q = log_selector(namespace, deployment_id)
    if search:
        q += " |= `" + search.replace("`", "")[:200] + "`"
    return q


def runtime_logs(namespace: str, deployment_id: str, since_ns: Optional[int] = None,
                 limit: int = 500, search: Optional[str] = None) -> list[dict]:
    """Newest `limit` lines after since_ns (default: the last hour), oldest first."""
    limit = max(1, min(int(limit), MAX_LOG_LINES))
    now_ns = time.time_ns()
    start = since_ns + 1 if since_ns else now_ns - 3600 * 10**9
    params = {"query": log_query(namespace, deployment_id, search), "start": str(start),
              "end": str(now_ns), "limit": str(limit), "direction": "backward"}
    try:
        r = httpx.get(f"{LOKI_URL}/loki/api/v1/query_range", params=params, timeout=TIMEOUT)
        r.raise_for_status()
        result = r.json()["data"]["result"]
    except Exception as e:
        raise ObservabilityError(f"loki: {type(e).__name__}") from e
    lines = []
    for stream in result:
        pod = (stream.get("stream") or {}).get("pod", "")
        for ts, line in stream.get("values", []):
            lines.append({"ts": int(ts), "pod": pod, "line": line})
    lines.sort(key=lambda x: x["ts"])
    return lines[-limit:]


def metric_queries(namespace: str) -> dict[str, str]:
    ns = _check(namespace)
    pods = f'namespace="{ns}", container!="", container!="POD"'
    route = f'envoy_cluster_name=~"httproute/{ns}/.*"'
    return {
        "cpu_cores": f"sum(rate(container_cpu_usage_seconds_total{{{pods}}}[5m]))",
        "memory_bytes": f"sum(container_memory_working_set_bytes{{{pods}}})",
        "instances": f'sum(kube_deployment_status_replicas_available{{namespace="{ns}"}})',
        "restarts": f'sum(increase(kube_pod_container_status_restarts_total{{namespace="{ns}"}}[5m]))',
        "requests_per_s": f"sum(rate(envoy_cluster_upstream_rq_total{{{route}}}[5m]))",
        "errors_per_s": f'sum(rate(envoy_cluster_upstream_rq_xx{{{route}, envoy_response_code_class="5"}}[5m]))',
        "p95_ms": ("histogram_quantile(0.95, sum by (le) "
                   f"(rate(envoy_cluster_upstream_rq_time_bucket{{{route}}}[5m])))"),
    }


def project_metrics(namespace: str, range_: str = "1h") -> dict:
    """{name: [[unix_seconds, value], ...]} for each metric over the range."""
    if range_ not in _RANGES:
        raise ValueError("invalid range")
    span, step = _RANGES[range_]
    end = int(time.time())
    start = end - span
    series = {}
    with httpx.Client(timeout=TIMEOUT) as client:
        for name, query in metric_queries(namespace).items():
            try:
                r = client.get(f"{PROMETHEUS_URL}/api/v1/query_range",
                               params={"query": query, "start": start, "end": end, "step": step})
                r.raise_for_status()
                result = r.json()["data"]["result"]
            except Exception as e:
                raise ObservabilityError(f"prometheus: {type(e).__name__}") from e
            points = result[0]["values"] if result else []
            series[name] = [[int(t), _num(v)] for t, v in points]
    return {"range": range_, "step": step, "start": start, "end": end, "series": series}


def _num(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f or f in (float("inf"), float("-inf")) else round(f, 6)
