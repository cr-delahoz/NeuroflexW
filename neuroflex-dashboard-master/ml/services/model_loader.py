"""Lazy loader for the frozen NeuroFlex cognitive model artifacts.

The model itself (a small Keras dense network) never runs through
TensorFlow in this project: its weights were exported offline to a plain
numpy .npz file (see ml/model_artifacts/). The scaler was migrated from
sklearn pickle → numpy .npz so the runtime only needs numpy. See
ml/mlj/neuroflex_IA-main/model.py and inferencia.py for the original
training/inference reference this was frozen from.
"""

from __future__ import annotations

import json

import numpy as np

from django.conf import settings


_CACHE = {}


class NumpyStandardScaler:
    """Pure-numpy drop-in for sklearn.preprocessing.StandardScaler.transform.

    Loaded from a pre-computed ``scaler_neuroflex.npz`` file – no sklearn
    dependency at runtime.
    """

    def __init__(self):
        self.mean_ = None
        self.scale_ = None
        self.var_ = None
        self.n_features_in_ = None
        self.feature_names_in_ = None
        self.with_mean = True
        self.with_std = True
        self.n_samples_seen_ = None

    def transform(self, X):
        """Standardise X using the fitted ``mean_`` and ``scale_``.

        Accepts 1-D (n_features,) or 2-D (n_samples, n_features) arrays.
        """
        X = np.asarray(X, dtype=float)
        if self.with_mean:
            X = X - self.mean_
        if self.with_std:
            X = X / self.scale_
        return X


class ModelLoaderError(RuntimeError):
    """Base error for cognitive model artifact loading."""


class ModelArtifactsNotFoundError(ModelLoaderError):
    """Raised when a required artifact file is missing from COGNITIVE_MODEL_DIR."""


class ModelDependencyError(ModelLoaderError):
    """Raised when a required package is not installed (kept for API compat)."""


def get_model_dir():
    """Return the configured model artifacts directory."""
    return settings.COGNITIVE_MODEL_DIR


def reset_model_cache():
    """Reset the cached artifacts for tests or controlled reloads."""
    _CACHE.clear()
    # Keep the public cache-reset hook compatible with the active ONNX model.
    from .onnx_model_loader import reset_onnx_model_cache

    reset_onnx_model_cache()


def _load_weights(model_dir):
    weights_path = model_dir / "pesos_numpy.npz"
    if not weights_path.exists():
        raise ModelArtifactsNotFoundError(
            f"Model weights file not found at '{weights_path}'."
        )
    with np.load(weights_path) as data:
        return {key: data[key] for key in data.files}


def _load_scaler(model_dir):
    scaler_path = model_dir / "scaler_neuroflex.npz"
    if not scaler_path.exists():
        raise ModelArtifactsNotFoundError(
            f"Scaler NPZ file not found at '{scaler_path}'."
            " Did you forget to run ml/model_artifacts/generate_scaler_npz.py?"
        )

    # allow_pickle=True safe: scaler_neuroflex.npz is local, version-controlled artifact
    with np.load(scaler_path, allow_pickle=True) as data:
        scaler = NumpyStandardScaler()
        scaler.mean_ = data["mean_"]
        scaler.scale_ = data["scale_"]
        scaler.var_ = data["var_"]
        scaler.n_features_in_ = int(data["n_features_in_"])
        scaler.with_mean = bool(data["with_mean"])
        scaler.with_std = bool(data["with_std"])
        scaler.feature_names_in_ = data.get("feature_names_in_", None)
        if "n_samples_seen_" in data:
            scaler.n_samples_seen_ = data["n_samples_seen_"]
        return scaler


def _load_json(model_dir, filename):
    path = model_dir / filename
    if not path.exists():
        raise ModelArtifactsNotFoundError(f"'{filename}' not found at '{path}'.")
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def get_model_artifacts():
    """Return the cached dict of {weights, scaler, columns, metadata}.

    Loaded once per process; call reset_model_cache() to force a reload.
    """
    if "artifacts" in _CACHE:
        return _CACHE["artifacts"]

    model_dir = get_model_dir()
    artifacts = {
        "weights": _load_weights(model_dir),
        "scaler": _load_scaler(model_dir),
        "columns": _load_json(model_dir, "columnas_modelo.json"),
        "metadata": _load_json(model_dir, "metadata_modelo.json"),
    }
    _CACHE["artifacts"] = artifacts
    return artifacts
