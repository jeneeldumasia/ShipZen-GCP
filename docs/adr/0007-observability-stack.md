# ADR 0007: Observability Stack

**Status:** ACCEPTED
**Context:** The platform requires metrics, alerts, and dashboards.
**Decision:** We will use Prometheus for metrics, Grafana for visualization, and GCS for long-term log storage. High cardinality labels (e.g. dynamic paths or pod names) are strictly forbidden.
**Consequences:** 
- Ensures Prometheus remains performant at scale.
- Aggregated metrics will be used for SLO monitoring.
**Conflict Resolution Policy:** Any metrics containing unbound high cardinality labels will be rejected during code review.
