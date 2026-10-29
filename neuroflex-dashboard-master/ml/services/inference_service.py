"""ONNX inference for NeuroFlex's provisional three-class performance model."""

from __future__ import annotations

import numpy as np

from .onnx_model_loader import (
    OnnxModelError,
    OnnxModelNotFoundError,
    OnnxRuntimeUnavailableError,
    get_onnx_model_artifacts,
)
from .performance_feature_builder import (
    MissingPerformanceFeatureError,
    build_performance_features,
)
from .result_interpreter import interpret_class_probabilities, interpret_probability

_BATCH_NORM_EPSILON = 1e-3


def _relu(x):
    return np.maximum(x, 0)


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def _batch_norm(x, weights, index):
    gamma = weights[f"bn{index}_gamma"]
    beta = weights[f"bn{index}_beta"]
    moving_mean = weights[f"bn{index}_mean"]
    moving_var = weights[f"bn{index}_var"]
    return gamma * (x - moving_mean) / np.sqrt(moving_var + _BATCH_NORM_EPSILON) + beta


def forward(features, weights):
    """Run the frozen network's forward pass. `features` is a (1, 12) ndarray."""
    hidden = _relu(features @ weights["dense0_W"] + weights["dense0_b"])
    hidden = _batch_norm(hidden, weights, 0)
    hidden = _relu(hidden @ weights["dense1_W"] + weights["dense1_b"])
    hidden = _batch_norm(hidden, weights, 1)
    hidden = _relu(hidden @ weights["dense2_W"] + weights["dense2_b"])
    logits = hidden @ weights["dense3_W"] + weights["dense3_b"]
    return _sigmoid(logits)


def _unavailable(user_message, *, missing_features=None):
    return {
        "available": False,
        "user_message": user_message,
        "missing_features": missing_features or [],
        "warnings": [],
    }


def predict_cognitive_result(metrics, patient_info=None):
    """Run the three-class performance model over a session's raw metrics."""
    try:
        artifacts = get_onnx_model_artifacts()
    except OnnxModelNotFoundError:
        return _unavailable(
            "El modelo de desempeño no se encuentra disponible en este entorno."
        )
    except OnnxRuntimeUnavailableError:
        return _unavailable(
            "No está instalado ONNX Runtime. Instala las dependencias del proyecto."
        )
    except OnnxModelError:
        return _unavailable("No se pudo cargar el modelo de desempeño.")

    try:
        features = build_performance_features(
            metrics,
            artifacts["metadata"]["columnas_entrada"],
            patient_info=patient_info,
        )
    except MissingPerformanceFeatureError as exc:
        return _unavailable(
            "Resultado de desempeño no disponible: faltan variables "
            f"({', '.join(exc.missing_features)}).",
            missing_features=exc.missing_features,
        )

    feeds = {}
    for name, value in features.items():
        if artifacts["input_types"][name] == "tensor(int64)":
            feeds[name] = np.asarray([[value]], dtype=np.int64)
        else:
            feeds[name] = np.asarray([[value]], dtype=np.float32)

    try:
        output_names = [item.name for item in artifacts["session"].get_outputs()]
        outputs = dict(zip(output_names, artifacts["session"].run(None, feeds)))
        class_id = int(np.asarray(outputs["label"]).reshape(-1)[0])
        probabilities = np.asarray(outputs["probabilities"], dtype=float).reshape(-1)
        return interpret_class_probabilities(
            class_id, probabilities, metadata=artifacts["metadata"]
        )
    except (KeyError, TypeError, ValueError, RuntimeError):
        return _unavailable("No se pudo ejecutar el modelo de desempeño.")
