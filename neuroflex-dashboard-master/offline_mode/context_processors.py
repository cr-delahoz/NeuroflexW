from offline_mode.services import offline_session_ui_service
from offline_mode.services.connectivity import is_online


def sync_banner(request):
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}
    if getattr(request.user, "role", None) != "SPECIALIST":
        return {}
    pending = offline_session_ui_service.count_pending_sessions(request.user)
    return {"offline_sync_banner": {
        "is_online": is_online(),
        "pending_count": pending,
        "offline_mode": request.session.get("offline_mode", False),
    }}
