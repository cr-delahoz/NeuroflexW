import shutil
from pathlib import Path
from tempfile import mkdtemp
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from audit.models import AuditLog
from clinical_sessions.services import ExternalSessionServiceUnavailableError

from .models import ReportRequest


User = get_user_model()
TEST_MEDIA_ROOT = Path(mkdtemp())

SESSION_METRICS = {
    "Precision": 91.5,
    "TiempoActivoTarea": 22.4,
    "CantAciertasTotales": 10,
    "ObjetosInteractuadosCorrectamente": 8,
    "TiempoTutorial": 4.2,
    "TipoEscena": 1,
    "TiempoRespuestaPararse": 3.1,
    "TiempoRespuestaPregunta1": 1.1,
    "TiempoRespuestaPregunta2": 1.3,
    "TiempoRespuestaPregunta3": 1.5,
    "TiempoCapturarNumero": 2.8,
}

API_SESSION_WITH_METRICS = {
    "session_id": "SESSION-001",
    "display_code": "123456",
    "created_at": "2025-10-13T19:16:15.691686+00:00",
    "vr_user_email": None,
    "status": "completed",
    "metrics": SESSION_METRICS,
}

API_SESSION_WITHOUT_METRICS = {
    "session_id": "SESSION-001",
    "display_code": "123456",
    "created_at": "2025-10-13T19:16:15.691686+00:00",
    "vr_user_email": None,
    "status": "confirmed",
    "metrics": None,
}


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class ReportFlowTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    @classmethod
    def setUpTestData(cls):
        cls.admin_user = User.objects.create_user(
            username="admin_user",
            password="test-pass-123",
            role=User.Role.ADMIN,
            is_staff=True,
        )
        cls.specialist_user = User.objects.create_user(
            username="specialist_user",
            password="test-pass-123",
            role=User.Role.SPECIALIST,
            first_name="Pedro",
            last_name="Gonzalez",
        )
        cls.other_specialist = User.objects.create_user(
            username="other_specialist",
            password="test-pass-123",
            role=User.Role.SPECIALIST,
        )
        cls.permission_specialist = User.objects.create_user(
            username="permission_specialist",
            password="test-pass-123",
            role=User.Role.SPECIALIST,
            can_generate_pdf_without_approval=True,
        )

    def _login_specialist_with_neuroflex_session(self, username="specialist_user"):
        self.client.login(username=username, password="test-pass-123")
        session = self.client.session
        session["cognito_id_token"] = "fake-id-token"
        session["cognito_sub"] = "fake-sub"
        session.save()

    def _create_report_request(self, **overrides):
        defaults = {
            "session_id": "SESSION-001",
            "requested_by": self.specialist_user,
            "session_snapshot": API_SESSION_WITH_METRICS,
        }
        defaults.update(overrides)
        return ReportRequest.objects.create(**defaults)

    def _create_mock_pdf(self, report_request):
        report_request.file.save(
            f"report-{report_request.pk}.pdf",
            ContentFile(b"%PDF-1.4 mock"),
            save=False,
        )
        report_request.generated_at = timezone.now()
        report_request.status = ReportRequest.Status.GENERATED
        report_request.save(update_fields=["status", "file", "generated_at"])

    def test_only_specialist_can_create_report_request(self):
        self.client.login(username="admin_user", password="test-pass-123")

        response = self.client.post(
            reverse("reports:create"),
            {"session_id": "SESSION-001"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(ReportRequest.objects.exists())

    @patch(
        "reports.views.get_session_confirmed_by",
        return_value=API_SESSION_WITH_METRICS,
    )
    def test_specialist_can_create_report_request(self, mock_get_session):
        self._login_specialist_with_neuroflex_session()

        response = self.client.post(
            reverse("reports:create"),
            {
                "session_id": "SESSION-001",
                "specialist_observation": "Observacion breve",
            },
        )

        self.assertRedirects(response, reverse("reports:specialist-list"))
        report_request = ReportRequest.objects.get()
        self.assertEqual(report_request.status, ReportRequest.Status.PENDING)
        self.assertEqual(report_request.requested_by, self.specialist_user)
        self.assertEqual(report_request.specialist_observation, "Observacion breve")
        self.assertEqual(report_request.session_snapshot, API_SESSION_WITH_METRICS)
        mock_get_session.assert_called_once_with(
            "fake-sub", "fake-id-token", "SESSION-001"
        )
        self.assertTrue(
            AuditLog.objects.filter(
                actor=self.specialist_user,
                action="report_requested",
                resource_type="report_request",
                resource_id=str(report_request.pk),
            ).exists()
        )

    def test_missing_neuroflex_session_shows_error_without_calling_api(self):
        self.client.login(username="specialist_user", password="test-pass-123")

        with patch("reports.views.get_session_confirmed_by") as mock_get_session:
            response = self.client.post(
                reverse("reports:create"),
                {"session_id": "SESSION-001"},
            )

        mock_get_session.assert_not_called()
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Tu sesion con NeuroFlex expiro", status_code=400)
        self.assertFalse(ReportRequest.objects.exists())

    @patch("reports.views.get_session_confirmed_by", return_value=None)
    def test_session_not_found_for_specialist_is_rejected(self, mock_get_session):
        self._login_specialist_with_neuroflex_session()

        response = self.client.post(
            reverse("reports:create"),
            {"session_id": "UNKNOWN-SESSION"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertContains(
            response, "No se encontro la sesion para tu cuenta.", status_code=403
        )
        self.assertFalse(ReportRequest.objects.exists())

    @patch(
        "reports.views.get_session_confirmed_by",
        return_value=API_SESSION_WITHOUT_METRICS,
    )
    def test_session_without_metrics_cannot_request_report(self, mock_get_session):
        self._login_specialist_with_neuroflex_session()

        response = self.client.post(
            reverse("reports:create"),
            {"session_id": "SESSION-001"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(
            response,
            "La sesion aun no tiene metricas disponibles",
            status_code=400,
        )
        self.assertFalse(ReportRequest.objects.exists())

    @patch(
        "reports.views.get_session_confirmed_by",
        side_effect=ExternalSessionServiceUnavailableError("down"),
    )
    def test_api_unavailable_on_create_does_not_break_page(self, mock_get_session):
        self._login_specialist_with_neuroflex_session()

        response = self.client.post(
            reverse("reports:create"),
            {"session_id": "SESSION-001"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(ReportRequest.objects.exists())

    @patch(
        "reports.views.get_session_confirmed_by",
        return_value=API_SESSION_WITH_METRICS,
    )
    def test_requested_by_cannot_be_overridden_from_post(self, mock_get_session):
        self._login_specialist_with_neuroflex_session()

        self.client.post(
            reverse("reports:create"),
            {
                "session_id": "SESSION-001",
                "requested_by": self.other_specialist.pk,
            },
        )

        report_request = ReportRequest.objects.get()
        self.assertEqual(report_request.requested_by, self.specialist_user)

    def test_get_request_form_does_not_create_request(self):
        self.client.login(username="specialist_user", password="test-pass-123")

        response = self.client.get(reverse("reports:create"))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(ReportRequest.objects.exists())

    @patch(
        "reports.views.get_session_confirmed_by",
        return_value=API_SESSION_WITH_METRICS,
    )
    def test_duplicate_active_request_is_rejected(self, mock_get_session):
        self._create_report_request(status=ReportRequest.Status.GENERATED)
        self._login_specialist_with_neuroflex_session()

        response = self.client.post(
            reverse("reports:create"),
            {"session_id": "SESSION-001"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Ya existe una solicitud activa", status_code=400)
        self.assertTrue(
            AuditLog.objects.filter(
                actor=self.specialist_user,
                action="report_request_duplicate",
            ).exists()
        )

    @patch(
        "reports.views.get_session_confirmed_by",
        return_value=API_SESSION_WITH_METRICS,
    )
    def test_new_request_is_allowed_after_rejection(self, mock_get_session):
        self._create_report_request(status=ReportRequest.Status.REJECTED)
        self._login_specialist_with_neuroflex_session()

        response = self.client.post(
            reverse("reports:create"),
            {"session_id": "SESSION-001"},
        )

        self.assertRedirects(response, reverse("reports:specialist-list"))
        self.assertEqual(ReportRequest.objects.count(), 2)

    def test_specialist_only_sees_own_requests(self):
        own_request = self._create_report_request()
        other_request = self._create_report_request(
            session_id="SESSION-002", requested_by=self.other_specialist
        )
        self.client.login(username="specialist_user", password="test-pass-123")

        response = self.client.get(reverse("reports:specialist-list"))

        self.assertContains(response, own_request.session_id)
        self.assertNotContains(response, other_request.session_id)

    def test_admin_can_approve_pending_request_and_generate_pdf(self):
        report_request = self._create_report_request()
        self.client.login(username="admin_user", password="test-pass-123")

        with patch("reports.views.generate_report_file") as mock_generate:
            mock_generate.side_effect = (
                lambda req, *, actor, ip_address: self._create_mock_pdf(req)
            )
            response = self.client.post(reverse("reports:approve", args=[report_request.pk]))

        self.assertRedirects(response, reverse("reports:admin-list"))
        report_request.refresh_from_db()
        self.assertEqual(report_request.reviewed_by, self.admin_user)
        self.assertEqual(report_request.status, ReportRequest.Status.GENERATED)
        self.assertIsNotNone(report_request.generated_at)
        self.assertTrue(report_request.file.name.endswith(".pdf"))

    def test_reviewed_by_is_set_from_authenticated_admin(self):
        report_request = self._create_report_request()
        self.client.login(username="admin_user", password="test-pass-123")

        with patch("reports.views.generate_report_file") as mock_generate:
            mock_generate.side_effect = (
                lambda req, *, actor, ip_address: self._create_mock_pdf(req)
            )
            self.client.post(
                reverse("reports:approve", args=[report_request.pk]),
                {"reviewed_by": self.other_specialist.pk},
            )

        report_request.refresh_from_db()
        self.assertEqual(report_request.reviewed_by, self.admin_user)

    def test_admin_can_reject_pending_request_with_reason(self):
        report_request = self._create_report_request()
        self.client.login(username="admin_user", password="test-pass-123")

        response = self.client.post(
            reverse("reports:reject", args=[report_request.pk]),
            {"rejection_reason": "Falta validar la solicitud"},
        )

        self.assertRedirects(response, reverse("reports:admin-list"))
        report_request.refresh_from_db()
        self.assertEqual(report_request.status, ReportRequest.Status.REJECTED)
        self.assertEqual(report_request.reviewed_by, self.admin_user)

    def test_reject_requires_reason(self):
        report_request = self._create_report_request()
        self.client.login(username="admin_user", password="test-pass-123")

        response = self.client.post(
            reverse("reports:reject", args=[report_request.pk]),
            {"rejection_reason": "   "},
        )

        self.assertEqual(response.status_code, 400)
        report_request.refresh_from_db()
        self.assertEqual(report_request.status, ReportRequest.Status.PENDING)

    def test_cannot_approve_resolved_request(self):
        report_request = self._create_report_request(status=ReportRequest.Status.REJECTED)
        self.client.login(username="admin_user", password="test-pass-123")

        response = self.client.post(reverse("reports:approve", args=[report_request.pk]))

        self.assertEqual(response.status_code, 403)

    def test_cannot_reject_resolved_request(self):
        report_request = self._create_report_request(status=ReportRequest.Status.GENERATED)
        self.client.login(username="admin_user", password="test-pass-123")

        response = self.client.post(
            reverse("reports:reject", args=[report_request.pk]),
            {"rejection_reason": "No aplica"},
        )

        self.assertEqual(response.status_code, 403)

    def test_approve_and_reject_endpoints_do_not_allow_get(self):
        report_request = self._create_report_request()
        self.client.login(username="admin_user", password="test-pass-123")

        approve_response = self.client.get(reverse("reports:approve", args=[report_request.pk]))
        reject_response = self.client.get(reverse("reports:reject", args=[report_request.pk]))

        self.assertEqual(approve_response.status_code, 405)
        self.assertEqual(reject_response.status_code, 405)

    def test_specialist_cannot_access_admin_report_list(self):
        self.client.login(username="specialist_user", password="test-pass-123")

        response = self.client.get(reverse("reports:admin-list"))

        self.assertEqual(response.status_code, 403)

    def test_specialist_owner_can_download_generated_report(self):
        report_request = self._create_report_request()
        self.client.login(username="admin_user", password="test-pass-123")
        with patch("reports.views.generate_report_file") as mock_generate:
            mock_generate.side_effect = (
                lambda req, *, actor, ip_address: self._create_mock_pdf(req)
            )
            self.client.post(reverse("reports:approve", args=[report_request.pk]))
        self.client.logout()
        self.client.login(username="specialist_user", password="test-pass-123")

        response = self.client.get(reverse("reports:download", args=[report_request.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(
            AuditLog.objects.filter(
                actor=self.specialist_user,
                action="report_downloaded",
                resource_id=str(report_request.pk),
            ).exists()
        )

    def test_other_specialist_cannot_download_report(self):
        report_request = self._create_report_request()
        self.client.login(username="admin_user", password="test-pass-123")
        with patch("reports.views.generate_report_file") as mock_generate:
            mock_generate.side_effect = (
                lambda req, *, actor, ip_address: self._create_mock_pdf(req)
            )
            self.client.post(reverse("reports:approve", args=[report_request.pk]))
        self.client.logout()
        self.client.login(username="other_specialist", password="test-pass-123")

        response = self.client.get(reverse("reports:download", args=[report_request.pk]))

        self.assertEqual(response.status_code, 404)

    def test_admin_cannot_download_report(self):
        report_request = self._create_report_request(status=ReportRequest.Status.GENERATED)
        self.client.login(username="admin_user", password="test-pass-123")

        response = self.client.get(reverse("reports:download", args=[report_request.pk]))

        self.assertEqual(response.status_code, 403)

    def test_cannot_download_when_report_is_not_generated(self):
        report_request = self._create_report_request(status=ReportRequest.Status.PENDING)
        self.client.login(username="specialist_user", password="test-pass-123")

        response = self.client.get(reverse("reports:download", args=[report_request.pk]))

        self.assertEqual(response.status_code, 404)

    def test_pdf_contains_requester_name_traceability_and_metrics(self):
        report_request = self._create_report_request(
            specialist_observation="Observacion clinica inicial",
        )
        self.client.login(username="admin_user", password="test-pass-123")
        self.client.post(reverse("reports:approve", args=[report_request.pk]))
        report_request.refresh_from_db()

        pdf_bytes = report_request.file.read()
        self.assertIn(b"Pedro Gonzalez", pdf_bytes)
        self.assertIn(b"Informe de sesion", pdf_bytes)
        self.assertIn(b"Trazabilidad del documento", pdf_bytes)
        self.assertIn(b"Precision", pdf_bytes)
        self.assertIn(b"Tiempo activo en la tarea", pdf_bytes)
        self.assertIn(b"Resultado automatizado provisional", pdf_bytes)

    def test_pdf_includes_real_model_result_when_metrics_are_complete(self):
        full_metrics = dict(SESSION_METRICS, TiempoReaccionVisual=0.9)
        report_request = self._create_report_request(
            session_snapshot=dict(API_SESSION_WITH_METRICS, metrics=full_metrics),
        )
        self.client.login(username="admin_user", password="test-pass-123")
        self.client.post(reverse("reports:approve", args=[report_request.pk]))
        report_request.refresh_from_db()

        pdf_bytes = report_request.file.read()
        self.assertIn(b"Indicador provisional del modelo", pdf_bytes)
        self.assertIn(b"Puntuacion tecnica", pdf_bytes)
        self.assertIn(b"Resultado automatizado provisional", pdf_bytes)
        self.assertNotIn(b"Procedencia tecnica del resultado", pdf_bytes)

    def test_pdf_uses_username_when_full_name_is_missing(self):
        report_request = self._create_report_request(
            requested_by=self.other_specialist,
        )
        self.client.login(username="admin_user", password="test-pass-123")
        self.client.post(reverse("reports:approve", args=[report_request.pk]))
        report_request.refresh_from_db()

        pdf_bytes = report_request.file.read()
        self.assertIn(b"other_specialist", pdf_bytes)

    def test_generation_failure_sets_error_status(self):
        report_request = self._create_report_request()
        self.client.login(username="admin_user", password="test-pass-123")

        with patch(
            "reports.services.normalize_snapshot_for_report",
            side_effect=Exception("boom"),
        ):
            self.client.post(reverse("reports:approve", args=[report_request.pk]))

        report_request.refresh_from_db()
        self.assertEqual(report_request.status, ReportRequest.Status.ERROR)
        self.assertEqual(report_request.technical_error_message, "boom")

    def test_file_must_exist_for_download(self):
        report_request = self._create_report_request(status=ReportRequest.Status.GENERATED)
        self.client.login(username="specialist_user", password="test-pass-123")

        response = self.client.get(reverse("reports:download", args=[report_request.pk]))

        self.assertEqual(response.status_code, 404)

    def test_specialist_without_permission_still_requires_approval(self):
        with patch(
            "reports.views.get_session_confirmed_by",
            return_value=API_SESSION_WITH_METRICS,
        ):
            self._login_specialist_with_neuroflex_session()
            self.client.post(
                reverse("reports:create"),
                {"session_id": "SESSION-001"},
            )

        report_request = ReportRequest.objects.get()
        self.assertEqual(report_request.status, ReportRequest.Status.PENDING)
        self.assertFalse(
            AuditLog.objects.filter(action="pdf_auto_generated").exists()
        )

    def test_specialist_with_permission_gets_pdf_immediately(self):
        with patch(
            "reports.views.get_session_confirmed_by",
            return_value=API_SESSION_WITH_METRICS,
        ):
            self._login_specialist_with_neuroflex_session(username="permission_specialist")
            response = self.client.post(
                reverse("reports:create"),
                {"session_id": "SESSION-001"},
            )

        self.assertRedirects(response, reverse("reports:specialist-list"))
        report_request = ReportRequest.objects.get()
        self.assertEqual(report_request.status, ReportRequest.Status.GENERATED)
        self.assertIsNone(report_request.reviewed_by)
        self.assertIsNotNone(report_request.reviewed_at)
        self.assertTrue(report_request.file.name.endswith(".pdf"))
        self.assertTrue(
            AuditLog.objects.filter(
                actor=self.permission_specialist,
                action="pdf_auto_generated",
                resource_id=str(report_request.pk),
            ).exists()
        )
        self.assertFalse(
            AuditLog.objects.filter(action="report_approved").exists()
        )

        pdf_bytes = report_request.file.read()
        self.assertIn(b"Autogenerado sin aprobacion", pdf_bytes)

    def test_auto_generate_failure_sets_error_status(self):
        from .services import auto_generate_report

        report_request = self._create_report_request()

        with patch(
            "reports.services.normalize_snapshot_for_report",
            side_effect=Exception("boom"),
        ):
            auto_generate_report(report_request, actor=self.specialist_user, ip_address="127.0.0.1")

        report_request.refresh_from_db()
        self.assertEqual(report_request.status, ReportRequest.Status.ERROR)
        self.assertEqual(report_request.technical_error_message, "boom")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class AdminReportDownloadTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    @classmethod
    def setUpTestData(cls):
        cls.admin_user = User.objects.create_user(
            username="admin_user",
            password="test-pass-123",
            role=User.Role.ADMIN,
            is_staff=True,
        )
        cls.specialist_user = User.objects.create_user(
            username="specialist_user",
            password="test-pass-123",
            role=User.Role.SPECIALIST,
        )

    def _create_mock_pdf(self, report_request):
        report_request.file.save(
            f"report-{report_request.pk}.pdf",
            ContentFile(b"%PDF-1.4 mock"),
            save=False,
        )
        report_request.generated_at = timezone.now()
        report_request.status = ReportRequest.Status.GENERATED
        report_request.save(update_fields=["status", "file", "generated_at"])

    def _create_orphaned_report(self, real_pdf=False, **overrides):
        defaults = {
            "session_id": "ORPHAN-1",
            "requested_by": None,
            "status": ReportRequest.Status.PENDING,
            "session_snapshot": API_SESSION_WITH_METRICS,
        }
        defaults.update(overrides)
        report_request = ReportRequest.objects.create(**defaults)
        if defaults["status"] == ReportRequest.Status.GENERATED:
            if real_pdf:
                from .services import generate_report_file
                generate_report_file(report_request, actor=self.admin_user, ip_address="127.0.0.1")
            else:
                self._create_mock_pdf(report_request)
        return report_request

    def test_admin_can_download_orphaned_report(self):
        report_request = self._create_orphaned_report(
            status=ReportRequest.Status.GENERATED
        )
        self.client.login(username="admin_user", password="test-pass-123")

        response = self.client.get(
            reverse("reports:admin-download", args=[report_request.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(
            AuditLog.objects.filter(
                actor=self.admin_user,
                action="unassociated_report_downloaded",
                resource_id=str(report_request.pk),
            ).exists()
        )

    def test_specialist_cannot_use_admin_download(self):
        report_request = self._create_orphaned_report()
        self.client.login(username="specialist_user", password="test-pass-123")

        response = self.client.get(
            reverse("reports:admin-download", args=[report_request.pk])
        )

        self.assertEqual(response.status_code, 403)

    def test_admin_download_404s_for_report_with_owner(self):
        report_request = ReportRequest.objects.create(
            session_id="OWNED-1",
            requested_by=self.specialist_user,
            status=ReportRequest.Status.GENERATED,
            session_snapshot=API_SESSION_WITH_METRICS,
        )
        self.client.login(username="admin_user", password="test-pass-123")

        response = self.client.get(
            reverse("reports:admin-download", args=[report_request.pk])
        )

        self.assertEqual(response.status_code, 404)

    def test_admin_download_404s_when_report_not_generated(self):
        report_request = self._create_orphaned_report(
            status=ReportRequest.Status.PENDING
        )
        self.client.login(username="admin_user", password="test-pass-123")

        response = self.client.get(
            reverse("reports:admin-download", args=[report_request.pk])
        )

        self.assertEqual(response.status_code, 404)

    def test_pdf_shows_deleted_specialist_fallback(self):
        report_request = self._create_orphaned_report(
            status=ReportRequest.Status.GENERATED,
            real_pdf=True,
        )
        report_request.refresh_from_db()

        pdf_bytes = report_request.file.read()
        self.assertIn(b"Especialista eliminado", pdf_bytes)
