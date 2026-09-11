from __future__ import annotations

from dataclasses import dataclass
import os


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return default if value is None else int(value)


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return default if value is None else float(value)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class RuntimeSettings:
    model_registry_dir: str = "model_registry"
    schema_path: str = "data_schema/schema.yaml"
    training_job_db_path: str = "runtime/training_jobs.db"
    admin_api_key: str = ""
    max_batch_size: int = 256
    max_request_bytes: int = 1_048_576
    max_inference_concurrency: int = 8
    inference_acquire_timeout_ms: int = 250
    max_pending_training_jobs: int = 32
    training_job_lease_seconds: int = 900
    training_job_max_attempts: int = 3
    model_refresh_interval_seconds: float = 5.0
    model_load_on_startup: bool = True
    service_name: str = "network-security-decision-service"
    service_version: str = "3.0.0"

    @classmethod
    def from_env(cls) -> "RuntimeSettings":
        return cls(
            model_registry_dir=os.getenv("MODEL_REGISTRY_DIR", cls.model_registry_dir),
            schema_path=os.getenv("SCHEMA_PATH", cls.schema_path),
            training_job_db_path=os.getenv("TRAINING_JOB_DB_PATH", cls.training_job_db_path),
            admin_api_key=os.getenv("ADMIN_API_KEY", ""),
            max_batch_size=_env_int("MAX_BATCH_SIZE", 256),
            max_request_bytes=_env_int("MAX_REQUEST_BYTES", 1_048_576),
            max_inference_concurrency=_env_int("MAX_INFERENCE_CONCURRENCY", 8),
            inference_acquire_timeout_ms=_env_int("INFERENCE_ACQUIRE_TIMEOUT_MS", 250),
            max_pending_training_jobs=_env_int("MAX_PENDING_TRAINING_JOBS", 32),
            training_job_lease_seconds=_env_int("TRAINING_JOB_LEASE_SECONDS", 900),
            training_job_max_attempts=_env_int("TRAINING_JOB_MAX_ATTEMPTS", 3),
            model_refresh_interval_seconds=_env_float("MODEL_REFRESH_INTERVAL_SECONDS", 5.0),
            model_load_on_startup=_env_bool("MODEL_LOAD_ON_STARTUP", True),
            service_name=os.getenv("SERVICE_NAME", "network-security-decision-service"),
            service_version=os.getenv("SERVICE_VERSION", "3.0.0"),
        )
