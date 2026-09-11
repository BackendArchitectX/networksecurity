from __future__ import annotations

import sys

import numpy as np
import pandas as pd
from sklearn.impute import KNNImputer
from sklearn.pipeline import Pipeline

from networksecurity.constant.training_pipeline import (
    DATA_TRANSFORMATION_IMPUTER_PARAMS,
    TARGET_COLUMN,
)
from networksecurity.entity.artifact_entity import DataTransformationArtifact, DataValidationArtifact
from networksecurity.entity.config_entity import DataTransformationConfig
from networksecurity.exception.exception import NetworkSecurityException
from networksecurity.logging.logger import logging
from networksecurity.utils.main_utils.utils import save_numpy_array_data, save_object


class DataTransformation:
    def __init__(
        self,
        data_validation_artifact: DataValidationArtifact,
        data_transformation_config: DataTransformationConfig,
    ):
        self.data_validation_artifact = data_validation_artifact
        self.data_transformation_config = data_transformation_config

    @staticmethod
    def read_data(file_path: str) -> pd.DataFrame:
        try:
            return pd.read_csv(file_path)
        except Exception as exc:
            raise NetworkSecurityException(exc, sys) from exc

    @staticmethod
    def get_data_transformer_object() -> Pipeline:
        try:
            return Pipeline(
                [("imputer", KNNImputer(**DATA_TRANSFORMATION_IMPUTER_PARAMS))]
            )
        except Exception as exc:
            raise NetworkSecurityException(exc, sys) from exc

    def initiate_data_transformation(self) -> DataTransformationArtifact:
        try:
            train_df = self.read_data(self.data_validation_artifact.valid_train_file_path)
            test_df = self.read_data(self.data_validation_artifact.valid_test_file_path)

            input_feature_train_df = train_df.drop(columns=[TARGET_COLUMN])
            target_feature_train_df = train_df[TARGET_COLUMN].replace(-1, 0)
            input_feature_test_df = test_df.drop(columns=[TARGET_COLUMN])
            target_feature_test_df = test_df[TARGET_COLUMN].replace(-1, 0)

            preprocessor = self.get_data_transformer_object()
            transformed_input_train_feature = preprocessor.fit_transform(input_feature_train_df)
            transformed_input_test_feature = preprocessor.transform(input_feature_test_df)

            train_arr = np.c_[transformed_input_train_feature, np.asarray(target_feature_train_df)]
            test_arr = np.c_[transformed_input_test_feature, np.asarray(target_feature_test_df)]

            save_numpy_array_data(
                self.data_transformation_config.transformed_train_file_path,
                array=train_arr,
            )
            save_numpy_array_data(
                self.data_transformation_config.transformed_test_file_path,
                array=test_arr,
            )
            save_object(
                self.data_transformation_config.transformed_object_file_path,
                preprocessor,
            )

            logging.info("data transformation completed")
            return DataTransformationArtifact(
                transformed_object_file_path=self.data_transformation_config.transformed_object_file_path,
                transformed_train_file_path=self.data_transformation_config.transformed_train_file_path,
                transformed_test_file_path=self.data_transformation_config.transformed_test_file_path,
            )
        except Exception as exc:
            raise NetworkSecurityException(exc, sys) from exc
