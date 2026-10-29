import json
from functools import wraps

from django.http import JsonResponse
from django.utils import timezone

from offline_mode.models import OfflineDevice
from offline_mode.services.checksums import sha256_hex


def require_device_token(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return JsonResponse({"error": "Token de dispositivo requerido"}, status=401)
        token_hash = sha256_hex(header.removeprefix("Bearer ").strip())
        try:
            device = OfflineDevice.objects.get(
                device_token_hash=token_hash, revoked=False
            )
        except OfflineDevice.DoesNotExist:
            return JsonResponse({"error": "Dispositivo no autorizado"}, status=401)
        device.last_seen_at = timezone.now()
        device.save(update_fields=["last_seen_at"])
        request.offline_device = device
        return view_func(request, *args, **kwargs)

    return wrapper


def json_body(request) -> dict:
    try:
        body = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return body if isinstance(body, dict) else {}
