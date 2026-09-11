import json
import pickle

import pytest

from networksecurity.services.model_registry import ModelRegistry, StalePromotionError


def _write_pickle(path, value):
    with path.open("wb") as handle:
        pickle.dump(value, handle)


def _stage_pair(tmp_path, registry, version):
    model = tmp_path / f"{version}-model.pkl"
    preprocessor = tmp_path / f"{version}-preprocessor.pkl"
    _write_pickle(model, {"model": version})
    _write_pickle(preprocessor, {"preprocessor": version})
    return registry.stage(
        model_source=str(model),
        preprocessor_source=str(preprocessor),
        metadata={},
        version=version,
    )


def test_stale_fencing_token_cannot_overwrite_newer_model_pointer(tmp_path):
    registry = ModelRegistry(str(tmp_path / "registry"))
    _stage_pair(tmp_path, registry, "v1")
    _stage_pair(tmp_path, registry, "v2")

    registry.promote("v2", promotion_token=20)

    with pytest.raises(StalePromotionError, match="not newer"):
        registry.promote("v1", promotion_token=19)

    assert registry.current_version() == "v2"
    assert registry.current_promotion_token() == 20


def test_pre_fencing_pointer_is_migrated_as_generation_zero(tmp_path):
    registry = ModelRegistry(str(tmp_path / "registry"))
    _stage_pair(tmp_path, registry, "legacy")
    _stage_pair(tmp_path, registry, "fenced")

    pointer_path = tmp_path / "registry" / "current.json"
    pointer_path.write_text(
        json.dumps(
            {
                "version": "legacy",
                "manifest": "versions/legacy/manifest.json",
            }
        ),
        encoding="utf-8",
    )

    assert registry.current_version() == "legacy"
    assert registry.current_promotion_token() == 0

    registry.promote("fenced", promotion_token=1)
    assert registry.current_version() == "fenced"
    assert registry.current_promotion_token() == 1
