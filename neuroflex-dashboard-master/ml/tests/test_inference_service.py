from django.test import SimpleTestCase

from ml.services.inference_service import predict_cognitive_result
from ml.services.model_loader import reset_model_cache


FULL_METRICS = {
    "TiempoRespuestaPararse": 0.0,
    "TiempoActivoTarea": 288.45,
    "TiempoRespuestaPregunta1": 54.36,
    "TiempoRespuestaPregunta2": 7.07,
    "TiempoRespuestaPregunta3": 27.77,
    "TiempoCapturarNumero": 33.84,
    "TiempoTutorial": 421.43,
    "TipoEscena": 1,
}
PATIENT_INFO = {"dominant_hand": 1}


class PredictCognitiveResultTests(SimpleTestCase):
    databases = set()

    def setUp(self):
        reset_model_cache()

    def test_returns_three_class_result_with_contract_keys(self):
        result = predict_cognitive_result(FULL_METRICS, PATIENT_INFO)

        self.assertTrue(result["available"])
        self.assertIn(result["predicted_class"], {"bajo", "medio", "alto"})
        self.assertEqual(set(result["probabilities"]), {"bajo", "medio", "alto"})
        self.assertIsInstance(result["predicted_class_probability"], float)
        self.assertAlmostEqual(sum(result["probabilities"].values()), 1.0, places=5)
        self.assertEqual(result["model_mode"], "three_class_objects_dropout")
        self.assertEqual(result["interpretation_status"], "experimental_unvalidated")
        self.assertIn("objetos correctos", result["legacy_label"])
        self.assertTrue(result["warnings"])

    def test_missing_required_variable_returns_unavailable(self):
        metrics = dict(FULL_METRICS)
        del metrics["TiempoCapturarNumero"]

        result = predict_cognitive_result(metrics, PATIENT_INFO)

        self.assertFalse(result["available"])
        self.assertIn("TiempoCapturarNumero", result["user_message"])
        self.assertIn("TiempoCapturarNumero", result["missing_features"])

    def test_missing_hand_returns_unavailable(self):
        result = predict_cognitive_result(FULL_METRICS)

        self.assertFalse(result["available"])
        self.assertIn("ManoPredominante", result["missing_features"])

    def test_empty_metrics_returns_unavailable(self):
        result = predict_cognitive_result({}, PATIENT_INFO)

        self.assertFalse(result["available"])
        self.assertTrue(result["user_message"])

    def test_none_metrics_returns_unavailable_without_raising(self):
        result = predict_cognitive_result(None, PATIENT_INFO)

        self.assertFalse(result["available"])
