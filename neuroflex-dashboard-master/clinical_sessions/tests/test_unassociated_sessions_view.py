from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from clinical_sessions.models import SpecialistSession
from reports.models import ReportRequest

User = get_user_model()


class UnassociatedSessionsViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin_user = User.objects.create_user(
            username="admin_user",
            password="test-pass-123",
            role=User.Role.ADMIN,
        )
        cls.specialist_user = User.objects.create_user(
            username="specialist_user",
            password="test-pass-123",
            role=User.Role.SPECIALIST,
        )

    def test_lists_only_sessions_without_a_specialist(self):
        orphaned = SpecialistSession.objects.create(
            specialist=None, session_id="ORPHAN-1", status="completed"
        )
        owned = SpecialistSession.objects.create(
            specialist=self.specialist_user, session_id="OWNED-1", status="completed"
        )
        self.client.login(username="admin_user", password="test-pass-123")

        response = self.client.get(reverse("clinical_sessions:unassociated-sessions"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, orphaned.session_id)
        self.assertNotContains(response, owned.session_id)

    def test_specialist_role_is_forbidden(self):
        SpecialistSession.objects.create(
            specialist=None, session_id="ORPHAN-1", status="completed"
        )
        self.client.login(username="specialist_user", password="test-pass-123")

        response = self.client.get(reverse("clinical_sessions:unassociated-sessions"))

        self.assertEqual(response.status_code, 403)

    def test_shows_download_link_for_generated_orphaned_report(self):
        SpecialistSession.objects.create(
            specialist=None, session_id="ORPHAN-1", status="completed"
        )
        report = ReportRequest.objects.create(
            session_id="ORPHAN-1",
            requested_by=None,
            status=ReportRequest.Status.GENERATED,
        )
        self.client.login(username="admin_user", password="test-pass-123")

        response = self.client.get(reverse("clinical_sessions:unassociated-sessions"))

        self.assertContains(
            response, reverse("reports:admin-download", args=[report.pk])
        )

    def test_no_download_link_when_report_is_not_generated(self):
        SpecialistSession.objects.create(
            specialist=None, session_id="ORPHAN-1", status="completed"
        )
        ReportRequest.objects.create(
            session_id="ORPHAN-1",
            requested_by=None,
            status=ReportRequest.Status.PENDING,
        )
        self.client.login(username="admin_user", password="test-pass-123")

        response = self.client.get(reverse("clinical_sessions:unassociated-sessions"))

        self.assertContains(response, "Sin informe generado")
