from __future__ import annotations

import sys

from sklearn.metrics import f1_score, precision_score, recall_score

from networksecurity.entity.artifact_entity import ClassificationMetricArtifact
from networksecurity.exception.exception import NetworkSecurityException


def get_classification_score(y_true, y_pred) -> ClassificationMetricArtifact:
    try:
        return ClassificationMetricArtifact(
            f1_score=float(f1_score(y_true, y_pred, zero_division=0)),
            precision_score=float(precision_score(y_true, y_pred, zero_division=0)),
            recall_score=float(recall_score(y_true, y_pred, zero_division=0)),
        )
    except Exception as exc:
        raise NetworkSecurityException(exc, sys) from exc
