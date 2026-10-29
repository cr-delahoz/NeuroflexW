from django.test import SimpleTestCase

from ml.services.inference_service import predict_cognitive_result
from ml.services.model_loader import reset_model_cache

FULL_METRICS = {
    "TiempoRespuestaPararse": 2.5,
    "TiempoRespuestaPregunta1": 3.1,
    "TiempoRespuestaPregunta2": 3.8,
    "TiempoRespuestaPregunta3": 4.2,
    "TiempoReaccionVisual": 0.9,
    "TiempoCapturarNumero": 2.8,
}

# Real session metrics used to validate the pipeline end-to-end (see task notes).
REAL_SESSION_METRICS = {
    "TiempoRespuestaPararse": 0.0,
    "TiempoRespuestaPregunta1": 10.23,
    "TiempoRespuestaPregunta2": 17.48,
    "TiempoRespuestaPregunta3": 8.7,
    "TiempoReaccionVisual": 0.81,
    "TiempoCapturarNumero": 9.53,
}


class PredictCognitiveResultTests(SimpleTestCase):
    databases = set()

    def setUp(self):
        reset_model_cache()

    def test_full_metrics_return_available_result_with_contract_keys(self):
        result = predict_cognitive_result(FULL_METRICS)

        self.assertTrue(result["available"])
        self.assertIn(result["predicted_class"], {"Sí", "No"})
        self.assertIsInstance(result["predicted_class_probability"], float)
        self.assertTrue(0.0 <= result["predicted_class_probability"] <= 1.0)
        self.assertTrue(result["technical_confidence_label"].endswith("%"))
        self.assertEqual(result["interpretation_status"], "legacy_unverified")
        self.assertIn(result["legacy_label"], {"Deterioro cognitivo detectado", "Sin deterioro"})
        self.assertTrue(result["model_name"])
        self.assertEqual(result["model_mode"], "legacy_provisional")
        self.assertIsNotNone(result["processed_at"])
        self.assertTrue(result["warnings"])

    def test_predicted_class_matches_probability_threshold(self):
        result = predict_cognitive_result(FULL_METRICS)

        if result["predicted_class"] == "Sí":
            self.assertGreaterEqual(result["predicted_class_probability"], 0.5)
        else:
            self.assertLess(result["predicted_class_probability"], 0.5)

    def test_missing_required_variable_returns_unavailable(self):
        metrics = dict(FULL_METRICS)
        del metrics["TiempoCapturarNumero"]

        result = predict_cognitive_result(metrics)

        self.assertFalse(result["available"])
        self.assertIn("TiempoCapturarNumero", result["user_message"])
        self.assertIn("TiempoCapturarNumero", result["missing_features"])

    def test_empty_metrics_returns_unavailable(self):
        result = predict_cognitive_result({})

        self.assertFalse(result["available"])
        self.assertTrue(result["user_message"])

    def test_none_metrics_returns_unavailable_without_raising(self):
        result = predict_cognitive_result(None)

        self.assertFalse(result["available"])

    def test_real_session_metrics_produce_available_result(self):
        result = predict_cognitive_result(REAL_SESSION_METRICS)

        self.assertTrue(result["available"])
        self.assertIn(result["predicted_class"], {"Sí", "No"})
        self.assertTrue(0.0 <= result["predicted_class_probability"] <= 1.0)
