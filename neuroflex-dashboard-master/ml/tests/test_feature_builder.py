from django.test import SimpleTestCase

from ml.services.feature_builder import MissingFeatureError, build_features

COLUMNS = [
    "TiempoRespuestaPararse",
    "TiempoRespuestaPregunta1",
    "TiempoRespuestaPregunta2",
    "TiempoRespuestaPregunta3",
    "TiempoReaccionVisual",
    "TiempoCapturarNumero",
    "TiempoRespuestaPararse_sobre_3s",
    "TiempoRespuestaPregunta1_sobre_3s",
    "TiempoRespuestaPregunta2_sobre_3s",
    "TiempoRespuestaPregunta3_sobre_3s",
    "TiempoReaccionVisual_sobre_3s",
    "TiempoCapturarNumero_sobre_3s",
]

FULL_METRICS = {
    "TiempoRespuestaPararse": 2.5,
    "TiempoRespuestaPregunta1": 3.1,
    "TiempoRespuestaPregunta2": 3.8,
    "TiempoRespuestaPregunta3": 4.2,
    "TiempoReaccionVisual": 0.9,
    "TiempoCapturarNumero": 2.8,
}


class BuildFeaturesTests(SimpleTestCase):
    def test_builds_row_in_exact_column_order(self):
        features = build_features(FULL_METRICS, COLUMNS)

        self.assertEqual(features.shape, (1, 12))
        self.assertEqual(
            features[0].tolist(),
            [2.5, 3.0, 3.0, 3.0, 0.9, 2.8, 0, 1, 1, 1, 0, 0],
        )

    def test_values_over_3_seconds_are_capped_and_flagged(self):
        metrics = dict(FULL_METRICS, TiempoRespuestaPararse=5.0)

        features = build_features(metrics, COLUMNS)

        self.assertEqual(features[0][0], 3.0)
        self.assertEqual(features[0][6], 1)

    def test_values_at_or_under_3_seconds_are_not_flagged(self):
        metrics = dict(FULL_METRICS, TiempoRespuestaPararse=3.0)

        features = build_features(metrics, COLUMNS)

        self.assertEqual(features[0][0], 3.0)
        self.assertEqual(features[0][6], 0)

    def test_missing_single_variable_raises_with_that_variable_named(self):
        metrics = dict(FULL_METRICS)
        del metrics["TiempoReaccionVisual"]

        with self.assertRaises(MissingFeatureError) as ctx:
            build_features(metrics, COLUMNS)

        self.assertEqual(ctx.exception.missing_features, ["TiempoReaccionVisual"])

    def test_missing_multiple_variables_lists_all_of_them(self):
        metrics = {"TiempoRespuestaPararse": 2.0}

        with self.assertRaises(MissingFeatureError) as ctx:
            build_features(metrics, COLUMNS)

        self.assertEqual(
            set(ctx.exception.missing_features),
            {
                "TiempoRespuestaPregunta1",
                "TiempoRespuestaPregunta2",
                "TiempoRespuestaPregunta3",
                "TiempoReaccionVisual",
                "TiempoCapturarNumero",
            },
        )

    def test_non_numeric_value_is_treated_as_missing(self):
        metrics = dict(FULL_METRICS, TiempoCapturarNumero="not-a-number")

        with self.assertRaises(MissingFeatureError) as ctx:
            build_features(metrics, COLUMNS)

        self.assertIn("TiempoCapturarNumero", ctx.exception.missing_features)

    def test_does_not_silently_impute_missing_values(self):
        """Unlike inferencia.py's predecir(), a missing time must never
        become a silent 3.0 default here."""
        metrics = {}

        with self.assertRaises(MissingFeatureError):
            build_features(metrics, COLUMNS)
