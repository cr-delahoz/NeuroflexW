from django.urls import path

from .views import AuditLogExportView, AuditLogListView, AuditLogPdfExportView

app_name = "audit"

urlpatterns = [
    path("audit/", AuditLogListView.as_view(), name="log-list"),
    path("audit/export/", AuditLogExportView.as_view(), name="log-export"),
    path("audit/export/pdf/", AuditLogPdfExportView.as_view(), name="log-export-pdf"),
]
