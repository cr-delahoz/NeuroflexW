from unittest.mock import Mock

from django.test import TestCase

from integrations.services.neuroflex_api_client import NeuroflexApiNetworkError
from terms.models import TermsVersion
from terms.services import TermsSyncError, sync_terms_versions


class SyncTermsVersionsTests(TestCase):
    def _current_response(self, **overrides):
        entry = {
            "version_id": "0.0.1",
            "language": "es",
            "title": "Terminos y condiciones de Neuroflex VR",
            "content": "Términos de Servicio de Neuroflex VR...",
            "content_hash": "sha256-fake-1",
            "created_at": "2026-08-20T01:22:48.692267+00:00",
        }
        entry.update(overrides)
        return entry

    def test_sync_creates_current_version(self):
        client = Mock()
        client.get.return_value = self._current_response()

        summary = sync_terms_versions("fake-jwt-token", api_client=client)

        client.get.assert_called_once_with(
            "/terms/current", token="fake-jwt-token", params=None
        )
        self.assertEqual(summary, {"created": 1, "updated": 0, "unchanged": 0})
        self.assertEqual(TermsVersion.objects.count(), 1)
        terms = TermsVersion.objects.get()
        self.assertEqual(terms.version_id, "0.0.1")
        self.assertEqual(terms.language, "es")
        self.assertEqual(terms.title, "Terminos y condiciones de Neuroflex VR")
        self.assertEqual(terms.content, "Términos de Servicio de Neuroflex VR...")
        self.assertEqual(terms.content_hash, "sha256-fake-1")
        self.assertTrue(terms.published)

    def test_sync_passes_language_param(self):
        client = Mock()
        client.get.return_value = self._current_response()

        sync_terms_versions("fake-jwt-token", language="es", api_client=client)

        client.get.assert_called_once_with(
            "/terms/current", token="fake-jwt-token", params={"language": "es"}
        )

    def test_sync_defaults_language_to_es(self):
        client = Mock()
        client.get.return_value = self._current_response(language=None)

        sync_terms_versions("fake-jwt-token", api_client=client)

        self.assertEqual(TermsVersion.objects.get().language, "es")

    def test_sync_defaults_missing_language_to_es(self):
        client = Mock()
        payload = self._current_response()
        del payload["language"]
        client.get.return_value = payload

        sync_terms_versions("fake-jwt-token", api_client=client)

        self.assertEqual(TermsVersion.objects.get().language, "es")

    def test_sync_updates_when_content_hash_changes(self):
        client = Mock()
        client.get.return_value = self._current_response()
        sync_terms_versions("fake-jwt-token", api_client=client)

        client.get.return_value = self._current_response(
            content_hash="sha256-fake-2",
            title="Terminos y condiciones de Neuroflex VR (v2)",
            content="Términos de Servicio de Neuroflex VR v2...",
        )
        summary = sync_terms_versions("fake-jwt-token", api_client=client)

        self.assertEqual(summary, {"created": 0, "updated": 1, "unchanged": 0})
        self.assertEqual(TermsVersion.objects.count(), 1)
        terms = TermsVersion.objects.get()
        self.assertEqual(terms.content_hash, "sha256-fake-2")
        self.assertEqual(terms.title, "Terminos y condiciones de Neuroflex VR (v2)")
        self.assertEqual(terms.content, "Términos de Servicio de Neuroflex VR v2...")
        self.assertTrue(terms.published)

    def test_sync_leaves_unchanged_version_alone(self):
        client = Mock()
        client.get.return_value = self._current_response()
        sync_terms_versions("fake-jwt-token", api_client=client)

        summary = sync_terms_versions("fake-jwt-token", api_client=client)

        self.assertEqual(summary, {"created": 0, "updated": 0, "unchanged": 1})
        self.assertEqual(TermsVersion.objects.count(), 1)

    def test_sync_wraps_api_errors(self):
        client = Mock()
        client.get.side_effect = NeuroflexApiNetworkError("no network")

        with self.assertRaises(TermsSyncError):
            sync_terms_versions("fake-jwt-token", api_client=client)

    def test_sync_rejects_non_dict_payload(self):
        client = Mock()
        client.get.return_value = ["not", "a", "dict"]

        with self.assertRaises(TermsSyncError):
            sync_terms_versions("fake-jwt-token", api_client=client)

    def test_sync_rejects_payload_without_version_id(self):
        client = Mock()
        client.get.return_value = {"language": "es", "content": "..."}

        with self.assertRaises(TermsSyncError):
            sync_terms_versions("fake-jwt-token", api_client=client)
