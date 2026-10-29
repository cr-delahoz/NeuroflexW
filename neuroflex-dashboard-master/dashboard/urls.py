from django.urls import path

from .views import AdminDashboardView, HomeRedirectView, SpecialistDashboardView

app_name = "dashboard"

urlpatterns = [
    path("", HomeRedirectView.as_view(), name="home"),
    path("admin-dashboard/", AdminDashboardView.as_view(), name="admin"),
    path(
        "specialist-dashboard/",
        SpecialistDashboardView.as_view(),
        name="specialist",
    ),
]
