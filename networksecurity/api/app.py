from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging
import secrets
import time
import uuid

from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, make_asgi_app

from networksecurity.api.contracts import (
    BatchPredictionRequest,
    BatchPredictionResponse,
    PredictionItem,
    PredictionRequest,
    PredictionResponse,
    TrainingJobResponse,
)
from networksecurity.api.middleware import RequestBodyLimitMiddleware
from networksecurity.config.runtime import RuntimeSettings
from networksecurity.services.model_runtime import InferenceBusyError, ModelNotReadyError, ModelRuntime
from networksecurity.services.schema_registry import SchemaRegistry, SchemaValidationError
from networksecurity.services.training_jobs import TrainingJob, TrainingJobStore, TrainingQueueFullError


LOG = logging.getLogger(__name__)


def create_app(settings: RuntimeSettings | None = None) -> FastAPI:
    settings = settings or RuntimeSettings.from_env()
    schema = SchemaRegistry.from_yaml(settings.schema_path)
    runtime = ModelRuntime(settings=settings, schema=schema)
    jobs = TrainingJobStore(
        settings.training_job_db_path,
        max_pending_jobs=settings.max_pending_training_jobs,
        max_attempts=settings.training_job_max_attempts,
    )

    registry = CollectorRegistry()
    requests_total = Counter(
        "http_requests_total",
        "HTTP requests by method, route and status",
        ["method", "route", "status"],
        registry=registry,
    )
    request_latency = Histogram(
        "http_request_duration_seconds",
        "HTTP request latency",
        ["method", "route"],
        registry=registry,
    )
    inference_latency = Histogram(
        "inference_duration_seconds",
        "Model inference latency",
        registry=registry,
    )
    inference_inflight = Gauge(
        "inference_inflight",
        "Inference requests currently executing or waiting for the runtime bulkhead",
        registry=registry,
    )
    model_ready = Gauge("model_ready", "Whether a production model is loaded", registry=registry)
    model_reload_total = Counter(
        "model_reload_total",
        "Model reload attempts by outcome",
        ["outcome"],
        registry=registry,
    )

    async def refresh_model_loop() -> None:
        while True:
            await asyncio.sleep(settings.model_refresh_interval_seconds)
            try:
                changed = await run_in_threadpool(runtime.reload_if_changed)
                if changed:
                    model_reload_total.labels("success").inc()
                    LOG.info("serving model refreshed", extra={"model_version": runtime.metadata()["version"]})
                model_ready.set(1 if runtime.ready else 0)
            except asyncio.CancelledError:
                raise
            except Exception:
                model_reload_total.labels("failure").inc()
                model_ready.set(1 if runtime.ready else 0)
                LOG.exception("background model refresh rejected; last-known-good snapshot retained")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if settings.model_load_on_startup:
            try:
                loaded = await run_in_threadpool(runtime.try_load_startup_model)
                model_ready.set(1 if loaded else 0)
            except Exception:
                model_ready.set(0)
                LOG.exception("model startup load failed; process remains live but unready")
        refresh_task = asyncio.create_task(refresh_model_loop(), name="model-registry-refresh")
        try:
            yield
        finally:
            refresh_task.cancel()
            try:
                await refresh_task
            except asyncio.CancelledError:
                pass

    app = FastAPI(
        title="Network Security Decision Service",
        version=settings.service_version,
        description=(
            "Versioned threat-scoring serving plane backed by immutable model bundles "
            "and a durable asynchronous training control plane."
        ),
        lifespan=lifespan,
    )
    app.add_middleware(RequestBodyLimitMiddleware, max_bytes=settings.max_request_bytes)
    app.state.settings = settings
    app.state.schema = schema
    app.state.runtime = runtime
    app.state.training_jobs = jobs

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = request_id

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            route = _route_template(request)
            elapsed = time.perf_counter() - started
            requests_total.labels(request.method, route, "500").inc()
            request_latency.labels(request.method, route).observe(elapsed)
            raise

        route = _route_template(request)
        elapsed = time.perf_counter() - started
        requests_total.labels(request.method, route, str(response.status_code)).inc()
        request_latency.labels(request.method, route).observe(elapsed)
        response.headers["X-Request-Id"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    app.mount("/metrics", make_asgi_app(registry=registry))

    def require_admin(x_admin_api_key: str | None) -> None:
        if not settings.admin_api_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="administrative API is disabled until ADMIN_API_KEY is configured",
            )
        if x_admin_api_key is None or not secrets.compare_digest(x_admin_api_key, settings.admin_api_key):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid admin API key")

    @app.get("/")
    async def root() -> dict[str, str]:
        return {
            "service": settings.service_name,
            "version": settings.service_version,
            "docs": "/docs",
            "health": "/health/ready",
        }

    @app.get("/health/live")
    async def liveness() -> dict[str, str]:
        return {"status": "UP"}

    @app.get("/health/ready")
    async def readiness():
        if not runtime.ready:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="model not ready")
        return {"status": "READY", "model": runtime.metadata()}

    @app.get("/api/v1/model")
    async def model_metadata():
        metadata = runtime.metadata()
        if not metadata["ready"]:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="model not ready")
        return metadata

    @app.post("/api/v1/predict", response_model=PredictionResponse)
    async def predict(payload: PredictionRequest, request: Request):
        started = time.perf_counter()
        inference_inflight.inc()
        try:
            results, version = await run_in_threadpool(runtime.predict_records, [payload.features])
        except SchemaValidationError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        except ModelNotReadyError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
        except InferenceBusyError as exc:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
        finally:
            inference_inflight.dec()
        elapsed = time.perf_counter() - started
        inference_latency.observe(elapsed)
        return PredictionResponse(
            request_id=request.state.request_id,
            model_version=version,
            latency_ms=round(elapsed * 1000, 3),
            result=PredictionItem(**results[0]),
        )

    @app.post("/api/v1/predict/batch", response_model=BatchPredictionResponse)
    async def predict_batch(payload: BatchPredictionRequest, request: Request):
        if len(payload.records) > settings.max_batch_size:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"batch size exceeds configured maximum of {settings.max_batch_size}",
            )
        started = time.perf_counter()
        inference_inflight.inc()
        try:
            results, version = await run_in_threadpool(runtime.predict_records, payload.records)
        except SchemaValidationError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        except ModelNotReadyError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
        except InferenceBusyError as exc:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
        finally:
            inference_inflight.dec()
        elapsed = time.perf_counter() - started
        inference_latency.observe(elapsed)
        return BatchPredictionResponse(
            request_id=request.state.request_id,
            model_version=version,
            latency_ms=round(elapsed * 1000, 3),
            results=[PredictionItem(**item) for item in results],
        )

    @app.post("/api/v1/model/reload")
    async def reload_model(x_admin_api_key: str | None = Header(default=None, alias="X-Admin-Api-Key")):
        require_admin(x_admin_api_key)
        try:
            metadata = await run_in_threadpool(runtime.reload)
            model_ready.set(1)
            model_reload_total.labels("success").inc()
            return metadata
        except Exception as exc:
            model_ready.set(1 if runtime.ready else 0)
            model_reload_total.labels("failure").inc()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"reload rejected: {exc}") from exc

    @app.post("/api/v1/training-jobs", response_model=TrainingJobResponse, status_code=status.HTTP_202_ACCEPTED)
    async def create_training_job(
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
        x_admin_api_key: str | None = Header(default=None, alias="X-Admin-Api-Key"),
    ):
        require_admin(x_admin_api_key)
        try:
            job, created = await run_in_threadpool(jobs.submit, idempotency_key)
        except TrainingQueueFullError as exc:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
        return _job_response(job, deduplicated=not created)

    @app.get("/api/v1/training-jobs/{job_id}", response_model=TrainingJobResponse)
    async def get_training_job(
        job_id: str,
        x_admin_api_key: str | None = Header(default=None, alias="X-Admin-Api-Key"),
    ):
        require_admin(x_admin_api_key)
        job = await run_in_threadpool(jobs.get, job_id)
        if job is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="training job not found")
        return _job_response(job, deduplicated=False)

    return app


def _job_response(job: TrainingJob, *, deduplicated: bool) -> TrainingJobResponse:
    return TrainingJobResponse(
        job_id=job.job_id,
        state=job.state.value,
        submitted_at=job.submitted_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        attempts=job.attempts,
        model_version=job.model_version,
        error=job.error,
        deduplicated=deduplicated,
    )


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    return getattr(route, "path", request.url.path)
