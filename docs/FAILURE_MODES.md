# Failure Modes

This document is intentionally organized around failure, because the architecture is easier to evaluate by asking what breaks and what remains true.

| Event | What fails | What remains true | Recovery |
|---|---|---|---|
| API restarts | in-flight HTTP requests | durable training jobs and model registry | restart API; reload active model |
| Worker restarts | current training execution | durable job state; serving process | lease expiry and retry |
| Model bundle corrupt | new release load | current in-memory snapshot | reject reload; publish/fix another version |
| Schema changes without matching model | new release compatibility | current compatible model | retrain against new schema before promotion |
| Inference saturation | additional admission | existing accepted work and process health | callers retry with backoff; scale/tune from measurements |
| Oversized/chunked request | that request | process memory admission boundary | reject with `413` |
| Duplicate training request | duplicate intent | one durable job per idempotency key | return original job |
| Training backlog full | new training admission | existing queued/running jobs | wait for capacity; do not bypass queue |
| Worker lease expires | worker ownership | durable job identity/history | reclaim if attempts remain |
| Model refresh exception | visibility of new version | last-known-good serving snapshot | alert, diagnose, retry after registry correction |
| S3 mirror unavailable | optional remote copy | local publication/serving path | restore mirror connectivity; do not misstate S3 as serving authority |
| SQLite volume lost | local control-plane history | existing in-memory model and immutable registry if separate volume survives | restore backup; production design should use managed durable control-plane storage |

## Important non-atomic boundary

The reference system intentionally does not claim a distributed transaction across the SQLite job database, local filesystem model registry and optional S3 mirror. The local publication path minimizes torn artifacts through immutable bundles and pointer replacement, but a process crash at an exact cross-resource boundary can still require operator reconciliation.

A production multi-node release controller should make the promotion record authoritative and recoverable, typically through a transactional database/outbox or a model-registry service with explicit release state. This is a known boundary, not hidden behind an "exactly once" claim.
