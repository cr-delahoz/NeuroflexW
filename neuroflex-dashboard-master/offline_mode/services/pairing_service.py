import secrets
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, OperationalError, transaction
from django.db.models import Q
from django.utils import timezone

from offline_mode.models import OfflineDevice, PairingRequest
from offline_mode.services.audit_service import log_offline_event
from offline_mode.services.checksums import sha256_hex


def expire_stale_requests():
    """Expira solicitudes vencidas y borra el ``device_token`` crudo en BD.

    Una solicitud confirmada cuyo token nunca fue reclamado no debe
    conservar el token en claro una vez expirada (equivalente a marcar
    status EXPIRED en este modelo, basado en ``expires_at``).
    """
    now = timezone.now()
    ttl = timedelta(seconds=getattr(settings, "PAIRING_PIN_TTL_SECONDS", 300))
    PairingRequest.objects.filter(
        Q(expires_at__lt=now) | Q(created_at__lt=now - ttl)
    ).update(expires_at=now, device_token=None, is_active=False)


PAIRING_WINDOW_SECONDS = 15


def open_pairing_window():
    """Abre (o refresca) la ventana de emparejamiento en el cache.

    La ventana representa que el especialista tiene abierta la pantalla de
    emparejamiento: es la condicion para aceptar pair/request de los Quest.
    Expira sola (PAIRING_WINDOW_SECONDS) si el especialista abandona la
    pantalla, y la mantiene viva el polling de la pagina.
    """
    from django.core.cache import cache

    cache.set("pairing_window_open", timezone.now().isoformat(), PAIRING_WINDOW_SECONDS)


def pairing_window_open():
    from django.core.cache import cache

    return cache.get("pairing_window_open") is not None


def keep_pairing_window_alive():
    """Extiende la ventana solo si ya esta abierta (busqueda en curso).

    El polling del panel la llama para que la busqueda siga activa mientras
    el especialista tiene la pantalla abierta; nunca reabre una busqueda
    detenida o vencida.
    """
    if pairing_window_open():
        open_pairing_window()


def close_pairing_window():
    """Detiene la busqueda: cierra la ventana y cancela la solicitud pendiente."""
    from django.core.cache import cache

    cache.delete("pairing_window_open")
    PairingRequest.objects.filter(
        confirmed=False, expires_at__gt=timezone.now()
    ).update(expires_at=timezone.now(), is_active=False)


def dashboard_session_active():
    """True si el dashboard tiene al menos una sesión activa con usuario.

    Mientras el dashboard está en la pantalla de login (sin sesión activa)
    no se aceptan emparejamientos LAN: los Quest solo pueden vincularse
    cuando un especialista inició sesión.
    """
    from django.contrib.sessions.backends.db import SessionStore
    from django.contrib.sessions.models import Session

    for row in Session.objects.filter(expire_date__gt=timezone.now()).iterator():
        try:
            if SessionStore().decode(row.session_data).get("_auth_user_id"):
                return True
        except Exception:
            continue
    return False


def active_request():
    expire_stale_requests()
    return PairingRequest.objects.filter(
        confirmed=False, expires_at__gt=timezone.now()
    ).first()


def create_request(*, device_id, device_name, pin):
    with transaction.atomic():
        expire_stale_requests()
        # El mismo dispositivo puede reemplazar su solicitud activa (p. ej.
        # el Quest reinició la app y regeneró el PIN): se expira la fila
        # previa para liberar la restricción única parcial y permitir el
        # nuevo emparejamiento sin esperar el TTL.
        PairingRequest.objects.filter(
            device_id=device_id, confirmed=False, expires_at__gt=timezone.now()
        ).update(expires_at=timezone.now(), is_active=False)
        existing = (
            PairingRequest.objects.select_for_update()
            .filter(confirmed=False, expires_at__gt=timezone.now())
            .first()
        )
        if existing is not None:
            return None
        try:
            # Savepoint: si otra transacción creó una solicitud activa para
            # el mismo dispositivo, la restricción única parcial dispara
            # IntegrityError; en SQLite una carrera puede manifestarse como
            # OperationalError "database is locked". Ambos se tratan como
            # conflicto y devolvemos None (409 en el contrato); cualquier
            # otro error operativo se propaga.
            with transaction.atomic():
                return PairingRequest.objects.create(
                    device_id=device_id,
                    device_name=device_name,
                    pin_hash=sha256_hex(pin),
                    expires_at=timezone.now()
                    + timedelta(seconds=settings.PAIRING_PIN_TTL_SECONDS),
                    is_active=True,
                )
        except IntegrityError:
            return None
        except OperationalError as exc:
            if "database is locked" in str(exc).lower():
                return None
            raise


def confirm_pairing(pin: str, user):
    # La lectura y actualización de la solicitud van en una sola transacción
    # con select_for_update: dos confirmaciones concurrentes no pueden leer
    # la misma solicitud pendiente y generar dos tokens (la segunda espera
    # al lock, re-evalúa el filtro confirmed=False y no encuentra nada).
    try:
        with transaction.atomic():
            expire_stale_requests()
            req = (
                PairingRequest.objects.select_for_update()
                .filter(confirmed=False, expires_at__gt=timezone.now())
                .first()
            )
            if req is None:
                return None
            if req.pin_hash != sha256_hex(pin):
                req.confirm_attempts += 1
                if req.confirm_attempts >= settings.PAIRING_MAX_PIN_ATTEMPTS:
                    req.expires_at = timezone.now()
                    req.is_active = False
                req.save(update_fields=["confirm_attempts", "expires_at", "is_active"])
                return None
            token = secrets.token_hex(32)
            try:
                # Savepoint: si otra transacción emparejó el mismo dispositivo,
                # la restricción única de OfflineDevice dispara IntegrityError y
                # se trata como conflicto (None) sin abortar la transacción.
                with transaction.atomic():
                    device, _created = OfflineDevice.objects.update_or_create(
                        device_id=req.device_id,
                        defaults={
                            "name": req.device_name,
                            "device_token_hash": sha256_hex(token),
                            "paired_by": user,
                            "revoked": False,
                            "paired_at": timezone.now(),
                        },
                    )
                    req.confirmed = True
                    req.device_token = token
                    req.is_active = False
                    req.save(
                        update_fields=["confirmed", "device_token", "is_active"]
                    )
            except IntegrityError:
                req.expires_at = timezone.now()
                req.is_active = False
                req.save(update_fields=["expires_at", "is_active"])
                return None
            # El log de auditoría se escribe dentro de la transacción: si
            # falla con "database is locked" (SQLite bajo carrera), el
            # except exterior lo trata como conflicto y el emparejamiento
            # queda atómico (nunca un dispositivo confirmado sin auditoría).
            log_offline_event(
                actor=user,
                action="DEVICE_PAIRED",
                resource_type="device",
                resource_id=device.device_id,
                metadata={"name": device.name},
            )
    except OperationalError as exc:
        # En SQLite select_for_update no bloquea: una carrera concurrente
        # puede fallar con "database is locked" (incluso al hacer commit).
        # Se trata como conflicto (None, error genérico en la vista);
        # cualquier otro error operativo se propaga, igual que en
        # create_request.
        if "database is locked" in str(exc).lower():
            return None
        raise
    return device


def claim_token(pairing_id):
    """Entrega el token una única vez y solo si la solicitud no expiró.

    Una solicitud confirmada pero vencida nunca entrega su token: se limpia
    el ``device_token`` crudo, se desactiva la solicitud y se devuelve None.
    """
    with transaction.atomic():
        req = (
            PairingRequest.objects.select_for_update()
            .filter(pairing_id=pairing_id, expires_at__gt=timezone.now())
            .first()
        )
        if req is None:
            # No existe o está expirada: descarta cualquier token residual.
            PairingRequest.objects.filter(pairing_id=pairing_id).update(
                device_token=None, is_active=False
            )
            return None
        if not req.confirmed or req.delivered or not req.device_token:
            return None
        token = req.device_token
        claimed = PairingRequest.objects.filter(
            pk=req.pk, delivered=False, expires_at__gt=timezone.now()
        ).update(delivered=True, device_token=None, is_active=False)
        return token if claimed == 1 else None


def get_request_status(pairing_id):
    """Devuelve 'waiting' | 'confirmed' | 'expired' | None (no existe).

    Una solicitud confirmada cuyo token nunca fue reclamado
    (``delivered=False``) reporta ``expired`` una vez vencida: el Quest
    debe reiniciar el emparejamiento en lugar de sondear indefinidamente
    un ``confirmed`` que ya no entregará token. Una solicitud reclamada
    nunca reporta ``expired``: el dispositivo ya posee el token.

    Al reportar ``expired`` se descarta además el ``device_token`` crudo
    residual y se desactiva la solicitud: un token no reclamado no debe
    persistir en claro una vez vencida. El UPDATE es una sola sentencia
    condicionada a nivel de BD (expirada y sin reclamar), por lo que es
    atómico y nunca toca solicitudes aún vigentes.
    """
    req = PairingRequest.objects.filter(pairing_id=pairing_id).first()
    if req is None:
        return None
    if req.is_expired() and not req.delivered:
        PairingRequest.objects.filter(
            pk=req.pk,
            delivered=False,
            expires_at__lte=timezone.now(),
        ).update(device_token=None, is_active=False)
        return "expired"
    return "confirmed" if req.confirmed else "waiting"


def list_active_devices():
    return OfflineDevice.objects.filter(revoked=False).order_by("-paired_at")


def revoke_device(pk, user) -> bool:
    updated = OfflineDevice.objects.filter(pk=pk).update(revoked=True)
    if updated:
        log_offline_event(
            actor=user,
            action="DEVICE_REVOKED",
            resource_type="device",
            resource_id=pk,
        )
    return bool(updated)
