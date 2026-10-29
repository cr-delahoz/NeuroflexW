"""Build the 12-column feature vector expected by the frozen NeuroFlex model.

Mirrors the exact preprocessing rule from
ml/mlj/neuroflex_IA-main/inferencia.py::predecir() - EXCEPT that a missing
required time variable is surfaced as a MissingFeatureError instead of being
silently imputed to 3.0, so the caller can show an honest "not available"
result rather than a made-up prediction.
"""

from __future__ import annotations

import numpy as np

REQUIRED_TIME_COLUMNS = [
    "TiempoRespuestaPararse",
    "TiempoRespuestaPregunta1",
    "TiempoRespuestaPregunta2",
    "TiempoRespuestaPregunta3",
    "TiempoReaccionVisual",
    "TiempoCapturarNumero",
]

CLINICAL_CAP_SECONDS = 3.0


class MissingFeatureError(Exception):
    """Raised when `metrics` is missing one or more required time variables."""

    def __init__(self, missing_features):
        self.missing_features = missing_features
        super().__init__(f"Missing required metrics: {', '.join(missing_features)}")


def _coerce_float(value):
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed:  # NaN
        return None
    return parsed


def build_features(metrics, columns):
    """Build a (1, len(columns)) float64 ndarray in the exact order of `columns`.

    Raises MissingFeatureError listing every required time variable that is
    absent or not a valid number in `metrics`.
    """
    metrics = metrics or {}
    missing = []
    processed = {}

    for column in REQUIRED_TIME_COLUMNS:
        value = _coerce_float(metrics.get(column))
        if value is None:
            missing.append(column)
            continue
        processed[column] = min(value, CLINICAL_CAP_SECONDS)
        processed[f"{column}_sobre_3s"] = 1 if value > CLINICAL_CAP_SECONDS else 0

    if missing:
        raise MissingFeatureError(missing)

    row = [processed[column] for column in columns]
    return np.array([row], dtype=np.float64)
