from django.contrib import admin
from django.urls import include, path

from .views import error_403, error_404

urlpatterns = [
    path('admin/', admin.site.urls),
    path("", include("dashboard.urls")),
    path("", include("accounts.urls")),
    path("", include("audit.urls")),
    path("", include("reports.urls")),
    path("", include("clinical_sessions.urls")),
    path("updater/", include("updater.urls")),
    path("offline/", include("offline_mode.urls")),
    path("api/lan/", include("offline_mode.api.lan.urls")),
    path("", include("terms.urls")),
]

handler403 = error_403
handler404 = error_404
