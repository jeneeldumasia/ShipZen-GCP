from prometheus_client import Gauge
from prometheus_client import Counter, Summary, start_http_server

# Fix: was a Gauge — rate() on a Gauge always returns 0 and the drift alert
# was silently broken. Counter is correct for a monotonically increasing event total.
shipzen_drift_total = Counter(
    'shipzen_drift_total',
    'Total number of detected drift incidents (missing or orphaned resources)'
)

shipzen_reconciliation_duration_seconds = Summary(
    'shipzen_reconciliation_duration_seconds',
    'Time spent in the reconciliation loop'
)

# Fix #19: Counter resets on restart, but we will use PromQL increase()
# or rate() to measure success rate over time instead of relying on absolute value.
shipzen_deployment_success_total = Counter(
    'shipzen_deployment_success_total',
    'Total number of successful deployments transitioned to Running'
)


shipzen_active_deployments = Gauge(
    'shipzen_active_deployments',
    'Current number of running deployments',
    ['namespace']
)


def start_metrics_server(port: int = 9090):
    # Fix: was 8080, which collides with the controller's own app port.
    # Metrics now bind on 9090.
    start_http_server(port)
