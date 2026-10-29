from offline_mode.models import OfflineSession
from django.utils import timezone

from offline_mode.services.audit_service import log_offline_event


def list_visible_sessions(user):
    """Sesiones locales visibles en la cola (las SYNCED ya no existen localmente).

    Solo las de dispositivos emparejados por ``user``: cada especialista
    ve únicamente sus propias sesiones.
    """
    return OfflineSession.objects.filter(
        device__paired_by=user,
    ).exclude(
        status=OfflineSession.Status.SYNCED
    ).order_by("-created_at")


def list_active_sessions(user):
    """Sesiones creadas por el visor aun no terminadas (PENDING/CONFIRMED).

    PENDING: creada, pendiente de vincular con el especialista.
    CONFIRMED: vinculada, en curso hasta que el visor envie metricas.
    """
    return OfflineSession.objects.filter(
        device__paired_by=user,
        status__in=[
            OfflineSession.Status.PENDING,
            OfflineSession.Status.CONFIRMED,
        ],
    ).order_by("-created_at")


def count_active_sessions(user) -> int:
    return OfflineSession.objects.filter(
        device__paired_by=user,
        status__in=[
            OfflineSession.Status.PENDING,
            OfflineSession.Status.CONFIRMED,
        ],
    ).count()


def list_finished_sessions(user):
    """Sesiones terminadas (COMPLETED/SYNCING/ERROR): historial sincronizable."""
    return OfflineSession.objects.filter(
        device__paired_by=user,
        status__in=[
            OfflineSession.Status.COMPLETED,
            OfflineSession.Status.SYNCING,
            OfflineSession.Status.ERROR,
        ],
    ).order_by("-created_at")


def delete_unfinished_session(*, session_id, user) -> bool:
    """Elimina una sesión local no sincronizada (única operación de borrado).

    Solo en modo offline y para sesiones locales: nunca borra sesiones ya
    sincronizadas o en proceso (SYNCING/SYNCED).
    """
    try:
        session = OfflineSession.objects.get(
            session_id=session_id, device__paired_by=user
        )
    except OfflineSession.DoesNotExist:
        return False
    if session.status not in (
        OfflineSession.Status.PENDING,
        OfflineSession.Status.CONFIRMED,
        OfflineSession.Status.ERROR,
    ):
        return False
    session_id_value = session.session_id
    session.delete()
    log_offline_event(
        actor=user,
        action="OFFLINE_SESSION_DELETED",
        resource_type="offline_session",
        resource_id=session_id_value,
    )
    return True


def count_pending_sessions(user) -> int:
    """Sesiones listas para sincronizar (terminadas o con error de sync).

    Solo las de dispositivos emparejados por ``user``: cada especialista
    ve sus propias pendientes.
    """
    return OfflineSession.objects.filter(
        device__paired_by=user,
        status__in=[OfflineSession.Status.COMPLETED, OfflineSession.Status.ERROR],
    ).count()


def get_session_for_detail(session_id, user):
    try:
        return OfflineSession.objects.get(
            session_id=session_id, device__paired_by=user
        )
    except OfflineSession.DoesNotExist:
        return None


def confirm_session(*, session_id, user) -> bool:
    updated = OfflineSession.objects.filter(
        session_id=session_id,
        device__paired_by=user,
        status=OfflineSession.Status.PENDING,
    ).update(
        specialist=user,
        status=OfflineSession.Status.CONFIRMED,
        confirmed_at=timezone.now(),
    )
    if updated:
        log_offline_event(
            actor=user,
            action="OFFLINE_SESSION_CONFIRMED",
            resource_type="offline_session",
            resource_id=session_id,
        )
    return bool(updated)
