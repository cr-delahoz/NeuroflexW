from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from offline_mode.api.lan.auth import json_body, require_device_token
from offline_mode.services import lan_terms_service


@require_GET
@require_device_token
def terms_current(request):
    terms = lan_terms_service.current_terms()
    if terms is None:
        return JsonResponse(
            {"error": "No hay términos disponibles localmente"}, status=503
        )
    return JsonResponse(
        {
            "version_id": terms.version_id,
            "title": terms.title,
            "content": terms.content,
            "language": terms.language,
            "content_hash": terms.content_hash,
            "created_at": terms.created_at.isoformat(),
        }
    )


@csrf_exempt
@require_POST
@require_device_token
def terms_accept(request):
    data = json_body(request)
    application_version = data.get("application_version", "")
    if not isinstance(application_version, str) or not application_version.strip():
        return JsonResponse({"error": "application_version requerido"}, status=400)
    version_id = data.get("version_id")
    if not isinstance(version_id, str) or len(version_id) > 100:
        return JsonResponse({"error": "version_id inválido"}, status=400)
    acceptance = lan_terms_service.accept_terms(
        device=request.offline_device,
        version_id=version_id,
        content_hash=data.get("content_hash", ""),
        application_version=application_version,
    )
    if acceptance is None:
        return JsonResponse(
            {"error": "Versión o hash de términos inválido"}, status=400
        )
    return JsonResponse({"acceptance_token": str(acceptance.token)})
