"""Inference for the frozen three-class object-count MLP."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .performance_feature_builder import (
    MissingPerformanceFeatureError,
    build_performance_features,
)
from .performance_model_loader import (
    PerformanceModelError,
    PerformanceModelNotFoundError,
    get_performance_model_artifacts,
)
from .result_interpreter import interpret_class_probabilities


def _unavailable(user_message, *, missing_features=None):
    return {
        "available": False,
        "user_message": user_message,
        "missing_features": missing_features or [],
        "warnings": [],
    }


def predict_cognitive_result(metrics, patient_info=None):
    """Run the frozen three-class object-count model on raw session metrics."""
    try:
        artifacts = get_performance_model_artifacts()
    except PerformanceModelNotFoundError:
        return _unavailable(
            "El modelo de objetos correctos no se encuentra disponible en este entorno."
        )
    except PerformanceModelError:
        return _unavailable("No se pudo cargar el modelo de objetos correctos.")

    try:
        features = build_performance_features(
            metrics,
            artifacts["columns"],
            patient_info=patient_info,
        )
    except MissingPerformanceFeatureError as exc:
        return _unavailable(
            "Resultado de desempeño no disponible: faltan variables "
            f"({', '.join(exc.missing_features)}).",
            missing_features=exc.missing_features,
        )

    try:
        model_input = pd.DataFrame([features], columns=artifacts["columns"])
        probabilities = np.asarray(
            artifacts["model"].predict_proba(model_input), dtype=float
        ).reshape(-1)
        if (
            probabilities.shape != (3,)
            or not np.all(np.isfinite(probabilities))
            or np.any(probabilities < 0)
            or np.any(probabilities > 1)
            or not np.isclose(probabilities.sum(), 1.0)
        ):
            return _unavailable("El modelo no devolvio probabilidades validas para las tres clases.")
        class_id = int(np.argmax(probabilities))
        return interpret_class_probabilities(
            class_id, probabilities, metadata=artifacts["metadata"]
        )
    except (KeyError, TypeError, ValueError, RuntimeError, AttributeError):
        return _unavailable("No se pudo ejecutar el modelo de objetos correctos.")
