"""Lazy loader for the bundled multiclass ONNX performance model."""

from __future__ import annotations

import json

from django.conf import settings


_CACHE = None


class OnnxModelError(RuntimeError):
    """Base error for loading or running the ONNX model."""


class OnnxModelNotFoundError(OnnxModelError):
    """Raised when the ONNX file or its metadata is missing."""


class OnnxRuntimeUnavailableError(OnnxModelError):
    """Raised when ONNX Runtime is not installed."""


def reset_onnx_model_cache():
    global _CACHE
    _CACHE = None


def get_onnx_model_artifacts():
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    model_dir = settings.COGNITIVE_MODEL_DIR
    model_path = model_dir / "neuroflex_3classes_model.onnx"
    metadata_path = model_dir / "neuroflex_3classes_metadata.json"
    if not model_path.exists():
        raise OnnxModelNotFoundError(f"ONNX model not found at '{model_path}'.")
    if not metadata_path.exists():
        raise OnnxModelNotFoundError(f"ONNX metadata not found at '{metadata_path}'.")

    try:
        import onnxruntime as ort
    except ImportError as exc:
        raise OnnxRuntimeUnavailableError(
            "ONNX Runtime is required. Install the project requirements."
        ) from exc

    try:
        with metadata_path.open(encoding="utf-8") as file:
            metadata = json.load(file)
        session = ort.InferenceSession(
            str(model_path), providers=["CPUExecutionProvider"]
        )
    except (OSError, ValueError, RuntimeError) as exc:
        raise OnnxModelError("Could not initialize the ONNX model artifacts.") from exc
    runtime_inputs = {item.name: item.type for item in session.get_inputs()}
    expected_inputs = metadata["columnas_entrada"]
    if set(runtime_inputs) != set(expected_inputs):
        raise OnnxModelError(
            "ONNX model inputs do not match the bundled feature metadata."
        )
    if {item.name for item in session.get_outputs()} != {"label", "probabilities"}:
        raise OnnxModelError("ONNX model output contract is not supported.")

    _CACHE = {
        "session": session,
        "metadata": metadata,
        "input_types": runtime_inputs,
    }
    return _CACHE
