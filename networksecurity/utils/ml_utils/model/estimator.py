from __future__ import annotations

import sys
from typing import Any

from networksecurity.exception.exception import NetworkSecurityException


class NetworkModel:
    """Compose preprocessing and prediction behind one serializable interface."""

    def __init__(self, preprocessor: Any, model: Any):
        self.preprocessor = preprocessor
        self.model = model

    def predict(self, features: Any):
        try:
            transformed = self.preprocessor.transform(features)
            return self.model.predict(transformed)
        except Exception as exc:
            raise NetworkSecurityException(exc, sys) from exc
