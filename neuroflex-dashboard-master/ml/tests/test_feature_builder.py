import math

from django.test import SimpleTestCase

from ml.services.performance_feature_builder import (
    FEATURE_COLUMNS,
    MissingPerformanceFeatureError,
    build_performance_features,
)


FULL_METRICS = {
    "TiempoRespuestaPararse": 2.5,
    "TiempoActivoTarea": 300,
    "TiempoRespuestaPregunta1": 3.1,
    "TiempoRespuestaPregunta2": 3.8,
    "TiempoRespuestaPregunta3": 4.2,
    "TiempoCapturarNumero": 2.8,
    "TiempoTutorial": 10.0,
    "TipoEscena": 1,
}


class BuildPerformanceFeaturesTests(SimpleTestCase):
    def test_returns_raw_inputs_in_pipeline_order(self):
        features = build_performance_features(
            FULL_METRICS,
            patient_info={"dominant_hand": "right"},
        )

        self.assertEqual(list(features), FEATURE_COLUMNS)
        self.assertEqual(features["dominant_hand"], 1)
        self.assertEqual(features["TiempoActivoTarea"], 300.0)
        self.assertEqual(features["TipoEscena"], 1.0)

    def test_scene_can_be_imputed_by_frozen_pipeline(self):
        metrics = dict(FULL_METRICS)
        del metrics["TipoEscena"]

        features = build_performance_features(
            metrics,
            patient_info={"ManoPredominante": "left"},
        )

        self.assertTrue(math.isnan(features["TipoEscena"]))

    def test_missing_required_metrics_are_reported(self):
        metrics = dict(FULL_METRICS)
        del metrics["TiempoCapturarNumero"]

        with self.assertRaises(MissingPerformanceFeatureError) as ctx:
            build_performance_features(metrics, patient_info={"dominant_hand": 1})

        self.assertEqual(ctx.exception.missing_features, ["TiempoCapturarNumero"])

    def test_missing_hand_is_reported(self):
        with self.assertRaises(MissingPerformanceFeatureError) as ctx:
            build_performance_features(FULL_METRICS)

        self.assertIn("ManoPredominante", ctx.exception.missing_features)
