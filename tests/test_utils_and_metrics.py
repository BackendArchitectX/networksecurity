import numpy as np
from sklearn.linear_model import LogisticRegression

from networksecurity.utils.main_utils.utils import (
    evaluate_models,
    load_numpy_array_data,
    load_object,
    read_yaml_file,
    save_numpy_array_data,
    save_object,
    write_yaml_file,
)
from networksecurity.utils.ml_utils.metric.classification_metric import get_classification_score


def test_serialization_helpers_round_trip_yaml_numpy_and_pickle(tmp_path):
    yaml_path = tmp_path / "nested" / "config.yaml"
    write_yaml_file(str(yaml_path), {"service": "networksecurity", "enabled": True})
    assert read_yaml_file(str(yaml_path)) == {"service": "networksecurity", "enabled": True}

    write_yaml_file(str(yaml_path), {"version": 2}, replace=True)
    assert read_yaml_file(str(yaml_path)) == {"version": 2}

    array_path = tmp_path / "arrays" / "sample.npy"
    array = np.array([[1.0, 2.0], [3.0, 4.0]])
    save_numpy_array_data(str(array_path), array)
    np.testing.assert_array_equal(load_numpy_array_data(str(array_path)), array)

    object_path = tmp_path / "objects" / "sample.pkl"
    value = {"model": "candidate", "score": 0.9}
    save_object(str(object_path), value)
    assert load_object(str(object_path)) == value


def test_evaluate_models_uses_stratified_cross_validated_f1():
    x_train = np.array([[float(index), float(index % 3)] for index in range(20)])
    y_train = np.array([0] * 10 + [1] * 10)
    models = {"LogisticRegression": LogisticRegression(max_iter=1000, random_state=42)}

    report = evaluate_models(
        X_train=x_train,
        y_train=y_train,
        models=models,
        param={"LogisticRegression": {"C": [0.5, 1.0]}},
    )

    assert set(report) == {"LogisticRegression"}
    assert 0.0 <= report["LogisticRegression"] <= 1.0
    assert isinstance(models["LogisticRegression"], LogisticRegression)


def test_classification_metrics_are_explicit_binary_metrics():
    metrics = get_classification_score(
        y_true=np.array([0, 1, 1, 0]),
        y_pred=np.array([0, 1, 0, 0]),
    )

    assert metrics.f1_score == 2 / 3
    assert metrics.precision_score == 1.0
    assert metrics.recall_score == 0.5
