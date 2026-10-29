"""Presentation-layer interpretation of the cognitive model's raw probability."""

from __future__ import annotations

from django.utils import timezone


PERFORMANCE_CLASS_LABELS = {0: "bajo", 1: "medio", 2: "alto"}
PERFORMANCE_WARNING = (
    "Modelo experimental sin validacion clinica. En la prueba guardada no "
    "identifico ejemplos de la clase medio. No es un diagnostico."
)


def interpret_class_probabilities(class_id, class_probabilities, *, metadata=None):
    """Format the three-class performance prediction for the app and reports."""
    metadata = metadata or {}
    label = PERFORMANCE_CLASS_LABELS.get(int(class_id))
    if label is None:
        raise ValueError(f"Unexpected performance class: {class_id}")

    probabilities = {
        PERFORMANCE_CLASS_LABELS[index]: float(class_probabilities[index])
        for index in range(len(PERFORMANCE_CLASS_LABELS))
    }
    probability_labels = {
        label: f"{probability * 100:.1f}%"
        for label, probability in probabilities.items()
    }
    probability = probabilities[label]
    return {
        "available": True,
        "predicted_class": label,
        "classes": list(PERFORMANCE_CLASS_LABELS.values()),
        "probabilities": probabilities,
        "probability_labels": probability_labels,
        "predicted_class_probability": probability,
        "technical_confidence_label": f"{probability * 100:.1f}%",
        "legacy_label": f"Banda de desempeno estimada: {label}",
        "interpretation_status": "experimental_unvalidated",
        "model_name": metadata.get(
            "nombre_modelo", "NeuroFlex - Clasificador de banda de desempeño (3 clases)"
        ),
        "model_mode": "three_class_provisional",
        "processed_at": timezone.now(),
        "warnings": [metadata.get("advertencia", PERFORMANCE_WARNING)],
    }

THRESHOLD = 0.5

DISCLAIMER = (
    "Resultado provisional generado por un modelo heredado entrenado "
    "mayormente con datos sinteticos (accuracy ~85% sobre test sintetico, "
    "sin validacion clinica). No constituye un diagnostico."
)


def interpret_probability(probability, *, metadata=None):
    """Build the SessionDetailView/PDF presentation contract from a raw probability."""
    metadata = metadata or {}
    predicted_positive = probability >= THRESHOLD
    predicted_class = "Sí" if predicted_positive else "No"
    confidence = probability if predicted_positive else (1 - probability)

    return {
        "available": True,
        "predicted_class": predicted_class,
        "predicted_class_probability": probability,
        "technical_confidence_label": f"{confidence * 100:.1f}%",
        "interpretation_status": "legacy_unverified",
        "legacy_label": (
            "Deterioro cognitivo detectado" if predicted_positive else "Sin deterioro"
        ),
        "model_name": metadata.get(
            "nombre_modelo", "NeuroFlex - Clasificador Deterioro Cognitivo"
        ),
        "model_mode": "legacy_provisional",
        "processed_at": timezone.now(),
        "warnings": [DISCLAIMER],
    }
