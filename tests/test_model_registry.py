import pickle

import pytest

from networksecurity.services.model_registry import ModelRegistry, StalePromotionError


def _write_pickle(path, value):
    with path.open("wb") as handle:
        pickle.dump(value, handle)


def test_stale_fencing_token_cannot_overwrite_newer_model_pointer(tmp_path):
    model = tmp_path / "model.pkl"
    preprocessor = tmp_path / "preprocessor.pkl"
    _write_pickle(model, {"model": True})
    _write_pickle(preprocessor, {"preprocessor": True})

    registry = ModelRegistry(str(tmp_path / "registry"))
    registry.stage(
        model_source=str(model),
        preprocessor_source=str(preprocessor),
        metadata={},
        version="v1",
    )
    registry.stage(
        model_source=str(model),
        preprocessor_source=str(preprocessor),
        metadata={},
        version="v2",
    )

    registry.promote("v2", promotion_token=20)

    with pytest.raises(StalePromotionError, match="not newer"):
        registry.promote("v1", promotion_token=19)

    assert registry.current_version() == "v2"
    assert registry.current_promotion_token() == 20
