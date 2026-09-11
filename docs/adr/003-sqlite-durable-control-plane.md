# ADR 003: Use SQLite as the single-host durable control-plane reference

- Status: Accepted
- Date: 2026-09-11

## Context

The project needs restart-safe idempotency, bounded backlog, worker ownership, retry attempts, abandoned-job recovery and stale-worker protection. An in-memory dictionary or executor queue cannot demonstrate those semantics because all state disappears with the process.

The repository also should not pretend that adding Kafka or Redis automatically makes a correct distributed control plane.

## Decision

Use SQLite in WAL mode for the reference deployment. Job submission and claims use database transactions. Idempotency keys have a UNIQUE constraint. Workers claim jobs using time-bounded leases and heartbeat ownership. Expired leases are requeued until the configured attempt limit is reached.

Every successful claim also receives a globally monotonic `fence_token`. Heartbeats, terminal state changes and production promotion require the exact `(job_id, worker_id, fence_token)` generation. `claim_next()` permits only one unexpired RUNNING job, and promotion executes while a `BEGIN IMMEDIATE` transaction prevents concurrent reclaim.

The fence sequence is bootstrapped from the active model pointer when a worker starts. That prevents token reuse if the SQLite job database is restored or recreated while the model registry survives.

## Consequences

Positive:

- queue/idempotency state survives API and worker restarts;
- competing processes cannot claim the same queued job through the normal transaction path;
- worker crash recovery is explicit and testable;
- a worker that finishes after losing its lease cannot make its stale candidate active;
- the implementation is small enough that the semantics remain visible to reviewers.

Costs and boundaries:

- SQLite is a single-host/shared-local-filesystem design, not a multi-region queue;
- completed idempotency records need an operational retention policy as history grows;
- generic network filesystems are not assumed to provide appropriate SQLite semantics;
- SQLite state and the filesystem model pointer are separate resources, so the reference design does not claim a distributed transaction or exactly-once publication.

## Production evolution

A production multi-node adapter could use PostgreSQL for job/idempotency state plus SQS, Kafka, or another durable queue. The replacement must preserve the current behavioral contract rather than merely preserve method names: uniqueness, bounded admission, lease expiry, monotonic fencing, retry limits, crash recovery and observable terminal state. An authoritative promotion record or transactional outbox should own the cross-resource release decision.
