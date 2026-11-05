"""Recorded outputs for the frozen pipeline with no hand input."""

from django.test import SimpleTestCase

from ml.services import predict_cognitive_result, reset_performance_model_cache


class FrozenMLPRegressionTests(SimpleTestCase):
    def test_predictions_match_frozen_pipeline_without_hand_input(self):
        reset_performance_model_cache()
        self.addCleanup(reset_performance_model_cache)
        cases = [
            (
                [0.0, 288.45, 54.36, 7.07, 27.77, 33.84, 421.43],
                "medio",
                [0.02005460858226686, 0.9799453914134917, 4.24153154822313e-12],
            ),
            (
                [3.1, 22.4, 1.1, 1.3, 1.5, 2.8, 4.2],
                "alto",
                [3.1873477206574686e-08, 3.2206690953192487e-09, 0.9999999649058536],
            ),
        ]
        columns = [
            "TiempoRespuestaPararse", "TiempoActivoTarea", "TiempoRespuestaPregunta1",
            "TiempoRespuestaPregunta2", "TiempoRespuestaPregunta3",
            "TiempoCapturarNumero", "TiempoTutorial",
        ]
        for times, predicted_class, probabilities in cases:
            with self.subTest(predicted_class=predicted_class):
                metrics = dict(zip(columns, times), TipoEscena=1)
                result = predict_cognitive_result(metrics)
                self.assertTrue(result["available"])
                self.assertEqual(result["predicted_class"], predicted_class)
                for label, expected in zip(["bajo", "medio", "alto"], probabilities):
                    self.assertAlmostEqual(result["probabilities"][label], expected, delta=1e-8)
