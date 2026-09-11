# Architecture Decision Records

These ADRs capture decisions that materially change system semantics rather than merely code organization.

- `001-separate-serving-and-training.md` — isolate expensive training from inference
- `002-immutable-model-bundles.md` — publish model + preprocessor as one immutable release
- `003-sqlite-durable-control-plane.md` — durable single-host idempotency and worker leases
- `004-trusted-model-artifacts.md` — make pickle's trusted-code boundary explicit
- `005-request-admission-and-backpressure.md` — reject overload instead of hiding it in queues

Each decision records both the guarantee gained and the boundary that remains. The intent is to make trade-offs reviewable instead of burying them in implementation details.
