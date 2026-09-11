from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import sys

import mlflow
from sklearn.ensemble import AdaBoostClassifier, GradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeClassifier

from networksecurity.entity.artifact_entity import DataTransformationArtifact, ModelTrainerArtifact
from networksecurity.entity.config_entity import ModelTrainerConfig
from networksecurity.exception.exception import NetworkSecurityException
from networksecurity.logging.logger import logging
from networksecurity.utils.main_utils.utils import evaluate_models, load_numpy_array_data, save_object
from networksecurity.utils.ml_utils.metric.classification_metric import get_classification_score


class ModelTrainer:
    def __init__(self, model_trainer_config: ModelTrainerConfig, data_transformation_artifact: DataTransformationArtifact):
        self.model_trainer_config = model_trainer_config
        self.data_transformation_artifact = data_transformation_artifact

    def _track_mlflow(self, model, metrics, phase: str, model_name: str) -> None:
        tracking_uri = os.getenv("MLFLOW_TRACKING_URI")
        if not tracking_uri:
            return

        mlflow.set_tracking_uri(tracking_uri)
        mlflow.set_experiment(os.getenv("MLFLOW_EXPERIMENT_NAME", "networksecurity"))
        with mlflow.start_run(run_name=f"{model_name}-{phase}"):
            mlflow.log_param("model_name", model_name)
            mlflow.log_param("phase", phase)
            mlflow.log_metric("f1", metrics.f1_score)
            mlflow.log_metric("precision", metrics.precision_score)
            mlflow.log_metric("recall", metrics.recall_score)
            mlflow.sklearn.log_model(model, artifact_path="model")

    def train_model(self, x_train, y_train, x_test, y_test) -> ModelTrainerArtifact:
        try:
            models = {
                "RandomForest": RandomForestClassifier(
                    n_jobs=-1,
                    class_weight="balanced",
                    random_state=42,
                ),
                "DecisionTree": DecisionTreeClassifier(class_weight="balanced", random_state=42),
                "GradientBoosting": GradientBoostingClassifier(random_state=42),
                "LogisticRegression": LogisticRegression(
                    max_iter=2000,
                    class_weight="balanced",
                    random_state=42,
                ),
                "AdaBoost": AdaBoostClassifier(random_state=42),
            }
            params = {
                "DecisionTree": {"criterion": ["gini", "entropy", "log_loss"]},
                "RandomForest": {"n_estimators": [64, 128, 256]},
                "GradientBoosting": {
                    "learning_rate": [0.03, 0.05, 0.1],
                    "subsample": [0.75, 0.9, 1.0],
                    "n_estimators": [64, 128, 256],
                },
                "LogisticRegression": {"C": [0.25, 1.0, 4.0]},
                "AdaBoost": {"learning_rate": [0.03, 0.1, 0.5], "n_estimators": [64, 128, 256]},
            }

            cross_validated_f1 = evaluate_models(
                X_train=x_train,
                y_train=y_train,
                models=models,
                param=params,
            )
            best_model_name = max(cross_validated_f1, key=cross_validated_f1.get)
            best_model = models[best_model_name]

            train_metrics = get_classification_score(y_true=y_train, y_pred=best_model.predict(x_train))
            test_metrics = get_classification_score(y_true=y_test, y_pred=best_model.predict(x_test))

            if test_metrics.f1_score < self.model_trainer_config.minimum_f1:
                raise ValueError(
                    f"candidate model rejected: F1={test_metrics.f1_score:.4f} "
                    f"is below required {self.model_trainer_config.minimum_f1:.4f}"
                )

            self._track_mlflow(best_model, train_metrics, "train", best_model_name)
            self._track_mlflow(best_model, test_metrics, "test", best_model_name)

            save_object(self.model_trainer_config.trained_model_file_path, best_model)
            metadata = {
                "model_name": best_model_name,
                "trained_at": datetime.now(timezone.utc).isoformat(),
                "selection_metric": "cross_validated_f1",
                "cross_validated_f1": float(cross_validated_f1[best_model_name]),
                "test_f1": float(test_metrics.f1_score),
                "test_precision": float(test_metrics.precision_score),
                "test_recall": float(test_metrics.recall_score),
            }
            os.makedirs(os.path.dirname(self.model_trainer_config.metadata_file_path), exist_ok=True)
            with open(self.model_trainer_config.metadata_file_path, "w", encoding="utf-8") as handle:
                json.dump(metadata, handle, indent=2, sort_keys=True)
                handle.write("\n")

            artifact = ModelTrainerArtifact(
                trained_model_file_path=self.model_trainer_config.trained_model_file_path,
                metadata_file_path=self.model_trainer_config.metadata_file_path,
                train_metric_artifact=train_metrics,
                test_metric_artifact=test_metrics,
            )
            logging.info("model candidate accepted", extra={"model_name": best_model_name})
            return artifact
        except Exception as exc:
            raise NetworkSecurityException(exc, sys) from exc

    def initiate_model_trainer(self) -> ModelTrainerArtifact:
        try:
            train_arr = load_numpy_array_data(self.data_transformation_artifact.transformed_train_file_path)
            test_arr = load_numpy_array_data(self.data_transformation_artifact.transformed_test_file_path)
            x_train, y_train = train_arr[:, :-1], train_arr[:, -1]
            x_test, y_test = test_arr[:, :-1], test_arr[:, -1]
            return self.train_model(x_train, y_train, x_test, y_test)
        except Exception as exc:
            raise NetworkSecurityException(exc, sys) from exc
