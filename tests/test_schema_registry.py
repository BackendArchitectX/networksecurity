import pytest

from networksecurity.services.schema_registry import SchemaRegistry, SchemaValidationError


def test_schema_registry_preserves_feature_order_and_rejects_shape_mismatch(tmp_path):
    schema_file = tmp_path / "schema.yaml"
    schema_file.write_text(
        """
columns:
  - feature_a: int64
  - feature_b: int64
  - Result: int64
""".strip(),
        encoding="utf-8",
    )

    registry = SchemaRegistry.from_yaml(str(schema_file))
    frame = registry.to_frame([{"feature_b": 2, "feature_a": 1}])

    assert list(frame.columns) == ["feature_a", "feature_b"]
    assert frame.iloc[0].tolist() == [1.0, 2.0]

    with pytest.raises(SchemaValidationError, match="missing"):
        registry.to_frame([{"feature_a": 1}])

    with pytest.raises(SchemaValidationError, match="unexpected"):
        registry.to_frame([{"feature_a": 1, "feature_b": 2, "extra": 3}])
