# ADR 0005: Build System

**Status:** ACCEPTED (Amended)
**Context:** We need to convert source code to OCI container images automatically without introducing shared blast radius.
**Decision:** We adopt the **3-Tier Ephemeral Builder** architecture:
1. **Tier 1 (Buildpacks):** Default fallback. Runs `pack` rootless in `shipzen-builder`.
2. **Tier 2 (Dockerfile):** Runs BuildKit in `shipzen-builder-privileged`.
3. **Tier 3 (Railpack):** For complex/mixed repos, runs Railpack natively in `shipzen-builder-privileged`.

Every build is a single-use Kubernetes `Job` that instantly terminates.

**Historical Context:** 
Originally, Cloud Native Buildpacks were proposed with a Dockerfile fallback using KEDA scaled persistent pods. On June 19, this was amended to the 3-Tier Ephemeral Builder using single-use Kubernetes Jobs to eliminate shared environments and improve security.

**Consequences:** 
- Zero-configuration builds for supported runtimes.
- strict security boundaries with ephemeral jobs.
**Conflict Resolution Policy:** Shared persistent builder environments are forbidden.
