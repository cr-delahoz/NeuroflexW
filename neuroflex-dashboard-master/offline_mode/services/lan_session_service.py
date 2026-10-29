import uuid

from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils import timezone

from offline_mode.models import OfflineSession, OfflineTermsAcceptance
from offline_mode.services.audit_service import log_offline_event
from offline_mode.services.checksums import compute_metrics_checksum, sha256_hex


REQUIRED_METRIC_KEYS = [
    "TiempoRespuestaPararse",
    "Precision",
    "TiempoActivoTarea",
    "CantAciertasTotales",
    "ObjetosInteractuadosCorrectamente",
    "TiempoRespuestaPregunta1",
    "TiempoRespuestaPregunta2",
    "TiempoRespuestaPregunta3",
    "TiempoCapturarNumero",
    "TiempoTutorial",
    "TipoEscena",
]


def create_session(*, device, acceptance_token, patient_info=None):
    try:
        token_uuid = uuid.UUID(str(acceptance_token))
        if token_uuid.version != 4:
            return None
    except (ValueError, AttributeError, TypeError):
        return None
    try:
        with transaction.atomic():
            acceptance = OfflineTermsAcceptance.objects.select_for_update().get(
                token=token_uuid, consumed=False, device=device
            )
            metrics_token = str(uuid.uuid4())
            session = OfflineSession.objects.create(
                device=device,
                terms_version_id=acceptance.terms_version_id,
                terms_content_hash=acceptance.content_hash,
                terms_accepted_at=acceptance.accepted_at,
                acceptance_token=acceptance.token,
                vr_application_version=acceptance.application_version,
                metrics_token_hash=sha256_hex(metrics_token),
                patient_info=patient_info or {},
            )
            acceptance.consumed = True
            acceptance.save(update_fields=["consumed"])
            log_offline_event(
                actor=None,
                action="OFFLINE_SESSION_CREATED",
                resource_type="offline_session",
                resource_id=session.session_id,
            )
    except (OfflineTermsAcceptance.DoesNotExist, ValueError, ValidationError):
        return None
    return session, metrics_token


def _token_matches(session, metrics_token) -> bool:
    return session.metrics_token_hash == sha256_hex(str(metrics_token))


def session_status(session_id, metrics_token):
    try:
        session = OfflineSession.objects.get(session_id=session_id)
    except (OfflineSession.DoesNotExist, ValueError):
        return None
    if not _token_matches(session, metrics_token):
        return None
    return session.status.lower()


def save_metrics(session_id, metrics_token, metrics: dict):
    try:
        session = OfflineSession.objects.get(session_id=session_id)
    except (OfflineSession.DoesNotExist, ValueError):
        return "not_found"
    if not _token_matches(session, metrics_token):
        return "unauthorized"
    if session.status != OfflineSession.Status.CONFIRMED:
        return "conflict"
    if set(metrics.keys()) != set(REQUIRED_METRIC_KEYS):
        return "bad_request"
    with transaction.atomic():
        updated = OfflineSession.objects.filter(
            pk=session.pk, status=OfflineSession.Status.CONFIRMED
        ).update(
            metrics=metrics,
            metrics_checksum=compute_metrics_checksum(metrics),
            status=OfflineSession.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        if updated == 0:
            return "conflict"
        log_offline_event(
            actor=None,
            action="OFFLINE_SESSION_COMPLETED",
            resource_type="offline_session",
            resource_id=session.session_id,
        )
    return "ok"
