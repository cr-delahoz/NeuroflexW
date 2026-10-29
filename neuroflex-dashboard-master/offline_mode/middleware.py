from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.urls import reverse


# Login/logout se resuelven desde el URLconf para que el allowlist siempre
# coincida con las rutas reales de autenticacion.
ALLOWED_PREFIXES = (
    "/offline/",
    "/api/lan/",
    "/static/",
    reverse("accounts:login"),
    reverse("accounts:logout"),
)

LAN_API_PREFIX = "/api/lan/"
PROXY_HEADERS = ("HTTP_X_FORWARDED_FOR", "HTTP_X_REAL_IP", "HTTP_FORWARDED",
                 "HTTP_CLIENT_IP", "HTTP_X_CLUSTER_CLIENT_IP")
LOCAL_ADDRS = ("127.0.0.1", "::1")


class OfflineModeMiddleware:
    """Si la sesión es offline, solo permite las rutas del modo captura."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.session.get("offline_mode") and not request.path.startswith(
            ALLOWED_PREFIXES
        ):
            return redirect("offline_mode:panel")
        return self.get_response(request)


class LocalhostOnlyMiddleware:
    """La UI web solo responde a localhost; /api/lan/ queda expuesta a la red local."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith(LAN_API_PREFIX):
            return self.get_response(request)
        if any(h in request.META for h in PROXY_HEADERS):
            return HttpResponseForbidden("Acceso denegado")
        if request.META.get("REMOTE_ADDR") not in LOCAL_ADDRS:
            return HttpResponseForbidden("Solo acceso local")
        return self.get_response(request)
