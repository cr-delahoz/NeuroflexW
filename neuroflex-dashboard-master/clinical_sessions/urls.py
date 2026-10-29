from django.urls import path

from . import views

app_name = "clinical_sessions"

urlpatterns = [
    path(
        "clinical-sessions/",
        views.SessionListView.as_view(),
        name="session-list",
    ),
    path(
        "clinical-sessions/new/",
        views.SessionConfirmView.as_view(),
        name="session-confirm",
    ),
    path(
        "clinical-sessions/active/",
        views.ActiveSessionsView.as_view(),
        name="session-active",
    ),
    path(
        "clinical-sessions/unassociated/",
        views.UnassociatedSessionsView.as_view(),
        name="unassociated-sessions",
    ),
    path(
        "clinical-sessions/<str:session_id>/",
        views.SessionDetailView.as_view(),
        name="session-detail",
    ),
]
