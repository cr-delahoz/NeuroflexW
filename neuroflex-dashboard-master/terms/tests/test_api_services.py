from unittest.mock import Mock

from django.test import TestCase

from integrations.services.neuroflex_api_client import (
    NeuroflexApiClientError,
    NeuroflexApiNetworkError,
    NeuroflexApiResponseError,
)
from terms.services import (
    TermsPublicationForbiddenError,
    TermsSyncError,
    TermsVersionConflictError,
    TermsVersionNotFoundError,
    create_terms_version,
    fetch_terms_version,
    generate_terms_version_id,
    generate_terms_version_id_with_suffix,
    list_terms_versions,
    set_terms_publication,
)

TOKEN = "fake-jwt-token"


class ListTermsVersionsTests(TestCase):
    def test_returns_versions_list(self):
        client = Mock()
        versions = [
            {
                "version_id": "tc-2026-10-01-120000",
                "language": "es",
                "title": "Terminos y condiciones",
                "content_hash": "sha256-1",
                "created_at": "2026-10-01T12:00:00+00:00",
                "published": "true",
            }
        ]
        client.get.return_value = {"versions": versions}

        result = list_terms_versions(TOKEN, api_client=client)

        self.assertEqual(result, versions)
        client.get.assert_called_once_with("/terms/versions", token=TOKEN)

    def test_unexpected_payload_raises_terms_sync_error(self):
        client = Mock()
        client.get.return_value = {"unexpected": True}

        with self.assertRaises(TermsSyncError):
            list_terms_versions(TOKEN, api_client=client)

    def test_network_error_raises_terms_sync_error(self):
        client = Mock()
        client.get.side_effect = NeuroflexApiNetworkError("down")

        with self.assertRaises(TermsSyncError):
            list_terms_versions(TOKEN, api_client=client)


class FetchTermsVersionTests(TestCase):
    def test_returns_full_version(self):
        client = Mock()
        client.get.return_value = {
            "version_id": "tc-1",
            "language": "es",
            "title": "Terminos",
            "content": "Texto completo",
            "content_hash": "sha256-1",
            "published": "true",
        }

        result = fetch_terms_version(TOKEN, "tc-1", api_client=client)

        self.assertEqual(result["content"], "Texto completo")
        client.get.assert_called_once_with(
            "/terms/versions/tc-1", token=TOKEN, params={"language": "es"}
        )

    def test_unexpected_payload_raises_terms_sync_error(self):
        client = Mock()
        client.get.return_value = None

        with self.assertRaises(TermsSyncError):
            fetch_terms_version(TOKEN, "tc-1", api_client=client)


class CreateTermsVersionTests(TestCase):
    def _expected_body(self, **overrides):
        body = {
            "version_id": "tc-2026-10-01-120000",
            "language": "es",
            "title": "Terminos y condiciones",
            "content": "Nuevo contenido",
            "published": True,
        }
        body.update(overrides)
        return body

    def test_posts_new_version(self):
        client = Mock()
        client.post.return_value = {"version_id": "tc-1", "content_hash": "sha256-2"}

        result = create_terms_version(
            TOKEN, "tc-2026-10-01-120000", "Terminos y condiciones",
            "Nuevo contenido", api_client=client,
        )

        self.assertEqual(result["version_id"], "tc-1")
        client.post.assert_called_once_with(
            "/terms/versions", token=TOKEN, json_body=self._expected_body()
        )

    def test_conflict_maps_to_terms_version_conflict_error(self):
        client = Mock()
        client.post.side_effect = NeuroflexApiResponseError(
            "NeuroFlex API returned status 409 for '/terms/versions'.",
            status_code=409,
        )

        with self.assertRaises(TermsVersionConflictError):
            create_terms_version(
                TOKEN, "tc-dup", "Titulo", "Contenido", api_client=client
            )

    def test_other_api_error_raises_terms_sync_error(self):
        client = Mock()
        client.post.side_effect = NeuroflexApiResponseError(
            "NeuroFlex API returned status 500 for '/terms/versions'.",
            status_code=500,
        )

        with self.assertRaises(TermsSyncError):
            create_terms_version(
                TOKEN, "tc-1", "Titulo", "Contenido", api_client=client
            )

    def test_network_error_raises_terms_sync_error(self):
        client = Mock()
        client.post.side_effect = NeuroflexApiNetworkError("down")

        with self.assertRaises(TermsSyncError):
            create_terms_version(
                TOKEN, "tc-1", "Titulo", "Contenido", api_client=client
            )


class GenerateTermsVersionIdTests(TestCase):
    def test_id_has_tc_prefix_and_timestamp(self):
        version_id = generate_terms_version_id()

        self.assertRegex(version_id, r"^tc-\d{8}-\d{6}$")

    def test_suffix_variant_has_random_suffix(self):
        version_id = generate_terms_version_id_with_suffix()

        self.assertRegex(version_id, r"^tc-\d{8}-\d{6}-[0-9a-f]{4}$")


class SetTermsPublicationTests(TestCase):
    def test_sends_patch_with_language_and_published(self):
        client = Mock()
        client.patch.return_value = {"version_id": "tc-1", "published": True}

        result = set_terms_publication(TOKEN, "tc-1", api_client=client)

        self.assertEqual(result["version_id"], "tc-1")
        client.patch.assert_called_once_with(
            "/terms/versions/tc-1/publication",
            token=TOKEN,
            json_body={"language": "es", "published": True},
        )

    def test_missing_version_maps_to_not_found_error(self):
        client = Mock()
        client.patch.side_effect = NeuroflexApiResponseError(
            "NeuroFlex API returned status 404 for '/terms/versions/tc-1/publication'.",
            status_code=404,
        )

        with self.assertRaises(TermsVersionNotFoundError):
            set_terms_publication(TOKEN, "tc-1", api_client=client)

    def test_unpublish_protection_maps_to_forbidden_error(self):
        client = Mock()
        client.patch.side_effect = NeuroflexApiResponseError(
            "NeuroFlex API returned status 403 for '/terms/versions/tc-1/publication'.",
            status_code=403,
        )

        with self.assertRaises(TermsPublicationForbiddenError):
            set_terms_publication(
                TOKEN, "tc-1", published=False, api_client=client
            )

    def test_other_api_error_raises_terms_sync_error(self):
        client = Mock()
        client.patch.side_effect = NeuroflexApiResponseError(
            "NeuroFlex API returned status 500 for '/terms/versions/tc-1/publication'.",
            status_code=500,
        )

        with self.assertRaises(TermsSyncError):
            set_terms_publication(TOKEN, "tc-1", api_client=client)

    def test_network_error_raises_terms_sync_error(self):
        client = Mock()
        client.patch.side_effect = NeuroflexApiNetworkError("down")

        with self.assertRaises(TermsSyncError):
            set_terms_publication(TOKEN, "tc-1", api_client=client)
