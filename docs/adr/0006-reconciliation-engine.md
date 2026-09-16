# ADR 0006: Reconciliation Engine

**Status:** ACCEPTED
**Context:** We must ensure the runtime state in Kubernetes matches our intended state.
**Decision:** We will build a continuous reconciliation controller that treats MongoDB as the absolute source of truth. It will detect drift every 60 seconds and auto-correct it.
**Consequences:** 
- Kubernetes state is never authoritative. 
- Manual `kubectl` edits will be automatically reverted.
**Conflict Resolution Policy:** Any subsystem treating Kubernetes as the source of truth will be rejected.
