from pathlib import Path

from django.test import SimpleTestCase, override_settings

from ml.services.model_loader import (
    ModelArtifactsNotFoundError,
    get_model_artifacts,
    reset_model_cache,
)


class GetModelArtifactsTests(SimpleTestCase):
    databases = set()

    def setUp(self):
        reset_model_cache()

    def tearDown(self):
        reset_model_cache()

    def test_loads_weights_scaler_columns_and_metadata(self):
        artifacts = get_model_artifacts()

        self.assertEqual(len(artifacts["columns"]), 12)
        self.assertIn("dense0_W", artifacts["weights"])
        self.assertIn("bn0_gamma", artifacts["weights"])
        self.assertTrue(hasattr(artifacts["scaler"], "transform"))
        self.assertIn("nombre_modelo", artifacts["metadata"])

    def test_second_call_returns_cached_instance(self):
        first = get_model_artifacts()
        second = get_model_artifacts()

        self.assertIs(first, second)

    @override_settings(COGNITIVE_MODEL_DIR=Path("/nonexistent/model/dir"))
    def test_missing_artifacts_directory_raises(self):
        with self.assertRaises(ModelArtifactsNotFoundError):
            get_model_artifacts()
