from __future__ import annotations

import math
import os
import sys

import pandas as pd
from scipy.stats import ks_2samp

from networksecurity.constant.training_pipeline import SCHEMA_FILE_PATH, TARGET_COLUMN
from networksecurity.entity.artifact_entity import DataIngestionArtifact, DataValidationArtifact
from networksecurity.entity.config_entity import DataValidationConfig
from networksecurity.exception.exception import NetworkSecurityException
from networksecurity.logging.logger import logging
from networksecurity.utils.main_utils.utils import read_yaml_file, write_yaml_file


class DataValidation:
    def __init__(self, data_ingestion_artifact: DataIngestionArtifact, data_validation_config: DataValidationConfig):
        try:
            self.data_ingestion_artifact = data_ingestion_artifact
            self.data_validation_config = data_validation_config
            self._schema_config = read_yaml_file(SCHEMA_FILE_PATH)
            self._expected_columns = [next(iter(item)) for item in self._schema_config.get("columns", [])]
        except Exception as exc:
            raise NetworkSecurityException(exc, sys) from exc

    @staticmethod
    def read_data(file_path: str) -> pd.DataFrame:
        try:
            return pd.read_csv(file_path)
        except Exception as exc:
            raise NetworkSecurityException(exc, sys) from exc

    def validate_dataset(self, dataframe: pd.DataFrame) -> None:
        actual = list(dataframe.columns)
        missing = sorted(set(self._expected_columns) - set(actual))
        unexpected = sorted(set(actual) - set(self._expected_columns))
        if missing or unexpected:
            raise ValueError(f"schema mismatch: missing={missing}, unexpected={unexpected}")
        if len(actual) != len(self._expected_columns) or len(actual) != len(set(actual)):
            raise ValueError("dataset contains duplicate or malformed columns")
        if dataframe.empty:
            raise ValueError("dataset is empty")

        for column in self._expected_columns:
            numeric = pd.to_numeric(dataframe[column], errors="coerce")
            invalid_non_null = dataframe[column].notna() & numeric.isna()
            if invalid_non_null.any():
                raise ValueError(f"column '{column}' contains non-numeric values")
            finite_values = numeric.dropna()
            if not finite_values.map(math.isfinite).all():
                raise ValueError(f"column '{column}' contains non-finite values")

        if dataframe[TARGET_COLUMN].isna().any():
            raise ValueError("target column contains missing values")
        target_values = set(pd.to_numeric(dataframe[TARGET_COLUMN]).astype(int).unique())
        if not target_values.issubset({-1, 1}):
            raise ValueError(f"target column contains unsupported labels: {sorted(target_values)}")

    def write_split_consistency_report(
        self,
        train_df: pd.DataFrame,
        test_df: pd.DataFrame,
        threshold: float = 0.05,
    ) -> None:
        """Write a diagnostic comparison of the random train/test split.

        This is intentionally not called production drift detection and does not gate
        the pipeline. A p-value below the threshold can occur by chance when many
        independent features are tested.
        """
        try:
            report: dict[str, object] = {
                "kind": "train_test_split_consistency_diagnostic",
                "threshold": threshold,
                "gates_training": False,
                "features": {},
            }
            features: dict[str, dict[str, float | bool | int]] = {}
            numerical_columns = [
                column
                for column in self._schema_config.get("numerical_columns", [])
                if column != TARGET_COLUMN and column in train_df.columns and column in test_df.columns
            ]

            for column in numerical_columns:
                train = pd.to_numeric(train_df[column], errors="coerce").dropna()
                test = pd.to_numeric(test_df[column], errors="coerce").dropna()
                if train.empty or test.empty:
                    features[column] = {
                        "train_samples": int(len(train)),
                        "test_samples": int(len(test)),
                        "p_value": 0.0,
                        "below_threshold": True,
                    }
                    continue
                result = ks_2samp(train, test)
                features[column] = {
                    "train_samples": int(len(train)),
                    "test_samples": int(len(test)),
                    "p_value": float(result.pvalue),
                    "below_threshold": bool(result.pvalue < threshold),
                }

            report["features"] = features
            report_path = self.data_validation_config.drift_report_file_path
            os.makedirs(os.path.dirname(report_path), exist_ok=True)
            write_yaml_file(file_path=report_path, content=report, replace=True)
        except Exception as exc:
            raise NetworkSecurityException(exc, sys) from exc

    def initiate_data_validation(self) -> DataValidationArtifact:
        try:
            train_dataframe = self.read_data(self.data_ingestion_artifact.trained_file_path)
            test_dataframe = self.read_data(self.data_ingestion_artifact.test_file_path)

            self.validate_dataset(train_dataframe)
            self.validate_dataset(test_dataframe)
            self.write_split_consistency_report(train_dataframe, test_dataframe)

            os.makedirs(os.path.dirname(self.data_validation_config.valid_train_file_path), exist_ok=True)
            train_dataframe.to_csv(self.data_validation_config.valid_train_file_path, index=False)
            test_dataframe.to_csv(self.data_validation_config.valid_test_file_path, index=False)

            logging.info("data validation completed")
            return DataValidationArtifact(
                validation_status=True,
                valid_train_file_path=self.data_validation_config.valid_train_file_path,
                valid_test_file_path=self.data_validation_config.valid_test_file_path,
                invalid_train_file_path=self.data_validation_config.invalid_train_file_path,
                invalid_test_file_path=self.data_validation_config.invalid_test_file_path,
                drift_report_file_path=self.data_validation_config.drift_report_file_path,
            )
        except Exception as exc:
            raise NetworkSecurityException(exc, sys) from exc
