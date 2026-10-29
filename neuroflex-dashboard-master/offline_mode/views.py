from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from offline_mode.decorators import specialist_required
from offline_mode.services import offline_session_ui_service
from offline_mode.services import lan_terms_service
from offline_mode.services import pairing_service
from offline_mode.services.connectivity import is_online
from offline_mode.services.jwt_utils import is_id_token_valid
from offline_mode.services.sync_service import SyncService, UserInactiveError


@login_required
@specialist_required
def panel(request):
    return render(request, "offline_mode/panel.html", {
        "searching": pairing_service.pairing_window_open(),
        "pending": pairing_service.active_request(),
        "devices": pairing_service.list_active_devices(),
        "active_sessions": offline_session_ui_service.list_active_sessions(request.user),
        "sessions": offline_session_ui_service.list_finished_sessions(request.user),
        "terms": lan_terms_service.current_terms(),
    })


@login_required
@specialist_required
def panel_status(request):
    """Estado en vivo para el polling del panel (cada 2s).

    Mientras la busqueda esta activa, cada consulta mantiene viva la ventana
    de emparejamiento, asi no hace falta recargar la pagina.
    """
    pairing_service.keep_pairing_window_alive()
    return JsonResponse({
        "searching": pairing_service.pairing_window_open(),
        "pending_pairing": pairing_service.active_request() is not None,
        "active_count": offline_session_ui_service.count_active_sessions(request.user),
    })


@login_required
@require_POST
@specialist_required
def go_online(request):
    """Vuelve al modo con conexion conservando la sesion iniciada.

    Solo si hay conexion: limpia la bandera offline para que el middleware
    deje acceder al dashboard; no hace falta volver a iniciar sesion.
    """
    if not is_online():
        messages.error(request, "Sin conexion a internet. Continúe en modo offline.")
        return redirect("offline_mode:panel")
    request.session.pop("offline_mode", None)
    return redirect("dashboard:home")


@login_required
@specialist_required
def session_detail(request, session_id):
    session = offline_session_ui_service.get_session_for_detail(
        session_id, request.user
    )
    if session is None:
        raise Http404("Sesión no encontrada")
    return render(request, "offline_mode/session_detail.html", {"session": session})


@login_required
@require_POST
@specialist_required
def confirm_session(request, session_id):
    if offline_session_ui_service.confirm_session(
        session_id=session_id, user=request.user
    ):
        messages.success(request, "Sesión vinculada a su usuario.")
    else:
        messages.error(request, "La sesión no está pendiente.")
    return redirect("offline_mode:panel")


@login_required
@require_POST
@specialist_required
def delete_session(request, session_id):
    if offline_session_ui_service.delete_unfinished_session(
        session_id=session_id, user=request.user
    ):
        messages.success(request, "Sesión local eliminada.")
    else:
        messages.error(request, "No se puede eliminar: la sesión no existe o está sincronizada.")
    return redirect("offline_mode:panel")


@login_required
@require_POST
@specialist_required
def pairing_start(request):
    pairing_service.open_pairing_window()
    return redirect("offline_mode:panel")


@login_required
@require_POST
@specialist_required
def pairing_stop(request):
    pairing_service.close_pairing_window()
    return redirect("offline_mode:panel")


@login_required
@require_POST
@specialist_required
def pairing_confirm(request):
    device = pairing_service.confirm_pairing(request.POST.get("pin", ""), request.user)
    if device:
        pairing_service.close_pairing_window()
        messages.success(request, f"Dispositivo '{device.name}' emparejado.")
    else:
        messages.error(request, "PIN incorrecto o solicitud expirada.")
    return redirect("offline_mode:panel")


@login_required
@require_POST
@specialist_required
def device_revoke(request, pk):
    pairing_service.revoke_device(pk, request.user)
    messages.success(request, "Dispositivo revocado.")
    next_url = request.POST.get("next")
    if next_url and next_url.startswith("/"):
        return redirect(next_url)
    return redirect("offline_mode:panel")


@login_required
@require_POST
@specialist_required
def sync_now(request):
    if not is_online():
        return JsonResponse(
            {
                "ok": False,
                "results": [],
                "user_inactive": False,
                "error": "Sin conexión a internet",
            },
            status=503,
        )

    id_token = request.session.get("cognito_id_token", "")
    if not is_id_token_valid(id_token):
        return JsonResponse(
            {
                "ok": False,
                "results": [],
                "user_inactive": False,
                "reauth_required": True,
                "error": "Se requiere iniciar sesión online para sincronizar.",
            },
            status=403,
        )
    try:
        results = SyncService().sync_all(user=request.user, id_token=id_token)
    except UserInactiveError as exc:
        return JsonResponse(
            {"ok": False, "results": [], "user_inactive": True, "error": str(exc)},
            status=403,
        )

    return JsonResponse({"ok": True, "results": results, "user_inactive": False})
