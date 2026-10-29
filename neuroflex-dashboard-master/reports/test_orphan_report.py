from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import reverse

from clinical_sessions.models import SpecialistSession
from reports.models import ReportRequest

User = get_user_model()

METRICS = {
    "TiempoRespuestaPararse": 0.0,
    "TiempoRespuestaPregunta1": 10.2,
    "TiempoRespuestaPregunta2": 17.4,
    "TiempoRespuestaPregunta3": 8.7,
    "TiempoReaccionVisual": 0.81,
    "TiempoCapturarNumero": 9.5,
    "TipoEscena": 2,
}

ORPHAN_URL = "reports:admin-generate-orphan"
LIST_URL = "clinical_sessions:unassociated-sessions"


@patch(
    "reports.services.predict_cognitive_result",
    return_value={"available": False, "user_message": "n/a"},
)
class AdminGenerateOrphanReportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="adm", password="p", role=User.Role.ADMIN
        )
        cls.specialist = User.objects.create_user(
            username="spec", password="p", role=User.Role.SPECIALIST
        )

    def _create_mock_pdf(self, report_request):
        report_request.file.save(
            f"report-{report_request.pk}.pdf",
            ContentFile(b"%PDF-1.4 mock"),
            save=False,
        )
        report_request.status = ReportRequest.Status.GENERATED
        report_request.save(update_fields=["status", "file"])

    def test_admin_generates_report_from_cached_metrics(self, _mock_pred):
        SpecialistSession.objects.create(
            specialist=None, session_id="ORPH-1", status="completed", metrics=METRICS
        )
        self.client.force_login(self.admin)

        with patch("reports.views.generate_report_file") as mock_generate:
            mock_generate.side_effect = (
                lambda req, *, actor, ip_address: self._create_mock_pdf(req)
            )
            response = self.client.post(reverse(ORPHAN_URL), {"session_id": "ORPH-1"})

        self.assertRedirects(response, reverse(LIST_URL))
        report = ReportRequest.objects.get(session_id="ORPH-1")
        self.assertEqual(report.status, ReportRequest.Status.GENERATED)
        self.assertTrue(report.file)
        self.assertIsNone(report.requested_by)
        self.assertEqual(report.reviewed_by, self.admin)

    def test_blocked_without_local_metrics(self, _mock_pred):
        SpecialistSession.objects.create(
            specialist=None, session_id="ORPH-2", status="completed", metrics={}
        )
        self.client.force_login(self.admin)

        self.client.post(reverse(ORPHAN_URL), {"session_id": "ORPH-2"})

        self.assertFalse(ReportRequest.objects.filter(session_id="ORPH-2").exists())

    def test_blocked_when_active_report_already_exists(self, _mock_pred):
        SpecialistSession.objects.create(
            specialist=None, session_id="ORPH-3", status="completed", metrics=METRICS
        )
        ReportRequest.objects.create(
            session_id="ORPH-3",
            requested_by=None,
            status=ReportRequest.Status.GENERATED,
        )
        self.client.force_login(self.admin)

        self.client.post(reverse(ORPHAN_URL), {"session_id": "ORPH-3"})

        self.assertEqual(ReportRequest.objects.filter(session_id="ORPH-3").count(), 1)

    def test_session_still_owned_is_blocked(self, _mock_pred):
        SpecialistSession.objects.create(
            specialist=self.specialist,
            session_id="OWNED-1",
            status="completed",
            metrics=METRICS,
        )
        self.client.force_login(self.admin)

        self.client.post(reverse(ORPHAN_URL), {"session_id": "OWNED-1"})

        self.assertFalse(ReportRequest.objects.filter(session_id="OWNED-1").exists())

    def test_non_admin_is_forbidden(self, _mock_pred):
        SpecialistSession.objects.create(
            specialist=None, session_id="ORPH-4", status="completed", metrics=METRICS
        )
        self.client.force_login(self.specialist)

        response = self.client.post(reverse(ORPHAN_URL), {"session_id": "ORPH-4"})

        self.assertEqual(response.status_code, 403)
        self.assertFalse(ReportRequest.objects.filter(session_id="ORPH-4").exists())
