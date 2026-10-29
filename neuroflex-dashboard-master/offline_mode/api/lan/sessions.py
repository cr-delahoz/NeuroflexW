from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from offline_mode.api.lan.auth import json_body, require_device_token
from offline_mode.services import lan_session_service


@csrf_exempt
@require_POST
@require_device_token
def create_session(request):
    data = json_body(request)
    result = lan_session_service.create_session(
        device=request.offline_device,
        acceptance_token=data.get("acceptance_token"),
        patient_info=data.get("patient_info"),
    )
    if result is None:
        return JsonResponse(
            {"error": "acceptance_token inválido o consumido"}, status=400
        )
    session, metrics_token = result
    return JsonResponse(
        {
            "session_id": str(session.session_id),
            "metrics_token": metrics_token,
            "status": "pending",
        },
        status=201,
    )


@require_GET
def session_status(request, session_id):
    status = lan_session_service.session_status(
        session_id, request.headers.get("X-Metrics-Token", "")
    )
    if status is None:
        return JsonResponse(
            {"error": "Sesión no encontrada o token inválido"}, status=404
        )
    return JsonResponse({"session_id": str(session_id), "status": status})


@csrf_exempt
@require_POST
def save_metrics(request, session_id):
    result = lan_session_service.save_metrics(
        session_id,
        request.headers.get("X-Metrics-Token", ""),
        json_body(request),
    )
    if result == "not_found":
        return JsonResponse({"error": "Sesión no encontrada"}, status=404)
    if result == "unauthorized":
        return JsonResponse({"error": "metrics_token inválido"}, status=401)
    if result == "conflict":
        return JsonResponse({"error": "La sesión no está confirmada"}, status=409)
    if result == "bad_request":
        return JsonResponse({"error": "Métricas incompletas"}, status=400)
    return JsonResponse({"ok": True})
