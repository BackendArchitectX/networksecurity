from fastapi.testclient import TestClient

from networksecurity.api.app import create_app
from networksecurity.config.runtime import RuntimeSettings


def _settings(tmp_path, *, admin_api_key: str = "admin-secret") -> RuntimeSettings:
    schema_path = tmp_path / "schema.yaml"
    schema_path.write_text(
        """
columns:
  - feature_a: int64
  - Result: int64
""".strip(),
        encoding="utf-8",
    )
    return RuntimeSettings(
        schema_path=str(schema_path),
        model_registry_dir=str(tmp_path / "registry"),
        training_job_db_path=str(tmp_path / "jobs.db"),
        admin_api_key=admin_api_key,
        model_load_on_startup=False,
        model_refresh_interval_seconds=60,
    )


def test_root_model_status_and_request_security_headers(tmp_path):
    app = create_app(_settings(tmp_path))

    with TestClient(app) as client:
        root = client.get("/", headers={"X-Request-Id": "control-req"})
        model = client.get("/api/v1/model")

    assert root.status_code == 200
    assert root.json()["service"] == "network-security-decision-service"
    assert root.headers["x-request-id"] == "control-req"
    assert root.headers["x-content-type-options"] == "nosniff"
    assert root.headers["cache-control"] == "no-store"
    assert model.status_code == 503
    assert model.json()["detail"] == "model not ready"


def test_admin_authentication_and_training_job_idempotency(tmp_path):
    app = create_app(_settings(tmp_path))
    submission_headers = {
        "X-Admin-Api-Key": "admin-secret",
        "Idempotency-Key": "release-2026-09-11",
    }

    with TestClient(app) as client:
        unauthorized = client.post(
            "/api/v1/training-jobs",
            headers={
                "X-Admin-Api-Key": "wrong-secret",
                "Idempotency-Key": "unauthorized-request",
            },
        )
        first = client.post("/api/v1/training-jobs", headers=submission_headers)
        duplicate = client.post("/api/v1/training-jobs", headers=submission_headers)
        job_id = first.json()["job_id"]
        fetched = client.get(
            f"/api/v1/training-jobs/{job_id}",
            headers={"X-Admin-Api-Key": "admin-secret"},
        )
        missing = client.get(
            "/api/v1/training-jobs/train_missing",
            headers={"X-Admin-Api-Key": "admin-secret"},
        )

    assert unauthorized.status_code == 401
    assert first.status_code == 202
    assert first.json()["state"] == "QUEUED"
    assert first.json()["deduplicated"] is False
    assert duplicate.status_code == 202
    assert duplicate.json()["job_id"] == job_id
    assert duplicate.json()["deduplicated"] is True
    assert fetched.status_code == 200
    assert fetched.json()["job_id"] == job_id
    assert missing.status_code == 404


def test_admin_endpoints_are_disabled_without_configured_key(tmp_path):
    app = create_app(_settings(tmp_path, admin_api_key=""))

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/training-jobs",
            headers={
                "X-Admin-Api-Key": "anything",
                "Idempotency-Key": "disabled-admin-request",
            },
        )

    assert response.status_code == 503
    assert "ADMIN_API_KEY" in response.json()["detail"]
