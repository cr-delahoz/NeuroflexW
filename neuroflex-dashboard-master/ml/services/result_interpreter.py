"""Presentation of the three-class correct-object model output."""

from __future__ import annotations

from django.utils import timezone


PERFORMANCE_CLASS_LABELS = {0: "bajo", 1: "medio", 2: "alto"}
PERFORMANCE_WARNING = (
    "Modelo experimental no validado clinicamente. El resultado es "
    "orientativo y no constituye un diagnostico."
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
        "legacy_label": f"Rango de objetos correctos estimado: {label}",
        "interpretation_status": "experimental_unvalidated",
        "model_name": metadata.get(
            "nombre_modelo",
            "NeuroFlex - MLP con Dropout para objetos correctos (3 clases)",
        ),
        "model_mode": "three_class_objects_dropout",
        "processed_at": timezone.now(),
        "warnings": [metadata.get("advertencia", PERFORMANCE_WARNING)],
    }
