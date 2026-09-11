from networksecurity.config.runtime import RuntimeSettings


def test_runtime_settings_reads_typed_environment(monkeypatch):
    monkeypatch.setenv("MODEL_REGISTRY_DIR", "/tmp/models")
    monkeypatch.setenv("SCHEMA_PATH", "/tmp/schema.yaml")
    monkeypatch.setenv("TRAINING_JOB_DB_PATH", "/tmp/jobs.db")
    monkeypatch.setenv("ADMIN_API_KEY", "secret")
    monkeypatch.setenv("MAX_BATCH_SIZE", "17")
    monkeypatch.setenv("MAX_REQUEST_BYTES", "4096")
    monkeypatch.setenv("MAX_INFERENCE_CONCURRENCY", "3")
    monkeypatch.setenv("INFERENCE_ACQUIRE_TIMEOUT_MS", "125")
    monkeypatch.setenv("MAX_PENDING_TRAINING_JOBS", "7")
    monkeypatch.setenv("TRAINING_JOB_LEASE_SECONDS", "42")
    monkeypatch.setenv("TRAINING_JOB_MAX_ATTEMPTS", "5")
    monkeypatch.setenv("MODEL_REFRESH_INTERVAL_SECONDS", "2.5")
    monkeypatch.setenv("MODEL_LOAD_ON_STARTUP", "false")
    monkeypatch.setenv("SERVICE_NAME", "decision-api-test")
    monkeypatch.setenv("SERVICE_VERSION", "9.9.9")

    settings = RuntimeSettings.from_env()

    assert settings.model_registry_dir == "/tmp/models"
    assert settings.schema_path == "/tmp/schema.yaml"
    assert settings.training_job_db_path == "/tmp/jobs.db"
    assert settings.admin_api_key == "secret"
    assert settings.max_batch_size == 17
    assert settings.max_request_bytes == 4096
    assert settings.max_inference_concurrency == 3
    assert settings.inference_acquire_timeout_ms == 125
    assert settings.max_pending_training_jobs == 7
    assert settings.training_job_lease_seconds == 42
    assert settings.training_job_max_attempts == 5
    assert settings.model_refresh_interval_seconds == 2.5
    assert settings.model_load_on_startup is False
    assert settings.service_name == "decision-api-test"
    assert settings.service_version == "9.9.9"


def test_runtime_settings_uses_defaults_when_environment_is_absent(monkeypatch):
    for name in (
        "MODEL_REGISTRY_DIR",
        "SCHEMA_PATH",
        "TRAINING_JOB_DB_PATH",
        "ADMIN_API_KEY",
        "MAX_BATCH_SIZE",
        "MAX_REQUEST_BYTES",
        "MAX_INFERENCE_CONCURRENCY",
        "INFERENCE_ACQUIRE_TIMEOUT_MS",
        "MAX_PENDING_TRAINING_JOBS",
        "TRAINING_JOB_LEASE_SECONDS",
        "TRAINING_JOB_MAX_ATTEMPTS",
        "MODEL_REFRESH_INTERVAL_SECONDS",
        "MODEL_LOAD_ON_STARTUP",
        "SERVICE_NAME",
        "SERVICE_VERSION",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = RuntimeSettings.from_env()

    assert settings == RuntimeSettings()
