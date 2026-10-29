"""Build the inputs expected by the three-class performance ONNX model."""

from __future__ import annotations

import math

import numpy as np


FEATURE_COLUMNS = [
    "dominant_hand",
    "TiempoRespuestaPararse",
    "TiempoActivoTarea",
    "CantAciertasTotales",
    "ObjetosInteractuadosCorrectamente",
    "TiempoRespuestaPregunta1",
    "TiempoRespuestaPregunta2",
    "TiempoRespuestaPregunta3",
    "TiempoCapturarNumero",
    "TiempoTutorial",
    "TipoEscena",
    "tiempo_total",
    "ratio_aciertos",
    "TiempoRespuestaPararse_log",
    "TiempoActivoTarea_log",
    "TiempoTutorial_log",
    "TiempoRespuestaPregunta1_log",
    "TiempoRespuestaPregunta2_log",
    "TiempoRespuestaPregunta3_log",
]

METRIC_ALIASES = {
    "TiempoRespuestaPararse": ("TiempoRespuestaPararse", "stand_response_time"),
    "TiempoActivoTarea": ("TiempoActivoTarea", "active_task_time"),
    "CantAciertasTotales": ("CantAciertasTotales", "total_correct_answers"),
    "ObjetosInteractuadosCorrectamente": (
        "ObjetosInteractuadosCorrectamente",
        "correct_interacted_objects",
    ),
    "TiempoRespuestaPregunta1": ("TiempoRespuestaPregunta1", "question_1_response_time"),
    "TiempoRespuestaPregunta2": ("TiempoRespuestaPregunta2", "question_2_response_time"),
    "TiempoRespuestaPregunta3": ("TiempoRespuestaPregunta3", "question_3_response_time"),
    "TiempoCapturarNumero": ("TiempoCapturarNumero", "number_capture_time"),
    "TiempoTutorial": ("TiempoTutorial", "tutorial_time"),
    "TipoEscena": ("TipoEscena", "scene_type"),
}

TIME_COLUMNS = (
    "TiempoRespuestaPararse",
    "TiempoActivoTarea",
    "TiempoTutorial",
    "TiempoRespuestaPregunta1",
    "TiempoRespuestaPregunta2",
    "TiempoRespuestaPregunta3",
)

HAND_CODES = {
    "right": 1,
    "left": 2,
    "ambidextrous": 3,
    "1": 1,
    "1.0": 1,
    "2": 2,
    "2.0": 2,
    "3": 3,
    "3.0": 3,
}


class MissingPerformanceFeatureError(ValueError):
    """Raised when a required model input is absent or invalid."""

    def __init__(self, missing_features):
        self.missing_features = missing_features
        super().__init__(f"Missing model inputs: {', '.join(missing_features)}")


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _first_value(sources, names):
    for source in sources:
        if not isinstance(source, dict):
            continue
        for name in names:
            if source.get(name) is not None:
                return source[name]
    return None


def _dominant_hand(metrics, patient_info):
    value = _first_value(
        (patient_info, metrics),
        ("dominant_hand", "ManoPredominante", "dominantHand"),
    )
    if value is None:
        return None
    return HAND_CODES.get(str(value).strip().lower())


def build_performance_features(metrics, columns=None, patient_info=None):
    """Return one row of feature values in the exact ONNX input order.

    This mirrors the training notebook's feature engineering. Preprocessing
    learned during training (imputation, scaling, and one-hot encoding) remains
    inside the exported ONNX graph.
    """
    metrics = metrics or {}
    columns = columns or FEATURE_COLUMNS
    raw = {}
    missing = []

    hand = _dominant_hand(metrics, patient_info)
    if hand is None:
        missing.append("ManoPredominante")
    else:
        raw["dominant_hand"] = hand

    for column, aliases in METRIC_ALIASES.items():
        value = _number(_first_value((metrics,), aliases))
        if value is None:
            missing.append(column)
        else:
            raw[column] = value

    if missing:
        raise MissingPerformanceFeatureError(missing)

    raw["tiempo_total"] = (
        raw["TiempoRespuestaPararse"]
        + raw["TiempoActivoTarea"]
        + raw["TiempoTutorial"]
    )
    raw["ratio_aciertos"] = raw["CantAciertasTotales"] / (
        raw["ObjetosInteractuadosCorrectamente"] + 1
    )
    for column in TIME_COLUMNS:
        raw[f"{column}_log"] = float(np.log1p(max(raw[column], 0.0)))

    unknown = [column for column in columns if column not in raw]
    if unknown:
        raise MissingPerformanceFeatureError(unknown)
    return {column: raw[column] for column in columns}
