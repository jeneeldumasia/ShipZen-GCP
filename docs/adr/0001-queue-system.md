# ADR 0001: Queue System

**Status:** ACCEPTED (Amended)
**Context:** We need a robust queueing system to handle deployment requests asynchronously.
**Decision:** We will use Redis Streams. We will NOT use Redis Lists or BLPOP. Consumer groups will be utilized with explicit ACK support, retry handling, a Dead Letter Queue (DLQ), and pending message recovery.

**Amendment (June 19):** The worker queue now spawns single-use K8s Jobs (3-Tier Ephemeral Builders) rather than passing messages to a persistent builder queue. 
**Consequences:** 
- Ensures exactly-once behavior at the application level.
- Provides native support for consumer groups and failure tracking.
**Conflict Resolution Policy:** Any implementation attempting to use alternative queues or Redis Lists will be rejected.
