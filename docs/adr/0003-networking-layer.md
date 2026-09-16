# ADR 0003: Networking Layer

**Status:** ACCEPTED
**Context:** We need to expose tenant workloads safely and dynamically.
**Decision:** We will use the Gateway API with Envoy Gateway. NodePort services will NOT be used under any circumstances. HTTPRoutes will be dynamically generated and cleaned up per deployment.
**Consequences:** 
- Adopts the modern standard for Kubernetes ingress routing.
- Eliminates port conflicts and improves security boundaries.
**Conflict Resolution Policy:** Any PR introducing Ingress objects or NodePort services will be rejected.
