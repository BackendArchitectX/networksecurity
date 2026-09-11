from fastapi.testclient import TestClient

from networksecurity.api.app import create_app
from networksecurity.config.runtime import RuntimeSettings


def test_health_endpoints_separate_process_liveness_from_model_readiness(tmp_path):
    schema_path = tmp_path / "schema.yaml"
    schema_path.write_text(
        """
columns:
  - feature_a: int64
  - Result: int64
""".strip(),
        encoding="utf-8",
    )

    app = create_app(
        RuntimeSettings(
            schema_path=str(schema_path),
            model_registry_dir=str(tmp_path / "registry"),
            training_job_db_path=str(tmp_path / "jobs.db"),
            model_load_on_startup=False,
            model_refresh_interval_seconds=60,
        )
    )

    with TestClient(app) as client:
        live = client.get("/health/live")
        ready = client.get("/health/ready")

    assert live.status_code == 200
    assert live.json() == {"status": "UP"}
    assert ready.status_code == 503
