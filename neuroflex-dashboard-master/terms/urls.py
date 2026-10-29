from django.urls import path

from .views import (
    TermsListView,
    TermsSetCurrentView,
    TermsVersionCreateView,
    TermsVersionDetailView,
)

app_name = "terms"

urlpatterns = [
    path("terms/", TermsListView.as_view(), name="terms-list"),
    path("terms/nueva-version/", TermsVersionCreateView.as_view(), name="terms-create"),
    path(
        "terms/<str:version_id>/<str:language>/set-current/",
        TermsSetCurrentView.as_view(),
        name="terms-set-current",
    ),
    path(
        "terms/<str:version_id>/<str:language>/",
        TermsVersionDetailView.as_view(),
        name="terms-detail",
    ),
]
