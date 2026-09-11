from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from typing import Any, Iterable, Mapping

import pandas as pd
import yaml


class SchemaValidationError(ValueError):
    pass


@dataclass(frozen=True)
class SchemaRegistry:
    feature_names: tuple[str, ...]
    target_name: str
    schema_sha256: str

    @classmethod
    def from_yaml(cls, path: str, target_name: str = "Result") -> "SchemaRegistry":
        with open(path, "rb") as handle:
            raw_bytes = handle.read()
        raw = yaml.safe_load(raw_bytes.decode("utf-8"))
        if not isinstance(raw, dict):
            raise SchemaValidationError("schema.yaml must contain an object")

        columns = raw.get("columns", [])
        names: list[str] = []
        for item in columns:
            if not isinstance(item, dict) or len(item) != 1:
                raise SchemaValidationError("schema.yaml must define one column per mapping entry")
            names.append(next(iter(item)))

        if len(names) != len(set(names)):
            raise SchemaValidationError("schema.yaml contains duplicate columns")
        if target_name not in names:
            raise SchemaValidationError(f"target column '{target_name}' is missing from schema")

        features = tuple(name for name in names if name != target_name)
        if not features:
            raise SchemaValidationError("schema does not contain any inference features")
        return cls(
            feature_names=features,
            target_name=target_name,
            schema_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        )

    def validate_record(self, record: Mapping[str, Any]) -> dict[str, float | None]:
        actual = set(record)
        expected = set(self.feature_names)
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        if missing or unexpected:
            parts: list[str] = []
            if missing:
                parts.append(f"missing={missing}")
            if unexpected:
                parts.append(f"unexpected={unexpected}")
            raise SchemaValidationError("feature schema mismatch: " + ", ".join(parts))

        normalized: dict[str, float | None] = {}
        for name in self.feature_names:
            value = record[name]
            if value is None:
                normalized[name] = None
                continue
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise SchemaValidationError(f"feature '{name}' must be numeric or null") from exc
            if not math.isfinite(number):
                raise SchemaValidationError(f"feature '{name}' must be finite")
            normalized[name] = number
        return normalized

    def to_frame(self, records: Iterable[Mapping[str, Any]]) -> pd.DataFrame:
        normalized = [self.validate_record(record) for record in records]
        if not normalized:
            raise SchemaValidationError("at least one record is required")
        return pd.DataFrame(normalized, columns=list(self.feature_names))
