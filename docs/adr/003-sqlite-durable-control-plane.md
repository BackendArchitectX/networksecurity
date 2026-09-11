# ADR 003: Use SQLite as the single-host durable control-plane reference

- Status: Accepted
- Date: 2026-09-11

## Context

The project needs restart-safe idempotency, bounded backlog, worker ownership, retry attempts and abandoned-job recovery. An in-memory dictionary or executor queue cannot demonstrate those semantics because all state disappears with the process.

The repository also should not pretend that adding Kafka or Redis automatically makes a correct distributed control plane.

## Decision

Use SQLite in WAL mode for the reference deployment. Job submission and claims use database transactions. Idempotency keys have a UNIQUE constraint. Workers claim jobs using time-bounded leases and heartbeat ownership. Expired leases are requeued until the configured attempt limit is reached.

`claim_next()` permits only one unexpired RUNNING job. That gives the shared-filesystem model registry a single active training/publisher at a time even when multiple worker processes poll the database.

## Consequences

Positive:

- queue/idempotency state survives API and worker restarts;
- competing processes cannot claim the same queued job through the normal transaction path;
- worker crash recovery is explicit and testable;
- the implementation is small enough that the semantics remain visible to reviewers.

Costs and boundaries:

- SQLite is a single-host/shared-local-filesystem design, not a multi-region queue;
- completed idempotency records need an operational retention policy as history grows;
- generic network filesystems are not assumed to provide appropriate SQLite semantics;
- a distributed version needs a durable database/queue and stronger fencing around model promotion.

## Production evolution

A production multi-node adapter could use PostgreSQL for job/idempotency state plus SQS, Kafka, or another durable queue. The replacement must preserve the current behavioral contract rather than merely preserve method names: uniqueness, bounded admission, ownership, retry limits, crash recovery and observable terminal state.
