from django.urls import path

from offline_mode import views


app_name = "offline_mode"

urlpatterns = [
    path("panel/", views.panel, name="panel"),
    path("panel/status", views.panel_status, name="panel_status"),
    path("go-online", views.go_online, name="go_online"),
    path("sessions/<uuid:session_id>/", views.session_detail, name="session_detail"),
    path("sessions/<uuid:session_id>/confirm", views.confirm_session, name="confirm_session"),
    path("sessions/<uuid:session_id>/delete", views.delete_session, name="delete_session"),
    path("pairing/start", views.pairing_start, name="pairing_start"),
    path("pairing/stop", views.pairing_stop, name="pairing_stop"),
    path("pairing/active", views.panel_status, name="pairing_active"),
    path("pairing/confirm", views.pairing_confirm, name="pairing_confirm"),
    path("devices/<uuid:pk>/revoke", views.device_revoke, name="device_revoke"),
    path("sync/", views.sync_now, name="sync_now"),
]
