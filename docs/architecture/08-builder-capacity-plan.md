# Builder Pool Capacity Plan

**Target Capacity:** 100 concurrent builds

## Resource Allocation per Builder Pod
- **CPU Requests:** `1000m` (1 vCPU)
- **CPU Limits:** `2000m` (2 vCPU)
- **Memory Requests:** `2Gi`
- **Memory Limits:** `4Gi`

*Rationale:* Cloud Native Buildpacks (CNB) can be resource-intensive, particularly during dependency resolution and image layering for Java, Node.js, and Rust. Providing 1 vCPU and 2Gi base ensures reliable execution, while the 4Gi limit prevents OOMKills on heavier layers.

## Cluster Scaling Requirements (at max 100 builds)
- **Total Max CPU:** 200 vCPUs
- **Total Max Memory:** 400 GiB

## KEDA Autoscaling Configuration
- **Scale-to-Zero:** Enabled.
- **Queue Depth Threshold:** `1`
  - *Rationale:* Since builds are long-running (often 1-5 minutes), we want a 1:1 ratio between pending builds in the queue and builder pods. As soon as 1 item hits the `builder_queue`, we scale up.
- **Scale-down Cooldown:** `300` seconds (5 minutes)
  - *Rationale:* Build workloads are spiky. A 5-minute cooldown prevents HPA thrashing and allows Cluster Autoscaler to keep nodes warm for short bursts of commits in rapid succession.

## Node Type Recommendations (Cluster Autoscaler)
For builder workloads, compute-optimized or general-purpose instances with a balanced CPU/RAM ratio are best.
- **Primary:** `c6a.2xlarge` (8 vCPU, 16 GiB RAM) - Supports 4 concurrent builds per node optimally.
- **Fallback:** `m5.2xlarge` (8 vCPU, 32 GiB RAM)
- **Spot Instances:** Highly recommended for builders to reduce costs, relying on the Deployment/Queue retry mechanics if interrupted.
