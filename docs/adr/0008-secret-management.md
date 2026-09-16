# ADR 0008: Secret Management

**Status:** ACCEPTED
**Context:** Applications require sensitive configurations (API keys, DB credentials).
**Decision:** Centralized secret management via GCP Secret Manager. External Secrets Operator (ESO) will sync these into per-tenant Kubernetes Secrets. 
**Consequences:** 
- Secrets are never hardcoded or stored in MongoDB.
- Provides a centralized audit trail via GCP.
**Conflict Resolution Policy:** Secrets passed as plaintext environment variables or embedded in Git will be rejected.
