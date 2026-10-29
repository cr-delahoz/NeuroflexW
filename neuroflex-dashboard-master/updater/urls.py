from django.urls import path
from . import views

app_name = "updater"
urlpatterns = [
    path("check/", views.UpdateCheckView.as_view(), name="check"),
    path("run/", views.UpdateRunView.as_view(), name="run"),
    path("progress/<str:job_id>/", views.UpdateProgressView.as_view(), name="progress"),
]
