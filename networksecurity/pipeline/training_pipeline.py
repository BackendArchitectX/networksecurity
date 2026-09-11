from __future__ import annotations

import json
from pathlib import Path
import sys

from networksecurity.cloud.s3_syncer import S3Sync
from networksecurity.components.data_ingestion import DataIngestion
from networksecurity.components.data_transformation import DataTransformation
from networksecurity.components.data_validation import DataValidation
from networksecurity.components.model_trainer import ModelTrainer
from networksecurity.config.runtime import RuntimeSettings
from networksecurity.constant.training_pipeline import TRAINING_BUCKET_NAME
from networksecurity.entity.artifact_entity import (
    DataIngestionArtifact,
    DataTransformationArtifact,
    DataValidationArtifact,
    ModelTrainerArtifact,
    TrainingPipelineArtifact,
)
from networksecurity.entity.config_entity import (
    DataIngestionConfig,
    DataTransformationConfig,
    DataValidationConfig,
    ModelTrainerConfig,
    TrainingPipelineConfig,
)
from networksecurity.exception.exception import NetworkSecurityException
from networksecurity.logging.logger import logging
from networksecurity.services.model_registry import ModelBundle, ModelRegistry
from networksecurity.services.schema_registry import SchemaRegistry


class TrainingPipeline:
    def __init__(self, settings: RuntimeSettings | None = None):
        self.settings = settings or RuntimeSettings.from_env()
        self.training_pipeline_config = TrainingPipelineConfig()
        self.s3_sync = S3Sync()
        self.model_registry = ModelRegistry(self.settings.model_registry_dir)
        self.schema_registry = SchemaRegistry.from_yaml(self.settings.schema_path)

    def start_data_ingestion(self) -> DataIngestionArtifact:
        config = DataIngestionConfig(self.training_pipeline_config)
        return DataIngestion(config).initiate_data_ingestion()

    def start_data_validation(self, artifact: DataIngestionArtifact) -> DataValidationArtifact:
        config = DataValidationConfig(self.training_pipeline_config)
        return DataValidation(artifact, config).initiate_data_validation()

    def start_data_transformation(self, artifact: DataValidationArtifact) -> DataTransformationArtifact:
        config = DataTransformationConfig(self.training_pipeline_config)
        return DataTransformation(artifact, config).initiate_data_transformation()

    def start_model_trainer(self, artifact: DataTransformationArtifact) -> ModelTrainerArtifact:
        config = ModelTrainerConfig(self.training_pipeline_config)
        return ModelTrainer(config, artifact).initiate_model_trainer()

    def publish_model(
        self,
        trainer: ModelTrainerArtifact,
        transformation: DataTransformationArtifact,
    ) -> ModelBundle:
        with open(trainer.metadata_file_path, "r", encoding="utf-8") as handle:
            metadata = json.load(handle)
        metadata.update(
            {
                "training_run_id": self.training_pipeline_config.timestamp,
                "schema_sha256": self.schema_registry.schema_sha256,
                "feature_names": list(self.schema_registry.feature_names),
            }
        )
        return self.model_registry.publish(
            model_source=trainer.trained_model_file_path,
            preprocessor_source=transformation.transformed_object_file_path,
            metadata=metadata,
        )

    def _sync_outputs_if_configured(self, bundle: ModelBundle) -> None:
        if not TRAINING_BUCKET_NAME:
            logging.info("training bucket is not configured; skipping cloud artifact sync")
            return

        artifact_uri = f"s3://{TRAINING_BUCKET_NAME}/artifact/{self.training_pipeline_config.timestamp}"
        version_uri = f"s3://{TRAINING_BUCKET_NAME}/model_registry/versions/{bundle.version}"
        self.s3_sync.sync_folder_to_s3(self.training_pipeline_config.artifact_dir, artifact_uri)
        self.s3_sync.sync_folder_to_s3(str(Path(bundle.manifest_path).parent), version_uri)

        # Publish the remote pointer last so consumers never observe an incomplete bundle.
        self.s3_sync.upload_file(
            self.model_registry.current_pointer_path,
            f"s3://{TRAINING_BUCKET_NAME}/model_registry/current.json",
        )

    def run_pipeline(self) -> TrainingPipelineArtifact:
        try:
            logging.info("training pipeline started")
            ingestion = self.start_data_ingestion()
            validation = self.start_data_validation(ingestion)
            transformation = self.start_data_transformation(validation)
            trainer = self.start_model_trainer(transformation)
            bundle = self.publish_model(trainer, transformation)
            self._sync_outputs_if_configured(bundle)
            logging.info("training pipeline completed", extra={"model_version": bundle.version})
            return TrainingPipelineArtifact(
                model_version=bundle.version,
                manifest_path=bundle.manifest_path,
                model_trainer_artifact=trainer,
            )
        except Exception as exc:
            raise NetworkSecurityException(exc, sys) from exc
