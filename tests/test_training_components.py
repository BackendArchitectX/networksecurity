from types import SimpleNamespace

import numpy as np
import pandas as pd

from networksecurity.components.data_ingestion import DataIngestion
from networksecurity.components.data_transformation import DataTransformation
from networksecurity.components.data_validation import DataValidation
from networksecurity.entity.artifact_entity import DataIngestionArtifact
from networksecurity.entity.config_entity import (
    DataIngestionConfig,
    DataTransformationConfig,
    DataValidationConfig,
    ModelTrainerConfig,
    TrainingPipelineConfig,
)


def test_data_ingestion_reads_mongo_writes_feature_store_and_stratified_split(tmp_path, monkeypatch):
    records = [
        {"_id": index, "feature": index, "Result": -1 if index % 2 == 0 else 1}
        for index in range(20)
    ]

    class FakeCollection:
        def find(self):
            return list(records)

    class FakeDatabase:
        def __getitem__(self, _name):
            return FakeCollection()

    class FakeClient:
        closed = False

        def __getitem__(self, _name):
            return FakeDatabase()

        def close(self):
            self.closed = True

    client = FakeClient()
    monkeypatch.setenv("MONGO_DB_URL", "mongodb://unit-test")
    monkeypatch.setattr(
        "networksecurity.components.data_ingestion.pymongo.MongoClient",
        lambda *_args, **_kwargs: client,
    )

    config = SimpleNamespace(
        database_name="networksecurity",
        collection_name="network_events",
        feature_store_file_path=str(tmp_path / "feature-store" / "data.csv"),
        training_file_path=str(tmp_path / "ingested" / "train.csv"),
        testing_file_path=str(tmp_path / "ingested" / "test.csv"),
        train_test_split_ratio=0.25,
    )
    artifact = DataIngestion(config).initiate_data_ingestion()

    feature_store = pd.read_csv(config.feature_store_file_path)
    train = pd.read_csv(artifact.trained_file_path)
    test = pd.read_csv(artifact.test_file_path)

    assert client.closed is True
    assert "_id" not in feature_store.columns
    assert len(feature_store) == 20
    assert len(train) == 15
    assert len(test) == 5
    assert set(train["Result"]) == {-1, 1}
    assert set(test["Result"]) == {-1, 1}


def test_validation_and_transformation_execute_real_file_contract(tmp_path):
    ingestion = DataIngestionArtifact(
        trained_file_path=str(tmp_path / "source-train.csv"),
        test_file_path=str(tmp_path / "source-test.csv"),
    )
    validation_config = SimpleNamespace(
        valid_train_file_path=str(tmp_path / "validated" / "train.csv"),
        valid_test_file_path=str(tmp_path / "validated" / "test.csv"),
        invalid_train_file_path=str(tmp_path / "invalid" / "train.csv"),
        invalid_test_file_path=str(tmp_path / "invalid" / "test.csv"),
        drift_report_file_path=str(tmp_path / "diagnostics" / "split.yaml"),
    )
    validator = DataValidation(ingestion, validation_config)

    rows = 12
    frame = pd.DataFrame(
        {
            column: [float((row + index) % 3 - 1) for row in range(rows)]
            for index, column in enumerate(validator._expected_columns)
        }
    )
    frame["Result"] = [-1, 1] * (rows // 2)
    frame.iloc[:8].to_csv(ingestion.trained_file_path, index=False)
    frame.iloc[8:].to_csv(ingestion.test_file_path, index=False)

    validated = validator.initiate_data_validation()
    assert validated.validation_status is True
    assert pd.read_csv(validated.valid_train_file_path).shape[0] == 8
    assert pd.read_csv(validated.valid_test_file_path).shape[0] == 4
    report = (tmp_path / "diagnostics" / "split.yaml").read_text(encoding="utf-8")
    assert "train_test_split_consistency_diagnostic" in report
    assert "gates_training: false" in report

    transformation_config = SimpleNamespace(
        transformed_train_file_path=str(tmp_path / "transformed" / "train.npy"),
        transformed_test_file_path=str(tmp_path / "transformed" / "test.npy"),
        transformed_object_file_path=str(tmp_path / "transformed" / "preprocessor.pkl"),
    )
    transformed = DataTransformation(validated, transformation_config).initiate_data_transformation()

    train_array = np.load(transformed.transformed_train_file_path)
    test_array = np.load(transformed.transformed_test_file_path)
    assert train_array.shape[1] == len(validator._expected_columns)
    assert test_array.shape[1] == len(validator._expected_columns)
    assert set(np.unique(train_array[:, -1])).issubset({0.0, 1.0})


def test_validation_rejects_bad_schema_and_bad_target(tmp_path):
    validator = DataValidation(
        DataIngestionArtifact("unused-train.csv", "unused-test.csv"),
        SimpleNamespace(drift_report_file_path=str(tmp_path / "report.yaml")),
    )
    valid = pd.DataFrame({column: [1, 1] for column in validator._expected_columns})
    valid["Result"] = [-1, 1]

    missing = valid.drop(columns=[validator._expected_columns[0]])
    try:
        validator.validate_dataset(missing)
    except ValueError as exc:
        assert "schema mismatch" in str(exc)
    else:
        raise AssertionError("missing feature must be rejected")

    invalid_target = valid.copy()
    invalid_target["Result"] = [0, 1]
    try:
        validator.validate_dataset(invalid_target)
    except ValueError as exc:
        assert "unsupported labels" in str(exc)
    else:
        raise AssertionError("unsupported target must be rejected")


def test_pipeline_config_entities_derive_isolated_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pipeline = TrainingPipelineConfig()
    ingestion = DataIngestionConfig(pipeline)
    validation = DataValidationConfig(pipeline)
    transformation = DataTransformationConfig(pipeline)
    trainer = ModelTrainerConfig(pipeline)

    assert pipeline.artifact_dir.startswith("artifacts/")
    assert ingestion.training_file_path.endswith("data_ingestion/ingested/train.csv")
    assert validation.valid_test_file_path.endswith("data_validation/validated/test.csv")
    assert transformation.transformed_object_file_path.endswith("transformed_object/preprocessing.pkl")
    assert trainer.trained_model_file_path.endswith("model_trainer/trained_model/model.pkl")
    assert trainer.metadata_file_path.endswith("model_trainer/metadata.json")
