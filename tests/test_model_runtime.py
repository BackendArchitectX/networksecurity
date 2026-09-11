import pickle

import numpy as np
import pytest

from networksecurity.config.runtime import RuntimeSettings
from networksecurity.services.model_registry import ModelIntegrityError, ModelRegistry
from networksecurity.services.model_runtime import ModelRuntime
from networksecurity.services.schema_registry import SchemaRegistry


class IdentityPreprocessor:
    def transform(self, frame):
        return frame.to_numpy()


class ThresholdModel:
    def predict(self, values):
        return np.array([1 if row.sum() >= 2 else 0 for row in values])

    def predict_proba(self, values):
        rows = []
        for row in values:
            positive = 0.9 if row.sum() >= 2 else 0.1
            rows.append([1 - positive, positive])
        return np.array(rows)


def _write_pickle(path, value):
    with path.open("wb") as handle:
        pickle.dump(value, handle)


def test_failed_reload_retains_last_known_good_snapshot(tmp_path):
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
    model_source = tmp_path / "candidate-model.pkl"
    preprocessor_source = tmp_path / "candidate-preprocessor.pkl"
    _write_pickle(model_source, ThresholdModel())
    _write_pickle(preprocessor_source, IdentityPreprocessor())

    registry_dir = tmp_path / "registry"
    registry = ModelRegistry(str(registry_dir))
    metadata = {
        "schema_sha256": schema.schema_sha256,
        "feature_names": list(schema.feature_names),
    }
    registry.publish(
        model_source=str(model_source),
        preprocessor_source=str(preprocessor_source),
        metadata=metadata,
        version="v1",
    )

    settings = RuntimeSettings(
        model_registry_dir=str(registry_dir),
        schema_path=str(schema_path),
        training_job_db_path=str(tmp_path / "jobs.db"),
    )
    runtime = ModelRuntime(settings, schema)
    runtime.reload()

    results, version = runtime.predict_records([{"feature_a": 1, "feature_b": 1}])
    assert version == "v1"
    assert results[0] == {"prediction": 1, "confidence": 0.9}

    second = registry.publish(
        model_source=str(model_source),
        preprocessor_source=str(preprocessor_source),
        metadata=metadata,
        version="v2",
    )
    with open(second.model_path, "ab") as handle:
        handle.write(b"corruption")

    with pytest.raises(ModelIntegrityError, match="checksum mismatch"):
        runtime.reload()

    results_after_failure, version_after_failure = runtime.predict_records(
        [{"feature_a": 1, "feature_b": 1}]
    )
    assert version_after_failure == "v1"
    assert results_after_failure[0]["prediction"] == 1
