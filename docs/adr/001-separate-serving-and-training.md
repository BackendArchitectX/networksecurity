# ADR 001: Separate serving and training processes

- Status: Accepted
- Date: 2026-09-11

## Context

Model training is CPU/memory intensive, depends on MongoDB/MLflow/cloud libraries, and may run for much longer than an inference request. Running it inside the API process couples request availability to retraining resource consumption and process failure.

## Decision

The HTTP API only persists training intent to a durable job store. A separate `TrainingWorker` process claims leased jobs and executes the training pipeline. Runtime and training dependencies are split into separate requirements files and container images.

## Consequences

Positive:

- training CPU/memory pressure cannot directly consume the API's executor/thread budget;
- serving image excludes MongoDB, MLflow and AWS training dependencies;
- API restarts do not erase submitted jobs;
- worker restart/crash behavior is represented explicitly by leases and attempts.

Costs:

- API and worker need shared durable control-plane state;
- job lifecycle and recovery semantics become real system concerns rather than function-call behavior;
- local deployment has two processes instead of one.

## Rejected alternative

A bounded `ThreadPoolExecutor` inside FastAPI limits concurrency but still shares the process, memory space, deployment lifecycle and failure domain with inference. It was therefore rejected as insufficient isolation.
