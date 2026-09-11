# ADR 005: Reject overload instead of hiding it in unbounded queues

- Status: Accepted
- Date: 2026-09-11

## Context

An async HTTP server can admit work faster than a CPU-bound model can execute it. Large bodies, large batches and unlimited concurrent inference can convert a short traffic spike into memory pressure and extreme tail latency.

## Decision

Apply independent admission controls:

- count actual ASGI request bytes, including chunked bodies;
- limit batch record count;
- protect model execution with a bounded semaphore;
- wait only for a configured inference-acquire timeout;
- return `413` for oversized requests and `429` for unavailable inference capacity.

## Consequences

The service intentionally sacrifices admission under overload to preserve bounded resource use and useful latency for accepted work. Capacity settings must be derived from measurement for a specific model and machine.

A reverse proxy should enforce equivalent or stricter request limits, but application correctness does not rely on the client honestly supplying `Content-Length`.
