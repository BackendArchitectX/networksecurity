from __future__ import annotations

import os

import numpy as np

TARGET_COLUMN = "Result"
PIPELINE_NAME = "NetworkSecurity"
ARTIFACT_DIR = "artifacts"
FILE_NAME = "phishing_data.csv"
TRAIN_FILE_NAME = "train.csv"
TEST_FILE_NAME = "test.csv"
SCHEMA_FILE_PATH = os.path.join("data_schema", "schema.yaml")
MODEL_FILE_NAME = "model.pkl"

DATA_INGESTION_COLLECTION_NAME = os.getenv("DATA_INGESTION_COLLECTION_NAME", "network_events")
DATA_INGESTION_DATABASE_NAME = os.getenv("DATA_INGESTION_DATABASE_NAME", "networksecurity")
DATA_INGESTION_DIR_NAME = "data_ingestion"
DATA_INGESTION_FEATURE_STORE_DIR = "feature_store"
DATA_INGESTION_INGESTED_DIR = "ingested"
DATA_INGESTION_TRAIN_TEST_SPLIT_RATIO = 0.2

DATA_VALIDATION_DIR_NAME = "data_validation"
DATA_VALIDATION_VALID_DIR = "validated"
DATA_VALIDATION_INVALID_DIR = "invalid"
DATA_VALIDATION_DRIFT_REPORT_DIR = "drift_report"
DATA_VALIDATION_DRIFT_REPORT_FILE_NAME = "report.yaml"
PREPROCESSING_OBJECT_FILE_NAME = "preprocessing.pkl"

DATA_TRANSFORMATION_DIR_NAME = "data_transformation"
DATA_TRANSFORMATION_TRANSFORMED_DATA_DIR = "transformed"
DATA_TRANSFORMATION_TRANSFORMED_OBJECT_DIR = "transformed_object"
DATA_TRANSFORMATION_IMPUTER_PARAMS = {
    "missing_values": np.nan,
    "n_neighbors": 3,
    "weights": "uniform",
}

MODEL_TRAINER_DIR_NAME = "model_trainer"
MODEL_TRAINER_TRAINED_MODEL_DIR = "trained_model"
MODEL_TRAINER_MIN_F1 = float(os.getenv("MODEL_MIN_F1", "0.80"))

# Empty by default: local training should not unexpectedly write to a cloud account.
TRAINING_BUCKET_NAME = os.getenv("TRAINING_BUCKET_NAME", "")
