from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DataIngestionArtifact:
    trained_file_path: str
    test_file_path: str


@dataclass(frozen=True)
class DataValidationArtifact:
    validation_status: bool
    valid_train_file_path: str
    valid_test_file_path: str
    invalid_train_file_path: str
    invalid_test_file_path: str
    drift_report_file_path: str


@dataclass(frozen=True)
class DataTransformationArtifact:
    transformed_object_file_path: str
    transformed_train_file_path: str
    transformed_test_file_path: str


@dataclass(frozen=True)
class ClassificationMetricArtifact:
    f1_score: float
    precision_score: float
    recall_score: float


@dataclass(frozen=True)
class ModelTrainerArtifact:
    trained_model_file_path: str
    metadata_file_path: str
    train_metric_artifact: ClassificationMetricArtifact
    test_metric_artifact: ClassificationMetricArtifact


@dataclass(frozen=True)
class TrainingPipelineArtifact:
    model_version: str
    manifest_path: str
    model_trainer_artifact: ModelTrainerArtifact
