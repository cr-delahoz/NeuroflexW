"""Build raw inputs for the frozen three-class correct-object model."""

from __future__ import annotations

import math

import numpy as np


FEATURE_COLUMNS = [
    "dominant_hand",
    "TiempoRespuestaPararse",
    "TiempoActivoTarea",
    "TiempoRespuestaPregunta1",
    "TiempoRespuestaPregunta2",
    "TiempoRespuestaPregunta3",
    "TiempoCapturarNumero",
    "TiempoTutorial",
    "TipoEscena",
]

NUMERIC_FEATURE_ALIASES = {
    "TiempoRespuestaPararse": ("TiempoRespuestaPararse", "stand_response_time"),
    "TiempoActivoTarea": ("TiempoActivoTarea", "active_task_time"),
    "TiempoRespuestaPregunta1": ("TiempoRespuestaPregunta1", "question_1_response_time"),
    "TiempoRespuestaPregunta2": ("TiempoRespuestaPregunta2", "question_2_response_time"),
    "TiempoRespuestaPregunta3": ("TiempoRespuestaPregunta3", "question_3_response_time"),
    "TiempoCapturarNumero": ("TiempoCapturarNumero", "number_capture_time"),
    "TiempoTutorial": ("TiempoTutorial", "tutorial_time"),
}

class MissingPerformanceFeatureError(ValueError):
    """Raised when a required model input is missing or invalid."""

    def __init__(self, missing_features):
        self.missing_features = missing_features
        super().__init__(f"Missing model inputs: {', '.join(missing_features)}")


def _first_value(sources, names):
    for source in sources:
        if isinstance(source, dict):
            for name in names:
                if source.get(name) is not None:
                    return source[name]
    return None


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def build_performance_features(metrics, columns=None, patient_info=None):
    """Return one raw feature row in the exact order expected by the pipeline."""
    metrics = metrics or {}
    columns = columns or FEATURE_COLUMNS
    # Compatibility with the frozen pipeline's input schema only. Hand data is
    # never read from the session or requested from the specialist.
    raw = {"dominant_hand": np.nan}
    missing = []

    for column, aliases in NUMERIC_FEATURE_ALIASES.items():
        value = _number(_first_value((metrics,), aliases))
        if value is None:
            missing.append(column)
        else:
            raw[column] = value

    scene = _first_value((metrics,), ("TipoEscena", "scene_type"))
    scene_number = _number(scene)
    raw["TipoEscena"] = (
        scene_number
        if scene_number is not None
        else str(scene).strip() if scene is not None else np.nan
    )

    if missing:
        raise MissingPerformanceFeatureError(missing)
    unknown = [column for column in columns if column not in raw]
    if unknown:
        raise MissingPerformanceFeatureError(unknown)
    return {column: raw[column] for column in columns}
