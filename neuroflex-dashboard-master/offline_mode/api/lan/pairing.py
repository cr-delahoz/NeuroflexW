import re
import socket
import uuid

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from offline_mode.api.lan.auth import json_body, require_device_token
from offline_mode.services import pairing_service

PIN_RE = re.compile(r"^[0-9]{6}$")


@csrf_exempt
@require_POST
def pair_request(request):
    if not pairing_service.pairing_window_open():
        return JsonResponse(
            {"error": "Abra la pantalla de emparejamiento en el dashboard antes de vincular un dispositivo"},
            status=403,
        )
    if not pairing_service.dashboard_session_active():
        return JsonResponse(
            {"error": "Inicie sesión en el dashboard antes de emparejar dispositivos"},
            status=403,
        )
    data = json_body(request)
    device_id, data_name, pin = data.get("device_id"), data.get("device_name"), data.get("pin")
    name = str(data_name).strip()
    if (
        not device_id
        or not (1 <= len(name) <= 100)
        or not isinstance(data_name, str)
        or not pin
    ):
        return JsonResponse(
            {"error": "device_id, device_name y pin (6 dígitos) requeridos"},
            status=400,
        )
    if not isinstance(pin, str) or not PIN_RE.fullmatch(pin):
        return JsonResponse(
            {"error": "device_id, device_name y pin (6 dígitos) requeridos"},
            status=400,
        )
    try:
        uuid.UUID(str(device_id))
    except (ValueError, AttributeError, TypeError):
        return JsonResponse({"error": "device_id debe ser un UUID válido"}, status=400)
    req = pairing_service.create_request(
        device_id=device_id, device_name=name, pin=str(pin)
    )
    if req is None:
        active = pairing_service.active_request()
        if active is not None:
            return JsonResponse(
                {
                    "error": "Ya hay una solicitud de emparejamiento activa",
                    "pairing_id": str(active.pairing_id),
                    "expires_in": int(
                        max(
                            0,
                            (
                                active.expires_at - timezone.now()
                            ).total_seconds(),
                        )
                    ),
                },
                status=409,
            )
        return JsonResponse(
            {"error": "Ya hay una solicitud de emparejamiento activa"}, status=409
        )
    return JsonResponse(
        {"pairing_id": str(req.pairing_id), "expires_in": 180}, status=201
    )


@require_GET
def pair_status(request, pairing_id):
    status = pairing_service.get_request_status(pairing_id)
    if status is None:
        return JsonResponse({"error": "Solicitud no encontrada"}, status=404)
    if status == "expired":
        return JsonResponse({"status": "expired"})
    if status == "waiting":
        return JsonResponse({"status": "waiting"})
    token = pairing_service.claim_token(pairing_id)
    payload = {"status": "confirmed"}
    if token:
        payload["device_token"] = token
    return JsonResponse(payload)


@require_GET
@require_device_token
def device_ping(request):
    return JsonResponse({"ok": True, "dashboard": socket.gethostname()})
