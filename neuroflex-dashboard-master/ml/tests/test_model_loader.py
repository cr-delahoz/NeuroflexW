from pathlib import Path
from unittest.mock import patch

import numpy as np
from django.test import SimpleTestCase, override_settings

from ml.services.performance_model_loader import (
    PerformanceModelError,
    PerformanceModelNotFoundError,
    get_performance_model_artifacts,
    reset_performance_model_cache,
)


class GetPerformanceModelArtifactsTests(SimpleTestCase):
    def setUp(self):
        reset_performance_model_cache()
        self.addCleanup(reset_performance_model_cache)

    def test_loads_frozen_three_class_pipeline(self):
        artifacts = get_performance_model_artifacts()

        self.assertEqual(len(artifacts["columns"]), 9)
        self.assertEqual(list(artifacts["model"].classes_), [0, 1, 2])
        self.assertEqual(artifacts["metadata"]["variable_objetivo"], "ObjetosInteractuadosCorrectamente")
        self.assertTrue(hasattr(artifacts["model"], "predict_proba"))

    def test_second_call_returns_cached_instance(self):
        self.assertIs(get_performance_model_artifacts(), get_performance_model_artifacts())

    @override_settings(COGNITIVE_MODEL_DIR=Path("/nonexistent/model/dir"))
    def test_missing_artifacts_directory_raises(self):
        with self.assertRaises(PerformanceModelNotFoundError):
            get_performance_model_artifacts()

    def test_rejects_binary_or_reordered_model_classes(self):
        pipeline = get_performance_model_artifacts()["model"]
        for classes in ([0, 1], [2, 1, 0]):
            with self.subTest(classes=classes):
                reset_performance_model_cache()
                with patch.object(pipeline.steps[-1][1], "classes_", np.array(classes)):
                    with patch("ml.services.performance_model_loader.joblib.load", return_value=pipeline):
                        with self.assertRaises(PerformanceModelError):
                            get_performance_model_artifacts()
