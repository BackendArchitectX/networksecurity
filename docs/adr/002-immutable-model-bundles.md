# ADR 002: Publish immutable model bundles through an atomic pointer

- Status: Accepted
- Date: 2026-09-11

## Context

A serving release consists of at least a classifier and its matching preprocessor. Updating those files independently creates a torn-release window. A failed training run must also be unable to overwrite a production preprocessor before its candidate classifier is accepted.

## Decision

Training writes only run-scoped candidate artifacts. After the selected candidate passes the held-out quality gate, `ModelRegistry` publishes the classifier and preprocessor together inside an immutable version directory with a manifest and SHA-256 digests.

The active release is represented by `current.json`. Publication commits the complete version directory first and atomically replaces the pointer last.

The serving runtime additionally requires the manifest's schema fingerprint and ordered feature list to match its own schema before deserializing the bundle.

## Consequences

Positive:

- readers cannot observe a model from one release and a preprocessor from another;
- failed/rejected training does not mutate production artifacts;
- old releases remain available for audit/rollback workflows;
- corruption and schema incompatibility are detected before an in-memory swap;
- serving responses can expose an exact immutable model version.

Costs:

- immutable versions consume storage until retention is applied;
- SHA-256 proves integrity, not publisher authenticity;
- pickle remains a trusted-artifact boundary;
- a distributed registry needs a stronger authoritative promotion mechanism than a shared local filesystem.

## Rejected alternative

Overwriting `final_model/model.pkl` and `final_model/preprocessor.pkl` in place is simpler but cannot provide an atomic multi-file release and was rejected.
