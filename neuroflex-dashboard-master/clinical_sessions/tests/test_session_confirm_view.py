from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from audit.models import AuditLog
from clinical_sessions.models import SpecialistSession
from clinical_sessions.services.external_session_client import InvalidDisplayCodeError

User = get_user_model()


class SessionConfirmViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.specialist_user = User.objects.create_user(
            username="specialist_user",
            password="test-pass-123",
            role=User.Role.SPECIALIST,
        )
        cls.other_specialist = User.objects.create_user(
            username="other_specialist",
            password="test-pass-123",
            role=User.Role.SPECIALIST,
        )

    def _login_with_id_token(self, username, id_token="fake-id-token"):
        self.client.login(username=username, password="test-pass-123")
        session = self.client.session
        session["cognito_id_token"] = id_token
        session.save()

    def test_unauthenticated_user_cannot_access(self):
        response = self.client.get(reverse("clinical_sessions:session-confirm"))

        self.assertEqual(response.status_code, 302)

    @patch("clinical_sessions.views.confirm_and_associate_session")
    def test_specialist_can_confirm_session(self, mock_confirm):
        mock_confirm.return_value = SpecialistSession(
            specialist=self.specialist_user,
            session_id="SESSION-999",
            status="confirmed",
        )
        self._login_with_id_token("specialist_user")

        response = self.client.post(
            reverse("clinical_sessions:session-confirm"),
            {"display_code": "123456"},
        )

        self.assertRedirects(response, reverse("clinical_sessions:session-list"))
        mock_confirm.assert_called_once_with(
            self.specialist_user, "123456", "fake-id-token"
        )
        self.assertTrue(
            AuditLog.objects.filter(
                actor=self.specialist_user,
                action="session_confirmed",
                resource_id="SESSION-999",
            ).exists()
        )

    @patch(
        "clinical_sessions.views.confirm_and_associate_session",
        side_effect=InvalidDisplayCodeError("El codigo no es valido."),
    )
    def test_invalid_display_code_shows_form_error(self, mock_confirm):
        self._login_with_id_token("specialist_user")

        response = self.client.post(
            reverse("clinical_sessions:session-confirm"),
            {"display_code": "000000"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "El codigo no es valido.", status_code=400)

    def test_missing_cognito_id_token_shows_form_error(self):
        self.client.login(username="specialist_user", password="test-pass-123")

        response = self.client.post(
            reverse("clinical_sessions:session-confirm"),
            {"display_code": "123456"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Tu sesion con NeuroFlex expiro", status_code=400)
        self.assertFalse(SpecialistSession.objects.exists())

    def test_admin_cannot_access(self):
        admin_user = User.objects.create_user(
            username="admin_user",
            password="test-pass-123",
            role=User.Role.ADMIN,
        )
        self.client.login(username="admin_user", password="test-pass-123")

        response = self.client.get(reverse("clinical_sessions:session-confirm"))

        self.assertEqual(response.status_code, 403)
