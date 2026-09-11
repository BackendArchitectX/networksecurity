import pickle

import numpy as np
from fastapi.testclient import TestClient

from networksecurity.api.app import create_app
from networksecurity.config.runtime import RuntimeSettings
from networksecurity.services.model_registry import ModelRegistry
from networksecurity.services.schema_registry import SchemaRegistry


class IdentityPreprocessor:
    def transform(self, frame):
        return frame.to_numpy()


class ThresholdModel:
    def predict(self, values):
        return np.array([1 if row.sum() >= 2 else 0 for row in values])

    def predict_proba(self, values):
        return np.array([[0.1, 0.9] if row.sum() >= 2 else [0.9, 0.1] for row in values])


def test_prediction_contract_includes_request_and_model_identity(tmp_path):
    schema_path = tmp_path / "schema.yaml"
    schema_path.write_text(
        """
columns:
  - feature_a: int64
  - feature_b: int64
  - Result: int64
""".strip(),
        encoding="utf-8",
    )
    schema = SchemaRegistry.from_yaml(str(schema_path))
    model_path = tmp_path / "model.pkl"
    preprocessor_path = tmp_path / "preprocessor.pkl"
    with model_path.open("wb") as handle:
        pickle.dump(ThresholdModel(), handle)
    with preprocessor_path.open("wb") as handle:
        pickle.dump(IdentityPreprocessor(), handle)

    registry_dir = tmp_path / "registry"
    ModelRegistry(str(registry_dir)).publish(
        model_source=str(model_path),
        preprocessor_source=str(preprocessor_path),
        metadata={
            "schema_sha256": schema.schema_sha256,
            "feature_names": list(schema.feature_names),
        },
        version="api-test-v1",
    )

    app = create_app(
        RuntimeSettings(
            model_registry_dir=str(registry_dir),
            training_job_db_path=str(tmp_path / "jobs.db"),
            schema_path=str(schema_path),
            model_refresh_interval_seconds=60,
        )
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/predict",
            headers={"X-Request-Id": "req-123"},
            json={"features": {"feature_a": 1, "feature_b": 1}},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["request_id"] == "req-123"
    assert body["model_version"] == "api-test-v1"
    assert body["result"] == {"prediction": 1, "confidence": 0.9}
