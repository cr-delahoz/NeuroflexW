"""Recorded MLP outputs must survive removal of the unused binary model."""

from django.test import SimpleTestCase

from ml.services import predict_cognitive_result, reset_performance_model_cache


class FrozenMLPRegressionTests(SimpleTestCase):
    def test_predictions_match_outputs_recorded_before_binary_model_removal(self):
        reset_performance_model_cache()
        self.addCleanup(reset_performance_model_cache)
        cases = [
            (
                [0.0, 288.45, 54.36, 7.07, 27.77, 33.84, 421.43],
                1,
                "medio",
                [0.02005460858226686, 0.9799453914134917, 4.24153154822313e-12],
            ),
            (
                [3.1, 22.4, 1.1, 1.3, 1.5, 2.8, 4.2],
                2,
                "alto",
                [4.153334401134279e-08, 3.558958758058601e-05, 0.9999643688790754],
            ),
        ]
        columns = [
            "TiempoRespuestaPararse", "TiempoActivoTarea", "TiempoRespuestaPregunta1",
            "TiempoRespuestaPregunta2", "TiempoRespuestaPregunta3",
            "TiempoCapturarNumero", "TiempoTutorial",
        ]
        for times, hand, predicted_class, probabilities in cases:
            with self.subTest(predicted_class=predicted_class):
                metrics = dict(zip(columns, times), TipoEscena=1)
                result = predict_cognitive_result(metrics, {"dominant_hand": hand})
                self.assertTrue(result["available"])
                self.assertEqual(result["predicted_class"], predicted_class)
                for label, expected in zip(["bajo", "medio", "alto"], probabilities):
                    self.assertAlmostEqual(result["probabilities"][label], expected, delta=1e-8)
