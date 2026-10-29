from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from offline_mode.models import OfflineSession
from offline_mode.services.audit_service import log_offline_event
from offline_mode.services.checksums import compute_metrics_checksum
from offline_mode.services.lan_session_service import REQUIRED_METRIC_KEYS
from terms.models import TermsVersion


class UserInactiveError(Exception):
    """El usuario fue desactivado localmente o por AWS."""


# Mensaje genérico (sin datos clínicos) para fallos de limpieza
# post-sincronización: auditoría o eliminación de la fila local.
CLEANUP_FAILURE_MESSAGE = "Fallo al registrar auditoría o eliminar la sesión local"


class SyncService:
    def __init__(self, api_client=None):
        self.api_client = api_client

    def sync_all(self, *, user, id_token) -> list[dict]:
        if not user.is_active:
            raise UserInactiveError("Usuario inactivo localmente")

        self._recover_stale_syncing()
        results = []
        # Solo las sesiones de dispositivos emparejados por el
        # especialista que sincroniza: la propiedad sigue al dueño
        # del dispositivo, no a quien confirmó la sesión.
        candidates = OfflineSession.objects.filter(
            Q(status=OfflineSession.Status.COMPLETED) | Q(status=OfflineSession.Status.ERROR),
            device__paired_by=user,
        ).order_by("completed_at")
        for session in candidates:
            # Reclamo atómico: el UPDATE condicional garantiza que una
            # corrida concurrente no procese la misma sesión y que, si
            # el dispositivo se reasignó desde la consulta, el usuario
            # anterior no pueda reclamarla.
            claimed = OfflineSession.objects.filter(
                pk=session.pk,
                device__paired_by=user,
                status__in=[OfflineSession.Status.COMPLETED, OfflineSession.Status.ERROR],
            ).update(status=OfflineSession.Status.SYNCING, sync_started_at=timezone.now())
            if claimed == 0:
                continue  # otra corrida la reclamó o el dispositivo cambió de dueño
            session.refresh_from_db()
            results.append(self._sync_one(session, user=user, id_token=id_token))
        return results

    @staticmethod
    def _recover_stale_syncing():
        """Devuelve a COMPLETED sesiones SYNCING abandonadas (>5 min o sin marca)."""
        cutoff = timezone.now() - timedelta(minutes=5)
        OfflineSession.objects.filter(
            Q(status=OfflineSession.Status.SYNCING)
            & (Q(sync_started_at__lt=cutoff) | Q(sync_started_at__isnull=True))
        ).update(status=OfflineSession.Status.COMPLETED, sync_started_at=None)

    def _sync_one(self, session, *, user, id_token) -> dict:
        # La sesión ya fue reclamada como SYNCING en sync_all.
        error = self._run_local_verifications(session)
        if error:
            return self._mark_error(session, error)

        try:
            response = self._upload(session, id_token)
        except Exception as exc:
            status_code = getattr(exc, "status_code", None)
            if status_code == 409:
                return self._mark_synced(session, user, duplicate=True)
            if status_code in (401, 403):
                self._restore_after_auth_failure(session)
                raise UserInactiveError(
                    f"AWS rechazó la autorización ({status_code})"
                ) from exc
            return self._mark_error(session, str(exc))

        if response.status_code in (200, 201, 409):
            return self._mark_synced(
                session, user, duplicate=(response.status_code == 409)
            )
        if response.status_code in (401, 403):
            self._restore_after_auth_failure(session)
            raise UserInactiveError(
                f"AWS rechazó la autorización ({response.status_code})"
            )
        return self._mark_error(session, f"AWS respondió {response.status_code}")

    def _run_local_verifications(self, session) -> str | None:
        if not session.metrics:
            return "Sesión sin métricas"
        if any(key not in session.metrics for key in REQUIRED_METRIC_KEYS):
            return "Métricas incompletas"
        if compute_metrics_checksum(session.metrics) != session.metrics_checksum:
            return "Checksum de métricas no coincide"

        terms_ok = TermsVersion.objects.filter(
            version_id=session.terms_version_id,
            published=True,
            content_hash=session.terms_content_hash,
        ).exists()
        if not terms_ok:
            return "Términos inválidos o desactualizados"
        return None

    def _upload(self, session, id_token):
        """Único punto que conoce el contrato de ``/sessions/sync``."""
        payload = {
            "session_id": str(session.session_id),
            "terms": {
                "version_id": session.terms_version_id,
                "content_hash": session.terms_content_hash,
                "accepted_at": session.terms_accepted_at.isoformat(),
                "acceptance_token": str(session.acceptance_token),
            },
            "vr_application_version": session.vr_application_version,
            "patient_info": session.patient_info or {},
            "metrics": session.metrics,
            "completed_at": (
                session.completed_at.isoformat() if session.completed_at else None
            ),
        }
        if self.api_client is not None:
            return self.api_client.post("/sessions/sync", payload, token=id_token)
        return self._default_client().post("/sessions/sync", payload, token=id_token)

    def _default_client(self):
        from integrations.services.neuroflex_api_client import NeuroflexApiClient

        class ClientAdapter:
            def __init__(self):
                self.client = NeuroflexApiClient()

            def post(self, path, payload, *, token):
                try:
                    return self.client.post_with_response(
                        path, token=token, json_body=payload
                    )
                except Exception as exc:
                    if getattr(exc, "status_code", None) == 409:
                        return _Response(status_code=409)
                    raise

        return ClientAdapter()

    def _mark_error(self, session, reason) -> dict:
        session.status = OfflineSession.Status.ERROR
        session.sync_started_at = None
        session.sync_attempts += 1
        session.last_sync_error = reason
        session.save(
            update_fields=["status", "sync_started_at", "sync_attempts", "last_sync_error"]
        )
        log_offline_event(
            actor=None,
            action="SYNC_SESSION_ERROR",
            resource_type="offline_session",
            resource_id=session.session_id,
            result="FAILURE",
            metadata={"reason": reason},
        )
        return {
            "session_id": str(session.session_id),
            "ok": False,
            "error": reason,
        }

    def _mark_synced(self, session, user, *, duplicate) -> dict:
        metadata = {
            "duplicate": duplicate,
            "on_behalf_of": (
                session.specialist.username if session.specialist else user.username
            ),
        }
        # Auditoría y eliminación son atómicas: si una falla, la otra se
        # revierte. Sin esto, un delete fallido dejaría auditoría
        # SYNC_SESSION_SYNCED de una fila que sigue local (y se
        # re-auditaría como duplicado al reintentar).
        try:
            with transaction.atomic():
                log_offline_event(
                    actor=user,
                    action="SYNC_SESSION_SYNCED",
                    resource_type="offline_session",
                    resource_id=session.session_id,
                    metadata=metadata,
                )
                session.delete()
        except Exception:
            # La transacción se revirtió y la fila sigue local en SYNCING:
            # se restaura a COMPLETED y se limpia sync_started_at para
            # permitir reintento inmediato (sin esperar al recovery de
            # 5 min). El mensaje es fijo y genérico: nunca registra
            # datos clínicos del payload.
            OfflineSession.objects.filter(pk=session.pk).update(
                status=OfflineSession.Status.COMPLETED,
                sync_started_at=None,
                last_sync_error=CLEANUP_FAILURE_MESSAGE,
            )
            return {
                "session_id": str(session.session_id),
                "ok": False,
                "error": CLEANUP_FAILURE_MESSAGE,
            }
        return {"session_id": str(session.session_id), "ok": True, "error": None}

    @staticmethod
    def _restore_after_auth_failure(session):
        session.status = OfflineSession.Status.COMPLETED
        session.sync_started_at = None
        session.save(update_fields=["status", "sync_started_at"])


class _Response:
    def __init__(self, *, status_code, payload=None):
        self.status_code = status_code
        self.payload = payload
