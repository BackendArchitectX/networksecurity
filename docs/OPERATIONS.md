# Operations

## Operating assumptions

This repository provides a single-host durable reference topology with two processes: an inference API and a training worker. Both use the same durable job-store volume and immutable model-registry volume.

The policies below are **operational semantics and design targets**, not unmeasured availability or latency claims.

| Signal | Policy |
|---|---|
| API process liveness | independent of model availability |
| Inference readiness | true only with a verified in-memory model snapshot |
| Request overload | reject above configured body/batch limits |
| Inference saturation | bounded wait, then `429` |
| Training backlog | durable bounded admission, then `429` |
| Worker ownership | expiring lease with heartbeat and finite attempts |
| Model promotion | immutable bundle first, active pointer last |
| Reload failure | retain last-known-good in-memory snapshot |

## Local deployment

```bash
cp .env.example .env
# configure at least ADMIN_API_KEY and MONGO_DB_URL

docker compose up --build
```

The API uses runtime-only dependencies. The worker image contains training-only dependencies and database/cloud adapters.

## Startup behavior

The API can start before a model is promoted:

```text
/health/live   -> 200
/health/ready  -> 503
```

When `MODEL_LOAD_ON_STARTUP=true`, the API attempts to load the registry's active version. If the registry is empty, the process remains live and unready. If the active bundle is corrupt or incompatible, startup remains live/unready and logs the rejected load.

A background refresh loop subsequently watches the active registry version. A valid promotion becomes available without restarting the API.

## Training submission runbook

Choose an idempotency key that identifies the retraining intent, not a random retry token.

```bash
curl -X POST http://localhost:8080/api/v1/training-jobs \
  -H "X-Admin-Api-Key: $ADMIN_API_KEY" \
  -H 'Idempotency-Key: phishing-dataset-2026-09-11'
```

Persist the returned job ID. Repeating the same idempotency key returns the original job and does not create duplicate expensive work.

Check status:

```bash
curl http://localhost:8080/api/v1/training-jobs/<job-id> \
  -H "X-Admin-Api-Key: $ADMIN_API_KEY"
```

Operationally important response fields are `state`, `attempts`, `finished_at`, `error`, and `model_version`.

## Worker failure runbook

A RUNNING job has a lease. The worker extends that lease while training.

If a worker process crashes:

1. The job remains RUNNING until `lease_until`.
2. Another worker poll detects the expired lease.
3. If attempts remain, the job returns to QUEUED and is claimed again.
4. If `TRAINING_JOB_MAX_ATTEMPTS` has been reached, the job becomes FAILED.

Do not manually create a replacement job with a new idempotency key merely because the worker restarted. First inspect the durable original job.

## Model promotion runbook

Normal promotion is performed by the training worker after the candidate passes the held-out quality gate.

A promoted version contains:

- classifier artifact
- matching preprocessor artifact
- manifest
- SHA-256 checksums
- model-selection/evaluation metadata
- schema SHA-256 fingerprint
- ordered feature contract

The version directory is immutable. `current.json` is the only active-version pointer.

After promotion:

1. Verify the training job reaches `SUCCEEDED` with a `model_version`.
2. Verify `/api/v1/model` eventually reports that version.
3. Verify `model_ready == 1`.
4. Verify `model_reload_total{outcome="success"}` increments on refresh.
5. Run a known request fixture if this is an operator-driven rollout.

## Manual reload

The authenticated reload endpoint is useful when an operator wants immediate refresh rather than waiting for the background polling interval:

```bash
curl -X POST http://localhost:8080/api/v1/model/reload \
  -H "X-Admin-Api-Key: $ADMIN_API_KEY"
```

Reload performs the same checksum, path, schema and interface validation as background refresh. A rejected reload does not clear the already loaded snapshot.

## Rollback

Rollback means moving the active pointer to a previously verified immutable version; it should not mean copying old bytes over new bytes.

The current reference implementation does not expose an HTTP rollback endpoint. This is deliberate: arbitrary promotion/rollback is a privileged release-management action and should not be conflated with inference APIs.

For a production registry adapter, implement rollback as an audited pointer/promotion operation, then let serving instances refresh through the normal compatibility path.

## Alerts worth implementing

A real deployment should consider alerts for:

- `model_ready == 0` on an instance expected to receive traffic
- sustained HTTP `5xx`
- sustained inference `429`
- unexpected increase in in-flight inference
- p95/p99 inference or request-latency regression
- repeated `model_reload_total{outcome="failure"}`
- training jobs exhausting maximum attempts
- training backlog remaining near capacity
- active model version changing outside the expected release window
- model version remaining stale after a successful training promotion

Do not alert on the train/test KS diagnostic as though it were production drift. A separate production telemetry pipeline should define actual drift signals.

## Backup and recovery

For the local reference deployment, durable state consists of:

- SQLite training-job database
- immutable model-registry directories and `current.json`

Back up the database and model registry consistently for disaster recovery. The optional S3 mirror uploads versioned model contents before the active pointer, which avoids publishing a remote pointer to a bundle that has not yet been uploaded.

The current serving implementation consumes the local registry, not the S3 mirror. A production object-store registry should define its own consistency and watch semantics.

## Capacity knobs

| Setting | Meaning |
|---|---|
| `MAX_REQUEST_BYTES` | absolute request-body limit enforced on the ASGI byte stream |
| `MAX_BATCH_SIZE` | maximum records in one inference batch |
| `MAX_INFERENCE_CONCURRENCY` | concurrent model executions per API process |
| `INFERENCE_ACQUIRE_TIMEOUT_MS` | maximum wait for inference capacity |
| `MAX_PENDING_TRAINING_JOBS` | QUEUED + RUNNING durable backlog limit |
| `TRAINING_JOB_LEASE_SECONDS` | worker ownership duration between heartbeats |
| `TRAINING_JOB_MAX_ATTEMPTS` | recovery limit before terminal failure |
| `MODEL_REFRESH_INTERVAL_SECONDS` | registry polling interval for serving instances |

Tune these from measured CPU/memory/latency behavior. Do not copy benchmark values between machines or models and present them as universal capacity.

## Security runbook

- Use a secret manager for admin, MongoDB, AWS and MLflow credentials.
- Prefer workload identity/IAM roles over static cloud keys.
- Restrict write access to the model registry. Pickle artifacts are a trusted-code boundary.
- Keep administrative endpoints on an internal authorization/network path.
- Use TLS at the ingress/load balancer.
- Match or tighten body limits at the reverse proxy.
- Run both containers as non-root, as enforced by CI.
- Rotate any credential that has ever been committed to repository history; deleting the current file does not invalidate an exposed secret.

## Incident: corrupt promoted model

Expected behavior is last-known-good serving.

1. Confirm `/api/v1/model` still reports the previous version.
2. Inspect model reload failure logs and `model_reload_total{outcome="failure"}`.
3. Inspect the promoted bundle manifest and checksums.
4. Do not bypass integrity/schema validation to make the version load.
5. Correct the candidate/promotion path and publish a new immutable version or restore the release pointer through the privileged registry process.

## Multi-node evolution

Do not mount SQLite over a generic network filesystem and call it a distributed queue.

For multiple hosts/regions, replace the adapters with a durable distributed job store/queue and object-store registry while preserving the existing semantic contract: idempotency, bounded admission, lease/fencing ownership, immutable model versions, compatibility checks, last-known-good serving and observable promotion.
