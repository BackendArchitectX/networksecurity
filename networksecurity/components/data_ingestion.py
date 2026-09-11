from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
import pymongo
from sklearn.model_selection import train_test_split

from networksecurity.constant.training_pipeline import TARGET_COLUMN
from networksecurity.entity.artifact_entity import DataIngestionArtifact
from networksecurity.entity.config_entity import DataIngestionConfig
from networksecurity.exception.exception import NetworkSecurityException
from networksecurity.logging.logger import logging


class DataIngestion:
    def __init__(self, data_ingestion_config: DataIngestionConfig):
        self.data_ingestion_config = data_ingestion_config

    def export_collection_as_dataframe(self) -> pd.DataFrame:
        mongo_db_url = os.getenv("MONGO_DB_URL")
        if not mongo_db_url:
            raise ValueError("MONGO_DB_URL is required for training data ingestion")

        try:
            client = pymongo.MongoClient(mongo_db_url, serverSelectionTimeoutMS=5000)
            try:
                collection = client[
                    self.data_ingestion_config.database_name
                ][self.data_ingestion_config.collection_name]
                dataframe = pd.DataFrame(list(collection.find()))
            finally:
                client.close()

            if dataframe.empty:
                raise ValueError("training collection is empty")
            if "_id" in dataframe.columns:
                dataframe = dataframe.drop(columns=["_id"])
            dataframe.replace({"na": np.nan}, inplace=True)
            return dataframe
        except Exception as exc:
            raise NetworkSecurityException(exc, sys) from exc

    def export_data_into_feature_store(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        try:
            path = self.data_ingestion_config.feature_store_file_path
            os.makedirs(os.path.dirname(path), exist_ok=True)
            dataframe.to_csv(path, index=False)
            return dataframe
        except Exception as exc:
            raise NetworkSecurityException(exc, sys) from exc

    def split_data_as_train_test(self, dataframe: pd.DataFrame) -> None:
        try:
            stratify = dataframe[TARGET_COLUMN] if TARGET_COLUMN in dataframe.columns else None
            train_set, test_set = train_test_split(
                dataframe,
                test_size=self.data_ingestion_config.train_test_split_ratio,
                random_state=42,
                stratify=stratify,
            )
            os.makedirs(os.path.dirname(self.data_ingestion_config.training_file_path), exist_ok=True)
            train_set.to_csv(self.data_ingestion_config.training_file_path, index=False)
            test_set.to_csv(self.data_ingestion_config.testing_file_path, index=False)
            logging.info("training data split completed")
        except Exception as exc:
            raise NetworkSecurityException(exc, sys) from exc

    def initiate_data_ingestion(self) -> DataIngestionArtifact:
        try:
            dataframe = self.export_collection_as_dataframe()
            self.export_data_into_feature_store(dataframe)
            self.split_data_as_train_test(dataframe)
            return DataIngestionArtifact(
                trained_file_path=self.data_ingestion_config.training_file_path,
                test_file_path=self.data_ingestion_config.testing_file_path,
            )
        except Exception as exc:
            raise NetworkSecurityException(exc, sys) from exc
