from django.urls import path

from offline_mode.api.lan import pairing
from offline_mode.api.lan import sessions
from offline_mode.api.lan import terms

urlpatterns = []

urlpatterns = [
    path("pair/request", pairing.pair_request),
    path("pair/status/<uuid:pairing_id>", pairing.pair_status),
    path("device/ping", pairing.device_ping),
    path("terms/current", terms.terms_current),
    path("terms/accept", terms.terms_accept),
    path("sessions", sessions.create_session),
    path("sessions/<uuid:session_id>/status", sessions.session_status),
    path("sessions/<uuid:session_id>/metrics", sessions.save_metrics),
]
