# ADR 004: Treat model artifacts as trusted code, not user data

- Status: Accepted
- Date: 2026-09-11

## Context

The current scikit-learn artifacts are serialized with Python pickle. Pickle can execute code during deserialization. Hash verification detects accidental corruption or replacement relative to a manifest, but it does not authenticate a publisher who can rewrite both the artifact and its digest.

## Decision

Keep pickle for this reference implementation, but make the trust boundary explicit and enforce it operationally. Only the trusted training/release path may write the model registry. Serving validates bundle location, checksum, schema fingerprint, feature order and expected interfaces before deserializing.

## Consequences

This is acceptable only when registry write access is equivalent to code-deployment privilege. Arbitrary user-uploaded artifacts must never be loaded.

For a production external registry, use signed provenance and evaluate a narrower serialization format such as a constrained sklearn model format. Migration should be treated as a security architecture change rather than described as checksum hardening.
