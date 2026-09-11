# ADR 006: Preserve last-known-good serving across model reload failure

- Status: Accepted
- Date: 2026-09-11

## Context

A model release can be corrupt, incomplete, incompatible with the current feature schema, or fail during deserialization. Clearing the current model before validating its replacement would turn a bad release into an avoidable serving outage.

## Decision

`ModelRuntime` loads and validates a complete candidate snapshot before acquiring the short swap lock. The active snapshot remains untouched until the candidate is ready. Reload attempts are serialized with a separate reload lock, while inference continues against the current immutable snapshot.

## Consequences

A failed background or manual reload is observable but does not automatically make an already-ready process unavailable. A process that has never loaded a valid model remains live but unready.

This design favors serving continuity over forcing every registry pointer change to become immediately visible. Operators must alert on repeated reload failures so a stale last-known-good version does not silently persist indefinitely.
