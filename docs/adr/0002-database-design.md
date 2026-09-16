# ADR 0002: Database Design

**Status:** ACCEPTED (Amended)
**Context:** We need a primary database to serve as the Source of Truth for desired state. 
**Decision:** We will use PostgreSQL as the primary relational database and source of truth. Build logs will be stored in GCS, not PostgreSQL.
**Consequences:** 
- Allows strong schema validation, referential integrity, and ACID compliance.

**Historical Context (Original Proposal):**
Initially, MongoDB was proposed to allow flexible schema evolution. However, the decision was amended to PostgreSQL to enforce robust schema validation and avoid BSON document limits.

**Conflict Resolution Policy:** Any implementations using MongoDB or NoSQL for core state will be rejected.
