from unittest.mock import Mock

from django.test import TestCase

from terms.models import TermsVersion
from terms.services import TermsSyncError, sync_terms_history

TOKEN = "fake-jwt-token"


def _entry(version_id="tc-1", published="true", **overrides):
    entry = {
        "version_id": version_id,
        "language": "es",
        "title": f"Terminos {version_id}",
        "content_hash": f"sha256-{version_id}",
        "created_at": "2026-10-01T12:00:00+00:00",
        "published": published,
    }
    entry.update(overrides)
    return entry


class SyncTermsHistoryTests(TestCase):
    def test_creates_mirror_rows_for_remote_history(self):
        client = Mock()
        client.get.return_value = {"versions": [_entry("tc-1"), _entry("tc-2")]}

        summary = sync_terms_history(TOKEN, api_client=client)

        self.assertEqual(summary, {"created": 2, "updated": 0, "unchanged": 0})
        self.assertEqual(TermsVersion.objects.count(), 2)
        first = TermsVersion.objects.get(version_id="tc-1")
        self.assertEqual(first.language, "es")
        self.assertEqual(first.content, "")
        self.assertTrue(first.published)

    def test_published_false_is_mirrored_as_unpublished(self):
        client = Mock()
        client.get.return_value = {"versions": [_entry("tc-1", published="false")]}

        sync_terms_history(TOKEN, api_client=client)

        self.assertFalse(TermsVersion.objects.get(version_id="tc-1").published)

    def test_hash_change_updates_and_clears_cached_content(self):
        client = Mock()
        TermsVersion.objects.create(
            version_id="tc-1",
            language="es",
            title="Viejo",
            content="Texto cacheado viejo",
            content_hash="sha256-old",
            published=True,
        )
        client.get.return_value = {"versions": [_entry("tc-1")]}

        summary = sync_terms_history(TOKEN, api_client=client)

        self.assertEqual(summary, {"created": 0, "updated": 1, "unchanged": 0})
        updated = TermsVersion.objects.get(version_id="tc-1")
        self.assertEqual(updated.content_hash, "sha256-tc-1")
        self.assertEqual(updated.content, "")
        self.assertEqual(updated.title, "Terminos tc-1")

    def test_unchanged_version_is_counted_not_updated(self):
        client = Mock()
        TermsVersion.objects.create(
            version_id="tc-1",
            language="es",
            title="Terminos tc-1",
            content="Contenido cacheado vigente",
            content_hash="sha256-tc-1",
            published=True,
        )
        client.get.return_value = {"versions": [_entry("tc-1")]}

        summary = sync_terms_history(TOKEN, api_client=client)

        self.assertEqual(summary, {"created": 0, "updated": 0, "unchanged": 1})
        self.assertEqual(
            TermsVersion.objects.get(version_id="tc-1").content,
            "Contenido cacheado vigente",
        )

    def test_removes_local_versions_missing_remotely(self):
        client = Mock()
        TermsVersion.objects.create(
            version_id="tc-removed",
            language="es",
            title="Eliminada",
            content="",
            content_hash="x",
            published=False,
        )
        client.get.return_value = {"versions": [_entry("tc-1")]}

        sync_terms_history(TOKEN, api_client=client)

        self.assertFalse(TermsVersion.objects.filter(version_id="tc-removed").exists())
        self.assertTrue(TermsVersion.objects.filter(version_id="tc-1").exists())

    def test_incomplete_payload_raises_and_touches_nothing(self):
        client = Mock()
        TermsVersion.objects.create(
            version_id="tc-1",
            language="es",
            title="Vigente",
            content="",
            content_hash="x",
            published=True,
        )
        client.get.return_value = {"versions": [{"version_id": "bad"}]}

        with self.assertRaises(TermsSyncError):
            sync_terms_history(TOKEN, api_client=client)

        self.assertEqual(TermsVersion.objects.count(), 1)

    def test_defaults_missing_language_to_es(self):
        client = Mock()
        entry = _entry("tc-1")
        del entry["language"]
        client.get.return_value = {"versions": [entry]}

        sync_terms_history(TOKEN, api_client=client)

        self.assertEqual(
            TermsVersion.objects.get(version_id="tc-1").language, "es"
        )

    def test_deletion_is_scoped_by_language(self):
        client = Mock()
        TermsVersion.objects.create(
            version_id="tc-1",
            language="en",
            title="English version",
            content="Cached english content",
            content_hash="sha256-en",
            published=True,
        )
        client.get.return_value = {"versions": [_entry("tc-1", language="es")]}

        sync_terms_history(TOKEN, api_client=client)

        english = TermsVersion.objects.get(version_id="tc-1", language="en")
        self.assertEqual(english.content, "Cached english content")
        self.assertTrue(
            TermsVersion.objects.filter(version_id="tc-1", language="es").exists()
        )
