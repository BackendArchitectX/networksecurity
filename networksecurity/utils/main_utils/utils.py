from __future__ import annotations

import os
import pickle
import sys
from typing import Any

import numpy as np
import yaml
from sklearn.model_selection import GridSearchCV, StratifiedKFold

from networksecurity.exception.exception import NetworkSecurityException
from networksecurity.logging.logger import logging


def read_yaml_file(file_path: str) -> dict:
    try:
        with open(file_path, "r", encoding="utf-8") as yaml_file:
            return yaml.safe_load(yaml_file)
    except Exception as exc:
        raise NetworkSecurityException(exc, sys) from exc


def write_yaml_file(file_path: str, content: object, replace: bool = False) -> None:
    try:
        if replace and os.path.exists(file_path):
            os.remove(file_path)
        directory = os.path.dirname(file_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as file:
            yaml.safe_dump(content, file, sort_keys=False)
    except Exception as exc:
        raise NetworkSecurityException(exc, sys) from exc


def save_numpy_array_data(file_path: str, array: np.ndarray) -> None:
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "wb") as file_obj:
            np.save(file_obj, array)
    except Exception as exc:
        raise NetworkSecurityException(exc, sys) from exc


def save_object(file_path: str, obj: Any) -> None:
    try:
        directory = os.path.dirname(file_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(file_path, "wb") as file_obj:
            pickle.dump(obj, file_obj)
    except Exception as exc:
        raise NetworkSecurityException(exc, sys) from exc


def load_object(file_path: str) -> Any:
    try:
        if not os.path.exists(file_path):
            raise FileNotFoundError(file_path)
        with open(file_path, "rb") as file_obj:
            return pickle.load(file_obj)
    except Exception as exc:
        raise NetworkSecurityException(exc, sys) from exc


def load_numpy_array_data(file_path: str) -> np.ndarray:
    try:
        with open(file_path, "rb") as file_obj:
            return np.load(file_obj)
    except Exception as exc:
        raise NetworkSecurityException(exc, sys) from exc


def evaluate_models(X_train, y_train, models: dict, param: dict) -> dict[str, float]:
    """Tune classifiers on training data and rank them using cross-validated F1.

    The held-out test set is deliberately not consulted here so it remains an
    unbiased final evaluation after the candidate model has been selected.
    """
    try:
        report: dict[str, float] = {}
        cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

        for name, model in models.items():
            search = GridSearchCV(
                estimator=model,
                param_grid=param.get(name, {}),
                scoring="f1",
                cv=cv,
                n_jobs=-1,
                refit=True,
            )
            search.fit(X_train, y_train)
            models[name] = search.best_estimator_
            report[name] = float(search.best_score_)
            logging.info(
                "model candidate evaluated",
                extra={"model_name": name, "cross_validated_f1": report[name]},
            )

        return report
    except Exception as exc:
        raise NetworkSecurityException(exc, sys) from exc
