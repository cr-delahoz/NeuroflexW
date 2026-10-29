"""Critical parity test: numpy forward pass must match the original Keras model.

parity_samples.json was generated offline (see ml/model_artifacts/) by running
the frozen .keras model directly - raw_input -> Keras sigmoid probability -
so this test never needs TensorFlow itself, only the recorded outputs.
"""

import json
import warnings

from django.conf import settings
from django.test import SimpleTestCase

from ml.services.feature_builder import build_features
from ml.services.model_loader import get_model_artifacts, reset_model_cache

TOLERANCE = 1e-4


class ModelParityTests(SimpleTestCase):
    databases = set()

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        reset_model_cache()
        cls.artifacts = get_model_artifacts()
        parity_path = settings.COGNITIVE_MODEL_DIR / "parity_samples.json"
        with parity_path.open(encoding="utf-8") as f:
            cls.samples = json.load(f)

    def test_parity_samples_file_is_not_empty(self):
        self.assertGreaterEqual(len(self.samples), 20)

    def test_numpy_forward_matches_keras_probability_for_every_sample(self):
        from ml.services.inference_service import forward

        for index, sample in enumerate(self.samples):
            with self.subTest(sample=index):
                features = build_features(sample["raw_input"], self.artifacts["columns"])
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    scaled = self.artifacts["scaler"].transform(features)
                probability = float(forward(scaled, self.artifacts["weights"])[0][0])

                self.assertAlmostEqual(
                    probability, sample["probability"], delta=TOLERANCE
                )
