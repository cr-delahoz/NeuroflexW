import json
import uuid

from django.test import TestCase

from offline_mode.models import OfflineDevice, OfflineTermsAcceptance
from offline_mode.services.checksums import sha256_hex
from terms.models import TermsVersion


class LanTermsTests(TestCase):
    def setUp(self):
        self.token = "devicetoken123"
        OfflineDevice.objects.create(
            device_id=uuid.uuid4(),
            name="Q",
            device_token_hash=sha256_hex(self.token),
        )
        self.auth = {"HTTP_AUTHORIZATION": f"Bearer {self.token}"}
        self.terms = TermsVersion.objects.create(
            version_id="0.0.1",
            title="TyC",
            content="Contenido...",
            language="es",
            content_hash="a" * 64,
            published=True,
        )

    def test_current_terms(self):
        resp = self.client.get("/api/lan/terms/current", **self.auth)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["version_id"], "0.0.1")
        self.assertEqual(body["title"], "TyC")
        self.assertEqual(body["content"], "Contenido...")
        self.assertEqual(body["language"], "es")
        self.assertEqual(body["content_hash"], "a" * 64)
        self.assertEqual(body["created_at"], self.terms.created_at.isoformat())

    def test_current_terms_returns_503_when_no_terms_synced(self):
        TermsVersion.objects.all().delete()
        resp = self.client.get("/api/lan/terms/current", **self.auth)
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()["error"], "No hay términos disponibles localmente")

    def test_accept_terms_returns_uuid_token(self):
        resp = self.client.post(
            "/api/lan/terms/accept",
            data=json.dumps(
                {
                    "version_id": "0.0.1",
                    "content_hash": "a" * 64,
                    "application_version": "1.2.0",
                }
            ),
            content_type="application/json",
            **self.auth,
        )
        self.assertEqual(resp.status_code, 200)
        uuid.UUID(resp.json()["acceptance_token"])
        self.assertEqual(OfflineTermsAcceptance.objects.count(), 1)

    def test_accept_rejects_wrong_hash(self):
        resp = self.client.post(
            "/api/lan/terms/accept",
            data=json.dumps(
                {
                    "version_id": "0.0.1",
                    "content_hash": "b" * 64,
                    "application_version": "1.2.0",
                }
            ),
            content_type="application/json",
            **self.auth,
        )
        self.assertEqual(resp.status_code, 400)

    def test_accept_rejects_missing_application_version(self):
        resp = self.client.post(
            "/api/lan/terms/accept",
            data=json.dumps({"version_id": "0.0.1", "content_hash": "a" * 64}),
            content_type="application/json",
            **self.auth,
        )
        self.assertEqual(resp.status_code, 400)

    def _accept(self, payload):
        return self.client.post(
            "/api/lan/terms/accept",
            data=json.dumps(payload),
            content_type="application/json",
            **self.auth,
        )

    def test_accept_rejects_list_version_id(self):
        resp = self._accept(
            {
                "version_id": ["0.0.1"],
                "content_hash": "a" * 64,
                "application_version": "1.2.0",
            }
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "version_id inválido")
        self.assertEqual(OfflineTermsAcceptance.objects.count(), 0)

    def test_accept_rejects_dict_version_id(self):
        resp = self._accept(
            {
                "version_id": {"version": "0.0.1"},
                "content_hash": "a" * 64,
                "application_version": "1.2.0",
            }
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "version_id inválido")
        self.assertEqual(OfflineTermsAcceptance.objects.count(), 0)

    def test_accept_rejects_overlong_version_id(self):
        resp = self._accept(
            {
                "version_id": "x" * 101,
                "content_hash": "a" * 64,
                "application_version": "1.2.0",
            }
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "version_id inválido")
        self.assertEqual(OfflineTermsAcceptance.objects.count(), 0)

    def test_accept_allows_version_id_up_to_100_chars(self):
        # Alineado con TermsVersion.version_id (max_length=100): un
        # version_id de 100 caracteres se acepta y persiste.
        TermsVersion.objects.create(
            version_id="v" * 100,
            title="TyC 2",
            content="Contenido...",
            language="es",
            content_hash="a" * 64,
            published=True,
        )
        resp = self._accept(
            {
                "version_id": "v" * 100,
                "content_hash": "a" * 64,
                "application_version": "1.2.0",
            }
        )
        self.assertEqual(resp.status_code, 200)
        uuid.UUID(resp.json()["acceptance_token"])
        acceptance = OfflineTermsAcceptance.objects.get()
        self.assertEqual(acceptance.terms_version_id, "v" * 100)

    def test_accept_rejects_missing_version_id(self):
        resp = self._accept(
            {"content_hash": "a" * 64, "application_version": "1.2.0"}
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "version_id inválido")
        self.assertEqual(OfflineTermsAcceptance.objects.count(), 0)

    def test_requires_device_token(self):
        resp = self.client.get("/api/lan/terms/current")
        self.assertEqual(resp.status_code, 401)
