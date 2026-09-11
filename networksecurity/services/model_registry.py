from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import tempfile
import uuid
from typing import Any


_MANIFEST_SCHEMA_VERSION = 1
_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class ModelRegistryError(RuntimeError):
    pass


class ModelRegistryEmptyError(ModelRegistryError):
    pass


class ModelIntegrityError(ModelRegistryError):
    pass


class StalePromotionError(ModelRegistryError):
    pass


@dataclass(frozen=True)
class ModelBundle:
    version: str
    model_path: str
    preprocessor_path: str
    metadata: dict[str, Any]
    manifest_path: str


class ModelRegistry:
    """Filesystem-backed immutable model registry with fenced pointer promotion.

    Candidate bundles are staged immutably first. Promotion is a separate operation
    guarded by a monotonically increasing fencing token issued by the durable job
    store. Readers therefore observe only complete bundles, and an older worker can
    never overwrite a pointer written by a newer claim generation.
    """

    def __init__(self, root_dir: str):
        self._root = Path(root_dir)
        self._versions = self._root / "versions"
        self._current = self._root / "current.json"

    @property
    def root_dir(self) -> str:
        return str(self._root)

    @property
    def current_pointer_path(self) -> str:
        return str(self._current)

    def current_version(self) -> str | None:
        if not self._current.exists():
            return None
        pointer = self._read_current_pointer()
        return pointer["version"]

    def current_promotion_token(self) -> int | None:
        if not self._current.exists():
            return None
        pointer = self._read_current_pointer()
        return pointer["promotion_token"]

    def resolve_current(self) -> ModelBundle:
        if not self._current.exists():
            raise ModelRegistryEmptyError("model registry has no active version")

        pointer = self._read_current_pointer()
        bundle = self.resolve_version(pointer["version"])
        expected_manifest = self._safe_registry_path(pointer["manifest"])
        if Path(bundle.manifest_path).resolve() != expected_manifest.resolve():
            raise ModelIntegrityError("current model pointer references an unexpected manifest")
        return bundle

    def resolve_version(self, version: str) -> ModelBundle:
        self._validate_version(version)
        manifest_path = self._versions / version / "manifest.json"
        manifest = _read_json(manifest_path)
        if manifest.get("schema_version") != _MANIFEST_SCHEMA_VERSION:
            raise ModelIntegrityError("unsupported model manifest schema")
        if manifest.get("version") != version:
            raise ModelIntegrityError("model version and manifest version disagree")

        bundle_root = manifest_path.parent
        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, dict):
            raise ModelIntegrityError("model manifest is missing artifacts")

        model_path = self._validated_artifact(bundle_root, artifacts.get("model"), "model")
        preprocessor_path = self._validated_artifact(
            bundle_root,
            artifacts.get("preprocessor"),
            "preprocessor",
        )

        metadata = manifest.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ModelIntegrityError("model manifest metadata must be an object")

        return ModelBundle(
            version=version,
            model_path=str(model_path),
            preprocessor_path=str(preprocessor_path),
            metadata=dict(metadata),
            manifest_path=str(manifest_path),
        )

    def stage(
        self,
        *,
        model_source: str,
        preprocessor_source: str,
        metadata: dict[str, Any],
        version: str | None = None,
    ) -> ModelBundle:
        """Create and validate an immutable candidate without making it active."""
        version = version or _new_version()
        self._validate_version(version)

        model_source_path = Path(model_source)
        preprocessor_source_path = Path(preprocessor_source)
        for path in (model_source_path, preprocessor_source_path):
            if not path.is_file():
                raise FileNotFoundError(path)

        self._versions.mkdir(parents=True, exist_ok=True)
        final_dir = self._versions / version
        if final_dir.exists():
            raise ModelRegistryError(f"model version already exists: {version}")

        staging_dir = Path(tempfile.mkdtemp(prefix=f".{version}.", dir=str(self._versions)))
        try:
            model_target = staging_dir / "model.pkl"
            preprocessor_target = staging_dir / "preprocessor.pkl"
            shutil.copy2(model_source_path, model_target)
            shutil.copy2(preprocessor_source_path, preprocessor_target)

            manifest = {
                "schema_version": _MANIFEST_SCHEMA_VERSION,
                "version": version,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "artifacts": {
                    "model": {"path": model_target.name, "sha256": _sha256(model_target)},
                    "preprocessor": {
                        "path": preprocessor_target.name,
                        "sha256": _sha256(preprocessor_target),
                    },
                },
                "metadata": dict(metadata),
            }
            _write_json_fsync(staging_dir / "manifest.json", manifest)
            _fsync_directory(staging_dir)

            os.replace(staging_dir, final_dir)
            _fsync_directory(self._versions)
            return self.resolve_version(version)
        except Exception:
            if staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)
            raise

    def promote(self, version: str, *, promotion_token: int) -> ModelBundle:
        """Atomically advance the active pointer if the fencing token is newest."""
        if promotion_token < 1:
            raise ValueError("promotion_token must be a positive integer")

        bundle = self.resolve_version(version)
        if self._current.exists():
            current = self._read_current_pointer()
            if promotion_token <= current["promotion_token"]:
                raise StalePromotionError(
                    "promotion token is not newer than the active model pointer"
                )

        pointer = {
            "version": version,
            "manifest": f"versions/{version}/manifest.json",
            "promotion_token": promotion_token,
            "published_at": datetime.now(timezone.utc).isoformat(),
        }
        self._write_current_pointer(pointer)
        return self.resolve_current()

    def _read_current_pointer(self) -> dict[str, Any]:
        pointer = _read_json(self._current)
        version = pointer.get("version")
        manifest = pointer.get("manifest")
        promotion_token = pointer.get("promotion_token")
        if not isinstance(version, str) or not _VERSION_PATTERN.fullmatch(version):
            raise ModelIntegrityError("current model pointer contains an invalid version")
        if not isinstance(manifest, str):
            raise ModelIntegrityError("current model pointer is missing manifest path")
        if not isinstance(promotion_token, int) or promotion_token < 1:
            raise ModelIntegrityError("current model pointer contains an invalid promotion token")
        self._safe_registry_path(manifest)
        return {
            "version": version,
            "manifest": manifest,
            "promotion_token": promotion_token,
        }

    def _write_current_pointer(self, pointer: dict[str, Any]) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        temporary = self._root / f".current.{uuid.uuid4().hex}.tmp"
        try:
            _write_json_fsync(temporary, pointer)
            os.replace(temporary, self._current)
            _fsync_directory(self._root)
        finally:
            temporary.unlink(missing_ok=True)

    def _validated_artifact(self, bundle_root: Path, raw: Any, name: str) -> Path:
        if not isinstance(raw, dict):
            raise ModelIntegrityError(f"model manifest is missing {name} artifact")
        relative = raw.get("path")
        expected_sha = raw.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected_sha, str):
            raise ModelIntegrityError(f"invalid {name} artifact descriptor")

        path = (bundle_root / relative).resolve()
        resolved_root = bundle_root.resolve()
        if path.parent != resolved_root:
            raise ModelIntegrityError(f"{name} artifact escapes immutable bundle directory")
        if not path.is_file():
            raise ModelIntegrityError(f"{name} artifact is missing")
        actual_sha = _sha256(path)
        if not secrets.compare_digest(actual_sha, expected_sha):
            raise ModelIntegrityError(f"{name} artifact checksum mismatch")
        return path

    def _safe_registry_path(self, relative: str) -> Path:
        root = self._root.resolve()
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ModelIntegrityError("manifest path escapes model registry") from exc
        return path

    @staticmethod
    def _validate_version(version: str) -> None:
        if not _VERSION_PATTERN.fullmatch(version):
            raise ValueError("model version contains unsupported characters")


def _new_version() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    return f"{timestamp}-{uuid.uuid4().hex[:8]}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelIntegrityError(f"cannot read model registry file: {path}") from exc
    if not isinstance(value, dict):
        raise ModelIntegrityError(f"model registry file must contain an object: {path}")
    return value


def _write_json_fsync(path: Path, value: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
