from django.urls import path

from .views import (
    AdminGenerateOrphanReportView,
    AdminReportDownloadView,
    AdminReportListView,
    ReportApproveView,
    ReportDownloadView,
    ReportRejectView,
    ReportRequestCreateView,
    SpecialistReportListView,
)

app_name = "reports"

urlpatterns = [
    path("reports/", SpecialistReportListView.as_view(), name="specialist-list"),
    path("reports/new/", ReportRequestCreateView.as_view(), name="create"),
    path("admin-dashboard/reports/", AdminReportListView.as_view(), name="admin-list"),
    path(
        "admin-dashboard/reports/<int:report_id>/approve/",
        ReportApproveView.as_view(),
        name="approve",
    ),
    path(
        "admin-dashboard/reports/<int:report_id>/reject/",
        ReportRejectView.as_view(),
        name="reject",
    ),
    path("reports/<int:report_id>/download/", ReportDownloadView.as_view(), name="download"),
    path(
        "admin-dashboard/reports/<int:report_id>/admin-download/",
        AdminReportDownloadView.as_view(),
        name="admin-download",
    ),
    path(
        "admin-dashboard/reports/generate-orphan/",
        AdminGenerateOrphanReportView.as_view(),
        name="admin-generate-orphan",
    ),
]
