import json
import uuid
from unittest import mock

from django.test import TestCase

from offline_mode.models import OfflineDevice, OfflineSession, OfflineTermsAcceptance
from offline_mode.services import lan_session_service
from offline_mode.services.checksums import sha256_hex


METRICS = {
    "TiempoRespuestaPararse": 1.0,
    "Precision": 0.9,
    "TiempoActivoTarea": 30.0,
    "CantAciertasTotales": 8,
    "ObjetosInteractuadosCorrectamente": 5,
    "TiempoRespuestaPregunta1": 2.0,
    "TiempoRespuestaPregunta2": 2.1,
    "TiempoRespuestaPregunta3": 1.9,
    "TiempoCapturarNumero": 3.0,
    "TiempoTutorial": 10.0,
    "TipoEscena": 1,
}


class LanSessionsTests(TestCase):
    def setUp(self):
        self.device_token = "devicetoken123"
        self.device = OfflineDevice.objects.create(
            device_id=uuid.uuid4(),
            name="Q",
            device_token_hash=sha256_hex(self.device_token),
        )
        self.auth = {"HTTP_AUTHORIZATION": f"Bearer {self.device_token}"}
        self.acceptance = OfflineTermsAcceptance.objects.create(
            device=self.device,
            terms_version_id="0.0.1",
            content_hash="a" * 64,
            application_version="1.2.0",
        )

    def _create(self):
        return self.client.post(
            "/api/lan/sessions",
            data=json.dumps(
                {
                    "acceptance_token": str(self.acceptance.token),
                    "patient_info": {"age": 70, "dominant_hand": "right"},
                }
            ),
            content_type="application/json",
            **self.auth,
        )

    def test_create_session_returns_uuid_tokens(self):
        resp = self._create()
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        uuid.UUID(data["session_id"])
        uuid.UUID(data["metrics_token"])
        self.assertEqual(data["status"], "pending")
        self.assertTrue(
            OfflineTermsAcceptance.objects.get(pk=self.acceptance.pk).consumed
        )

    def test_create_rejects_consumed_acceptance(self):
        self._create()
        resp = self._create()
        self.assertEqual(resp.status_code, 400)

    def test_create_rejects_invalid_uuid_acceptance(self):
        resp = self.client.post(
            "/api/lan/sessions",
            data=json.dumps({"acceptance_token": "no-es-uuid"}),
            content_type="application/json",
            **self.auth,
        )
        self.assertEqual(resp.status_code, 400)

    def test_create_rejects_non_v4_acceptance_token(self):
        v1 = uuid.uuid1()
        resp = self.client.post(
            "/api/lan/sessions",
            data=json.dumps({"acceptance_token": str(v1)}),
            content_type="application/json",
            **self.auth,
        )
        self.assertEqual(resp.status_code, 400)

    def test_create_rejects_object_acceptance_token(self):
        resp = self.client.post(
            "/api/lan/sessions",
            data=json.dumps({"acceptance_token": ["x"]}),
            content_type="application/json",
            **self.auth,
        )
        self.assertEqual(resp.status_code, 400)

    def test_create_rejects_acceptance_from_other_device(self):
        """Un token de TyC aceptado en otro dispositivo no sirve para este."""
        other_device = OfflineDevice.objects.create(
            device_id=uuid.uuid4(),
            name="Otro",
            device_token_hash=sha256_hex("otro"),
        )
        other_acceptance = OfflineTermsAcceptance.objects.create(
            device=other_device,
            terms_version_id="0.0.1",
            content_hash="a" * 64,
            application_version="1.0",
        )
        resp = self.client.post(
            "/api/lan/sessions",
            data=json.dumps({"acceptance_token": str(other_acceptance.token)}),
            content_type="application/json",
            **self.auth,
        )
        self.assertEqual(resp.status_code, 400)

    def test_status_and_metrics_flow(self):
        data = self._create().json()
        sid, mtok = data["session_id"], data["metrics_token"]
        mauth = {"HTTP_X_METRICS_TOKEN": mtok}
        r = self.client.get(f"/api/lan/sessions/{sid}/status", **mauth)
        self.assertEqual(r.json()["status"], "pending")
        s = OfflineSession.objects.get(session_id=sid)
        s.status = "CONFIRMED"
        s.save()
        r = self.client.get(f"/api/lan/sessions/{sid}/status", **mauth)
        self.assertEqual(r.json()["status"], "confirmed")
        r = self.client.post(
            f"/api/lan/sessions/{sid}/metrics",
            data=json.dumps(METRICS),
            content_type="application/json",
            **mauth,
        )
        self.assertEqual(r.status_code, 200)
        s.refresh_from_db()
        self.assertEqual(s.status, "COMPLETED")
        self.assertEqual(len(s.metrics_checksum), 64)

    def test_metrics_rejected_with_wrong_token(self):
        data = self._create().json()
        s = OfflineSession.objects.get(session_id=data["session_id"])
        s.status = "CONFIRMED"
        s.save()
        r = self.client.post(
            f"/api/lan/sessions/{data['session_id']}/metrics",
            data=json.dumps(METRICS),
            content_type="application/json",
            HTTP_X_METRICS_TOKEN=str(uuid.uuid4()),
        )
        self.assertEqual(r.status_code, 401)

    def test_extra_metric_keys_rejected(self):
        data = self._create().json()
        sid, mtok = data["session_id"], data["metrics_token"]
        s = OfflineSession.objects.get(session_id=sid)
        s.status = "CONFIRMED"
        s.save()
        payload = METRICS.copy()
        payload["extra"] = 1
        resp = self.client.post(
            f"/api/lan/sessions/{sid}/metrics",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_METRICS_TOKEN=mtok,
        )
        self.assertEqual(resp.status_code, 400)

    def test_metrics_rejected_if_not_confirmed(self):
        data = self._create().json()
        r = self.client.post(
            f"/api/lan/sessions/{data['session_id']}/metrics",
            data=json.dumps(METRICS),
            content_type="application/json",
            HTTP_X_METRICS_TOKEN=data["metrics_token"],
        )
        self.assertEqual(r.status_code, 409)

    def test_pending_session_returns_409_not_400_for_incomplete_metrics(self):
        data = self._create().json()
        sid, mtok = data["session_id"], data["metrics_token"]
        payload = {"TiempoRespuestaPararse": 1.0}
        resp = self.client.post(
            f"/api/lan/sessions/{sid}/metrics",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_METRICS_TOKEN=mtok,
        )
        self.assertEqual(resp.status_code, 409)

    def test_metrics_submission_is_idempotent(self):
        data = self._create().json()
        sid, mtok = data["session_id"], data["metrics_token"]
        session = OfflineSession.objects.get(session_id=sid)
        session.status = "CONFIRMED"
        session.save()
        payload = {
            "data": json.dumps(METRICS),
            "content_type": "application/json",
            "HTTP_X_METRICS_TOKEN": mtok,
        }
        r1 = self.client.post(f"/api/lan/sessions/{sid}/metrics", **payload)
        self.assertEqual(r1.status_code, 200)
        r2 = self.client.post(f"/api/lan/sessions/{sid}/metrics", **payload)
        self.assertEqual(r2.status_code, 409)
        self.assertEqual(
            OfflineSession.objects.get(session_id=sid).status, "COMPLETED"
        )


class LanSessionAuditAtomicityTests(TestCase):
    """La mutación de OfflineSession y su auditoría fallan o exitan juntas."""

    def setUp(self):
        self.device = OfflineDevice.objects.create(
            device_id=uuid.uuid4(),
            name="Q",
            device_token_hash=sha256_hex("devicetoken123"),
        )
        self.acceptance = OfflineTermsAcceptance.objects.create(
            device=self.device,
            terms_version_id="0.0.1",
            content_hash="a" * 64,
            application_version="1.2.0",
        )

    def test_create_session_rolls_back_when_audit_fails(self):
        with mock.patch(
            "offline_mode.services.lan_session_service.log_offline_event",
            side_effect=RuntimeError("audit down"),
        ):
            with self.assertRaises(RuntimeError):
                lan_session_service.create_session(
                    device=self.device,
                    acceptance_token=str(self.acceptance.token),
                )
        self.assertFalse(OfflineSession.objects.exists())
        self.acceptance.refresh_from_db()
        self.assertFalse(self.acceptance.consumed)

    def test_save_metrics_rolls_back_when_audit_fails(self):
        result = lan_session_service.create_session(
            device=self.device, acceptance_token=str(self.acceptance.token)
        )
        session, metrics_token = result
        session.status = OfflineSession.Status.CONFIRMED
        session.save(update_fields=["status"])
        with mock.patch(
            "offline_mode.services.lan_session_service.log_offline_event",
            side_effect=RuntimeError("audit down"),
        ):
            with self.assertRaises(RuntimeError):
                lan_session_service.save_metrics(
                    str(session.session_id), metrics_token, METRICS
                )
        session.refresh_from_db()
        self.assertEqual(session.status, OfflineSession.Status.CONFIRMED)
        self.assertIsNone(session.metrics)
