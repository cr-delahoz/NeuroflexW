"""Lazy loader for the frozen dropout MLP and its metadata."""

from __future__ import annotations

import json

import joblib
import numpy as np
from django.conf import settings


_CACHE = None


class PerformanceModelError(RuntimeError):
    """Base error for the frozen performance model."""


class PerformanceModelNotFoundError(PerformanceModelError):
    """Raised when a required model artifact is missing."""


def reset_performance_model_cache():
    global _CACHE
    _CACHE = None


def get_performance_model_artifacts():
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    model_dir = settings.COGNITIVE_MODEL_DIR
    model_path = model_dir / "dropout_objects_model.joblib"
    metadata_path = model_dir / "dropout_objects_metadata.json"
    columns_path = model_dir / "dropout_objects_columns.json"
    missing = [path.name for path in (model_path, metadata_path, columns_path) if not path.is_file()]
    if missing:
        raise PerformanceModelNotFoundError(
            f"Missing frozen performance model files: {', '.join(missing)}"
        )

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        columns = json.loads(columns_path.read_text(encoding="utf-8"))
        model = joblib.load(model_path)
    except Exception as exc:
        raise PerformanceModelError("Could not load the frozen performance model.") from exc

    if columns != metadata.get("columnas_entrada"):
        raise PerformanceModelError("Model columns do not match the metadata.")
    if not hasattr(model, "predict_proba"):
        raise PerformanceModelError("Frozen model does not support predict_proba.")
    model_columns = list(getattr(model, "feature_names_in_", []))
    if model_columns and model_columns != columns:
        raise PerformanceModelError("Pipeline input columns do not match the metadata.")

    if not np.array_equal(getattr(model, "classes_", []), [0, 1, 2]):
        raise PerformanceModelError("Expected the three object-count classes in order: 0, 1, 2.")
    if metadata.get("variable_objetivo") != "ObjetosInteractuadosCorrectamente":
        raise PerformanceModelError("Expected an object-count performance model.")

    _CACHE = {"model": model, "metadata": metadata, "columns": columns}
    return _CACHE
