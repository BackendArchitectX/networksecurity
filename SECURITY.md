# Security Policy

## Supported code

Security fixes target the current `main` branch. This repository is a reference backend architecture rather than a hosted security product.

## Reporting

Do not open a public issue containing credentials, tokens, private endpoints, exploit payloads against a live deployment, or other secrets. Revoke/rotate exposed credentials first, then report the affected code path without reproducing the secret.

## Model artifact trust boundary

The serving runtime validates model-bundle paths, SHA-256 digests, schema fingerprint and ordered features before deserialization. These checks detect corruption and incompatible releases.

They do **not** make Python pickle safe for untrusted publishers. Anyone able to replace both a pickle artifact and its manifest/checksum must be treated as having code-execution capability in the serving process.

Therefore:

- restrict model-registry write access to the trusted training/release path;
- do not load model bundles uploaded by arbitrary users;
- use least-privilege filesystem/object-store permissions;
- for a distributed production registry, add signed provenance and/or migrate to a serialization format with a narrower executable surface.

## Administrative API

Training submission and manual reload are disabled until `ADMIN_API_KEY` is configured. The current API-key mechanism is suitable only for a constrained reference/internal deployment.

An internet-facing production service should place administrative operations behind workload identity or OAuth/JWT authorization and network policy. TLS should terminate at a trusted ingress/load balancer.

## Secrets

Secrets must come from the deployment environment or a secret manager. Never commit MongoDB credentials, AWS access keys, MLflow tokens, admin keys, or connection strings containing credentials.

If a credential has ever been committed:

1. revoke or rotate it immediately;
2. remove it from the current tree;
3. audit access/activity where the provider supports it;
4. rewrite Git history if removal from repository history is required;
5. assume forks, caches or clones may still contain the old value.

Deleting the latest version of a file does not make an already exposed credential safe.

## Dependency and container controls

CI audits the serving dependency set, performs package consistency checks, compiles the code, runs tests and builds both deployment images. API and training dependencies are intentionally separated. Both images run as a non-root user.

Dependency-audit findings must be evaluated before suppressing them. If a vulnerability cannot be fixed immediately, document the affected package, reachable surface, mitigation and expiry date of the exception.

## Request safety

The API enforces request-size limits on the actual ASGI byte stream, including chunked requests, and independently limits inference batch size. Production ingress should apply equivalent or stricter limits before traffic reaches the application.

## Data handling

Raw training data is intentionally not redistributed in this repository because the historical CSV's provenance and redistribution terms were not documented sufficiently. Supply only data that you are permitted to use, and define retention, access control, encryption, deletion and audit requirements appropriate to that data. See `docs/DATASET.md` for the expected schema and ingestion contract.
