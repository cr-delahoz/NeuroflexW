from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from ml.services.inference_service import predict_cognitive_result
from ml.services.performance_model_loader import reset_performance_model_cache


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
        reset_performance_model_cache()

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

    def test_inference_is_available_without_requesting_hand(self):
        result = predict_cognitive_result(FULL_METRICS)

        self.assertTrue(result["available"])
        self.assertIn(result["predicted_class"], {"bajo", "medio", "alto"})
        self.assertAlmostEqual(sum(result["probabilities"].values()), 1.0, places=5)
        self.assertNotIn("ManoPredominante", result.get("missing_features", []))

    def test_old_hand_metadata_does_not_change_the_result(self):
        expected = predict_cognitive_result(FULL_METRICS)
        self.assertTrue(expected["available"])
        for hand in (1, 2, 3, "right", "left", "invalid"):
            with self.subTest(hand=hand):
                result = predict_cognitive_result(
                    dict(FULL_METRICS, ManoPredominante=hand),
                    {"dominant_hand": hand},
                )
                self.assertTrue(result["available"])
                self.assertEqual(result["probabilities"], expected["probabilities"])

    def test_empty_metrics_returns_unavailable(self):
        result = predict_cognitive_result({}, PATIENT_INFO)

        self.assertFalse(result["available"])
        self.assertTrue(result["user_message"])

    def test_none_metrics_returns_unavailable_without_raising(self):
        result = predict_cognitive_result(None, PATIENT_INFO)

        self.assertFalse(result["available"])

    @override_settings(COGNITIVE_MODEL_MODE="legacy_provisional")
    def test_old_configuration_cannot_select_binary_model(self):
        result = predict_cognitive_result(FULL_METRICS, PATIENT_INFO)

        self.assertTrue(result["available"])
        self.assertEqual(result["model_mode"], "three_class_objects_dropout")
        self.assertIn(result["predicted_class"], {"bajo", "medio", "alto"})

    def test_invalid_model_probabilities_return_unavailable(self):
        from ml.services.performance_model_loader import get_performance_model_artifacts

        pipeline = get_performance_model_artifacts()["model"]
        for probabilities in ([[0.3, 0.7]], [[float("nan"), 0.5, 0.5]], [[0.2, 0.2, 0.2]]):
            with self.subTest(probabilities=probabilities):
                with patch.object(pipeline, "predict_proba", return_value=probabilities):
                    result = predict_cognitive_result(FULL_METRICS, PATIENT_INFO)
                self.assertFalse(result["available"])
                self.assertNotIn("predicted_class", result)
