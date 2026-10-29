import uuid
from datetime import timedelta
from unittest.mock import Mock, patch

from audit.models import AuditLog
from django.contrib.auth import get_user_model
from django.db import OperationalError
from django.test import TestCase
from django.utils import timezone

from offline_mode.models import OfflineDevice, OfflineSession
from offline_mode.services.checksums import compute_metrics_checksum, sha256_hex
from offline_mode.services.sync_service import SyncService, UserInactiveError
from terms.models import TermsVersion


User = get_user_model()
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


def _completed_session(owner, **kwargs):
    device = OfflineDevice.objects.create(
        device_id=uuid.uuid4(),
        name="Q",
        device_token_hash=sha256_hex("t"),
        paired_by=owner,
    )
    defaults = dict(
        device=device,
        specialist=owner,
        status="COMPLETED",
        terms_version_id="0.0.1",
        terms_content_hash="a" * 64,
        terms_accepted_at=timezone.now(),
        acceptance_token=uuid.uuid4(),
        metrics_token_hash=sha256_hex("m"),
        metrics=METRICS,
        metrics_checksum=compute_metrics_checksum(METRICS),
        completed_at=timezone.now(),
    )
    defaults.update(kwargs)
    return OfflineSession.objects.create(**defaults)


class SyncServiceTests(TestCase):
    def setUp(self):
        TermsVersion.objects.create(
            version_id="0.0.1",
            title="T",
            content="c",
            language="es",
            content_hash="a" * 64,
            published=True,
        )
        self.user = User.objects.create_user(username="esp", role="SPECIALIST")

    def _service(self, status_code=201):
        client = Mock()
        client.post.return_value = Mock(status_code=status_code)
        return SyncService(api_client=client), client

    def test_successful_sync_deletes_local_session(self):
        session = _completed_session(self.user)
        service, _ = self._service(201)
        results = service.sync_all(user=self.user, id_token="tok")
        self.assertTrue(results[0]["ok"])
        self.assertFalse(OfflineSession.objects.filter(session_id=session.session_id).exists())

    def test_sessions_on_foreign_devices_are_not_synced(self):
        # La propiedad sigue al dueño del dispositivo: aunque el
        # especialista haya confirmado la sesión, no sincroniza
        # sesiones de un dispositivo emparejado por otro.
        other = User.objects.create_user(username="otro", role="SPECIALIST")
        session = _completed_session(other, specialist=self.user)
        service, client = self._service(201)
        results = service.sync_all(user=self.user, id_token="tok")
        self.assertEqual(results, [])
        client.post.assert_not_called()
        self.assertTrue(
            OfflineSession.objects.filter(session_id=session.session_id).exists()
        )

    def test_own_device_sessions_synced_even_if_confirmed_by_other(self):
        # El dueño del dispositivo sincroniza sus sesiones aunque
        # las haya confirmado otro especialista.
        other = User.objects.create_user(username="otro", role="SPECIALIST")
        session = _completed_session(self.user, specialist=other)
        service, _ = self._service(201)
        results = service.sync_all(user=self.user, id_token="tok")
        self.assertTrue(results[0]["ok"])
        self.assertFalse(
            OfflineSession.objects.filter(session_id=session.session_id).exists()
        )

    def test_unowned_session_is_not_synced(self):
        # Sesiones en dispositivos sin dueño (nunca emparejados o
        # huérfanos por SET_NULL) no las sincroniza nadie.
        session = _completed_session(None)
        service, client = self._service(201)
        results = service.sync_all(user=self.user, id_token="tok")
        self.assertEqual(results, [])
        client.post.assert_not_called()
        self.assertTrue(
            OfflineSession.objects.filter(session_id=session.session_id).exists()
        )

    def test_409_conflict_counts_as_synced(self):
        _completed_session(self.user)
        service, _ = self._service(409)
        results = service.sync_all(user=self.user, id_token="tok")
        self.assertTrue(results[0]["ok"])
        self.assertEqual(OfflineSession.objects.count(), 0)

    def test_202_response_keeps_session_local_and_marks_error(self):
        session = _completed_session(self.user)
        service, _ = self._service(202)
        results = service.sync_all(user=self.user, id_token="tok")
        self.assertFalse(results[0]["ok"])
        self.assertTrue(
            OfflineSession.objects.filter(session_id=session.session_id).exists()
        )
        session.refresh_from_db()
        self.assertEqual(session.status, "ERROR")

    def test_204_response_keeps_session_local(self):
        session = _completed_session(self.user)
        service, _ = self._service(204)
        results = service.sync_all(user=self.user, id_token="tok")
        self.assertFalse(results[0]["ok"])
        self.assertTrue(
            OfflineSession.objects.filter(session_id=session.session_id).exists()
        )

    def test_corrupt_checksum_marks_error_and_keeps_local(self):
        session = _completed_session(self.user, metrics_checksum="0" * 64)
        service, _ = self._service(201)
        results = service.sync_all(user=self.user, id_token="tok")
        self.assertFalse(results[0]["ok"])
        session.refresh_from_db()
        self.assertEqual(session.status, "ERROR")
        self.assertEqual(session.sync_attempts, 1)

    def test_missing_metrics_marks_error(self):
        _completed_session(self.user, metrics=None)
        service, _ = self._service(201)
        results = service.sync_all(user=self.user, id_token="tok")
        self.assertFalse(results[0]["ok"])

    def test_terms_mismatch_marks_error(self):
        session = _completed_session(self.user, terms_content_hash="b" * 64)
        service, _ = self._service(201)
        results = service.sync_all(user=self.user, id_token="tok")
        self.assertFalse(results[0]["ok"])
        session.refresh_from_db()
        self.assertIn("érminos", session.last_sync_error)

    def test_aws_401_aborts_run_and_keeps_everything(self):
        _completed_session(self.user)
        _completed_session(self.user)
        service, _ = self._service(401)
        with self.assertRaises(UserInactiveError):
            service.sync_all(user=self.user, id_token="tok")
        self.assertEqual(OfflineSession.objects.count(), 2)

    def test_one_failure_does_not_stop_others(self):
        _completed_session(self.user, metrics_checksum="0" * 64)
        _completed_session(self.user)
        service, _ = self._service(201)
        results = service.sync_all(user=self.user, id_token="tok")
        self.assertEqual(len(results), 2)
        self.assertEqual(OfflineSession.objects.count(), 1)

    def test_injected_api_409_exception_counts_as_duplicate(self):
        _completed_session(self.user)
        client = Mock()
        client.post.side_effect = _ApiError(409)
        service = SyncService(api_client=client)
        results = service.sync_all(user=self.user, id_token="tok")
        self.assertTrue(results[0]["ok"])
        self.assertEqual(OfflineSession.objects.count(), 0)

    def test_stale_syncing_session_recovered_and_synced(self):
        session = _completed_session(
            self.user,
            status="SYNCING",
            sync_started_at=timezone.now() - timedelta(minutes=6),
        )
        service, _ = self._service(201)
        results = service.sync_all(user=self.user, id_token="tok")
        self.assertTrue(results[0]["ok"])
        self.assertFalse(
            OfflineSession.objects.filter(session_id=session.session_id).exists()
        )

    def test_recent_syncing_session_left_untouched(self):
        session = _completed_session(
            self.user,
            status="SYNCING",
            sync_started_at=timezone.now() - timedelta(minutes=1),
        )
        service, client = self._service(201)
        results = service.sync_all(user=self.user, id_token="tok")
        self.assertEqual(results, [])
        client.post.assert_not_called()
        session.refresh_from_db()
        self.assertEqual(session.status, "SYNCING")
        self.assertIsNotNone(session.sync_started_at)

    def test_syncing_without_timestamp_recovered(self):
        session = _completed_session(self.user, status="SYNCING", sync_started_at=None)
        service, _ = self._service(201)
        results = service.sync_all(user=self.user, id_token="tok")
        self.assertTrue(results[0]["ok"])
        self.assertFalse(
            OfflineSession.objects.filter(session_id=session.session_id).exists()
        )

    def test_error_after_upload_clears_sync_started_at(self):
        session = _completed_session(self.user)
        service, _ = self._service(202)
        service.sync_all(user=self.user, id_token="tok")
        session.refresh_from_db()
        self.assertEqual(session.status, "ERROR")
        self.assertIsNone(session.sync_started_at)

    def test_failed_delete_rolls_back_synced_audit_and_restores_session(self):
        # Auditoría y eliminación deben ser atómicas: si el delete falla,
        # no puede quedar un SYNC_SESSION_SYNCED huérfano de una fila que
        # sigue local (se re-auditaría como duplicado al reintentar).
        # La sesión se restaura a COMPLETED para permitir reintento
        # inmediato, sin esperar al recovery de 5 min de SYNCING.
        session = _completed_session(self.user)
        service, _ = self._service(201)
        with patch.object(
            OfflineSession, "delete", side_effect=OperationalError("database is locked")
        ):
            results = service.sync_all(user=self.user, id_token="tok")
        self.assertFalse(results[0]["ok"])
        session.refresh_from_db()
        self.assertEqual(session.status, "COMPLETED")
        self.assertIsNone(session.sync_started_at)
        self.assertFalse(
            AuditLog.objects.filter(
                action="SYNC_SESSION_SYNCED", resource_id=str(session.session_id)
            ).exists()
        )
        # Reintento inmediato: la sesión es candidata de nuevo y el 409
        # de AWS la cierra como duplicado.
        client = Mock()
        client.post.return_value = Mock(status_code=409)
        retry_results = SyncService(api_client=client).sync_all(
            user=self.user, id_token="tok"
        )
        self.assertTrue(retry_results[0]["ok"])
        self.assertFalse(
            OfflineSession.objects.filter(session_id=session.session_id).exists()
        )

    def test_failed_audit_restores_session_for_retry(self):
        session = _completed_session(self.user)
        service, _ = self._service(201)
        with patch(
            "offline_mode.services.sync_service.log_offline_event",
            side_effect=OperationalError("database is locked"),
        ):
            results = service.sync_all(user=self.user, id_token="tok")
        self.assertFalse(results[0]["ok"])
        session.refresh_from_db()
        self.assertEqual(session.status, "COMPLETED")
        self.assertIsNone(session.sync_started_at)
        self.assertTrue(
            OfflineSession.objects.filter(session_id=session.session_id).exists()
        )
        self.assertFalse(
            AuditLog.objects.filter(
                action="SYNC_SESSION_SYNCED", resource_id=str(session.session_id)
            ).exists()
        )

    def test_session_claimed_as_syncing_before_upload(self):
        # El reclamo a SYNCING debe ocurrir antes de la subida para que
        # una corrida concurrente no tome la misma sesión.
        session = _completed_session(self.user)
        seen = {}

        def probe(path, payload, *, token):
            seen["status"] = OfflineSession.objects.get(pk=session.pk).status
            return Mock(status_code=201)

        client = Mock()
        client.post.side_effect = probe
        SyncService(api_client=client).sync_all(user=self.user, id_token="tok")
        self.assertEqual(seen["status"], "SYNCING")

    def test_concurrently_claimed_session_is_skipped(self):
        # Si otra corrida reclama la sesión (UPDATE condicional devuelve 0),
        # esta corrida la salta sin subirla ni auditarla.
        first = _completed_session(
            self.user, completed_at=timezone.now() - timedelta(minutes=5)
        )
        second = _completed_session(self.user)
        service, client = self._service(201)

        original_refresh = OfflineSession.refresh_from_db
        raced = {"done": False}

        def racing_refresh(session_obj):
            if not raced["done"]:
                raced["done"] = True
                # Corrida concurrente reclama `second` antes de que
                # este loop llegue a ella.
                OfflineSession.objects.filter(
                    pk=second.pk, status=OfflineSession.Status.COMPLETED
                ).update(
                    status=OfflineSession.Status.SYNCING,
                    sync_started_at=timezone.now(),
                )
            return original_refresh(session_obj)

        with patch.object(OfflineSession, "refresh_from_db", racing_refresh):
            results = service.sync_all(user=self.user, id_token="tok")

        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["ok"])
        self.assertEqual(client.post.call_count, 1)
        second.refresh_from_db()
        self.assertEqual(second.status, "SYNCING")
        self.assertFalse(
            AuditLog.objects.filter(
                action="SYNC_SESSION_SYNCED", resource_id=str(second.session_id)
            ).exists()
        )

    def test_device_reassigned_between_query_and_claim_is_skipped(self):
        # Si el dispositivo se reasigna a otro especialista entre la
        # consulta de candidatas y el UPDATE de reclamo, el usuario
        # anterior no puede reclamar la sesión: el reclamo revalida
        # la propiedad del dispositivo.
        other = User.objects.create_user(username="otro", role="SPECIALIST")
        first = _completed_session(
            self.user, completed_at=timezone.now() - timedelta(minutes=5)
        )
        second = _completed_session(self.user)
        service, client = self._service(201)

        original_refresh = OfflineSession.refresh_from_db
        reassigned = {"done": False}

        def reassigning_refresh(session_obj):
            if not reassigned["done"]:
                reassigned["done"] = True
                # El dispositivo de `second` se reasigna a otro usuario
                # antes de que el loop llegue a reclamarla.
                second.device.paired_by = other
                second.device.save(update_fields=["paired_by"])
            return original_refresh(session_obj)

        with patch.object(OfflineSession, "refresh_from_db", reassigning_refresh):
            results = service.sync_all(user=self.user, id_token="tok")

        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["ok"])
        self.assertEqual(client.post.call_count, 1)
        second.refresh_from_db()
        self.assertEqual(second.status, "COMPLETED")
        self.assertIsNone(second.sync_started_at)
        self.assertTrue(
            OfflineSession.objects.filter(session_id=second.session_id).exists()
        )
        self.assertFalse(
            AuditLog.objects.filter(
                action="SYNC_SESSION_SYNCED", resource_id=str(second.session_id)
            ).exists()
        )

    def test_synced_audit_includes_on_behalf_of_confirmer(self):
        other = User.objects.create_user(username="otro", role="SPECIALIST")
        session = _completed_session(self.user, specialist=other)
        service, _ = self._service(201)
        service.sync_all(user=self.user, id_token="tok")
        row = AuditLog.objects.get(
            action="SYNC_SESSION_SYNCED", resource_id=str(session.session_id)
        )
        self.assertEqual(row.metadata["on_behalf_of"], "otro")
        self.assertFalse(row.metadata["duplicate"])

    def test_synced_audit_on_behalf_of_falls_back_to_syncing_user(self):
        session = _completed_session(self.user, specialist=None)
        service, _ = self._service(201)
        service.sync_all(user=self.user, id_token="tok")
        row = AuditLog.objects.get(
            action="SYNC_SESSION_SYNCED", resource_id=str(session.session_id)
        )
        self.assertEqual(row.metadata["on_behalf_of"], "esp")

    def test_duplicate_sync_audit_marks_duplicate(self):
        session = _completed_session(self.user)
        service, _ = self._service(409)
        service.sync_all(user=self.user, id_token="tok")
        row = AuditLog.objects.get(
            action="SYNC_SESSION_SYNCED", resource_id=str(session.session_id)
        )
        self.assertTrue(row.metadata["duplicate"])
        self.assertEqual(row.metadata["on_behalf_of"], "esp")


class _ApiError(Exception):
    def __init__(self, status_code):
        self.status_code = status_code
