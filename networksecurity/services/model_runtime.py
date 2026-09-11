from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import pickle
import threading
from typing import Any, Mapping

from networksecurity.config.runtime import RuntimeSettings
from networksecurity.services.model_registry import ModelBundle, ModelRegistry, ModelRegistryEmptyError
from networksecurity.services.schema_registry import SchemaRegistry


class ModelNotReadyError(RuntimeError):
    pass


class InferenceBusyError(RuntimeError):
    pass


class ModelSchemaMismatchError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelSnapshot:
    preprocessor: Any
    model: Any
    version: str
    loaded_at: str
    metadata: dict[str, Any]
    manifest_path: str


class ModelRuntime:
    """Thread-safe serving runtime backed by immutable registry versions."""

    def __init__(self, settings: RuntimeSettings, schema: SchemaRegistry):
        self._settings = settings
        self._schema = schema
        self._registry = ModelRegistry(settings.model_registry_dir)
        self._snapshot: ModelSnapshot | None = None
        self._swap_lock = threading.RLock()
        self._reload_lock = threading.Lock()
        self._capacity = threading.BoundedSemaphore(settings.max_inference_concurrency)

    @property
    def ready(self) -> bool:
        with self._swap_lock:
            return self._snapshot is not None

    def metadata(self) -> dict[str, Any]:
        with self._swap_lock:
            snapshot = self._snapshot
        if snapshot is None:
            return {"ready": False}

        return {
            **dict(snapshot.metadata),
            "ready": True,
            "version": snapshot.version,
            "loaded_at": snapshot.loaded_at,
            "model_type": type(snapshot.model).__name__,
            "feature_count": len(self._schema.feature_names),
            "manifest_path": snapshot.manifest_path,
        }

    def reload(self) -> dict[str, Any]:
        # Serialize reloads but never block inference on registry I/O/deserialization.
        with self._reload_lock:
            bundle = self._registry.resolve_current()
            snapshot = self._load_snapshot(bundle)
            with self._swap_lock:
                self._snapshot = snapshot
        return self.metadata()

    def reload_if_changed(self) -> bool:
        current_version = self._registry.current_version()
        if current_version is None:
            return False
        with self._swap_lock:
            loaded_version = self._snapshot.version if self._snapshot else None
        if loaded_version == current_version:
            return False
        self.reload()
        return True

    def predict_records(self, records: list[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], str]:
        with self._swap_lock:
            snapshot = self._snapshot
        if snapshot is None:
            raise ModelNotReadyError("no production model is loaded")

        acquired = self._capacity.acquire(timeout=self._settings.inference_acquire_timeout_ms / 1000)
        if not acquired:
            raise InferenceBusyError("inference concurrency limit reached")

        try:
            frame = self._schema.to_frame(records)
            transformed = snapshot.preprocessor.transform(frame)
            predictions = snapshot.model.predict(transformed)

            probabilities = None
            if callable(getattr(snapshot.model, "predict_proba", None)):
                probabilities = snapshot.model.predict_proba(transformed)

            results: list[dict[str, Any]] = []
            for index, prediction in enumerate(predictions):
                confidence = None
                if probabilities is not None:
                    confidence = float(max(probabilities[index]))
                results.append({"prediction": int(prediction), "confidence": confidence})
            return results, snapshot.version
        finally:
            self._capacity.release()

    def _load_snapshot(self, bundle: ModelBundle) -> ModelSnapshot:
        published_schema_hash = bundle.metadata.get("schema_sha256")
        published_features = bundle.metadata.get("feature_names")
        if published_schema_hash != self._schema.schema_sha256:
            raise ModelSchemaMismatchError(
                "published model schema fingerprint does not match serving schema"
            )
        if published_features != list(self._schema.feature_names):
            raise ModelSchemaMismatchError(
                "published model feature order does not match serving schema"
            )

        # Pickle is loaded only after bundle checksums and schema compatibility pass.
        # The registry itself must remain a trusted internal boundary.
        with open(bundle.preprocessor_path, "rb") as handle:
            preprocessor = pickle.load(handle)
        with open(bundle.model_path, "rb") as handle:
            model = pickle.load(handle)

        if not callable(getattr(preprocessor, "transform", None)):
            raise TypeError("published preprocessor does not implement transform()")
        if not callable(getattr(model, "predict", None)):
            raise TypeError("published model does not implement predict()")

        return ModelSnapshot(
            preprocessor=preprocessor,
            model=model,
            version=bundle.version,
            loaded_at=datetime.now(timezone.utc).isoformat(),
            metadata=dict(bundle.metadata),
            manifest_path=bundle.manifest_path,
        )

    def try_load_startup_model(self) -> bool:
        try:
            self.reload()
            return True
        except ModelRegistryEmptyError:
            return False
