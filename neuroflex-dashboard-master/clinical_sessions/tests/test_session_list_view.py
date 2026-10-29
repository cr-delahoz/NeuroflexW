from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from clinical_sessions.services.external_session_client import (
    ExternalSessionServiceUnavailableError,
)

User = get_user_model()

FAKE_SESSIONS = [
    {
        "session_id": "ACTIVE-1",
        "display_code": "111111",
        "created_at": "2026-07-08T20:01:19.146575+00:00",
        "vr_user_email": None,
        "status": "confirmed",
        "metrics": None,
    },
    {
        "session_id": "COMPLETED-1",
        "display_code": "222222",
        "created_at": "2026-07-01T10:00:00+00:00",
        "vr_user_email": "patient@example.com",
        "status": "completed",
        "metrics": {"precision": 91.5},
    },
    {
        "session_id": "COMPLETED-2",
        "display_code": "333333",
        "created_at": "2026-06-30T10:00:00+00:00",
        "vr_user_email": None,
        "status": "completed",
        "metrics": None,
    },
]


class SessionListViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.specialist_user = User.objects.create_user(
            username="specialist_user",
            password="test-pass-123",
            role=User.Role.SPECIALIST,
        )

    def _login_with_neuroflex_session(self):
        self.client.login(username="specialist_user", password="test-pass-123")
        session = self.client.session
        session["cognito_id_token"] = "fake-id-token"
        session["cognito_sub"] = "fake-sub"
        session.save()

    def test_missing_neuroflex_session_shows_warning_without_calling_api(self):
        self.client.login(username="specialist_user", password="test-pass-123")

        with patch(
            "clinical_sessions.views.list_sessions_confirmed_by"
        ) as mock_list:
            response = self.client.get(reverse("clinical_sessions:session-list"))

        mock_list.assert_not_called()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tu sesion con NeuroFlex expiro")

    @patch("clinical_sessions.views.list_sessions_confirmed_by")
    def test_separates_active_and_completed_sessions(self, mock_list):
        mock_list.return_value = FAKE_SESSIONS
        self._login_with_neuroflex_session()

        response = self.client.get(reverse("clinical_sessions:session-list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ACTIVE-1")
        self.assertContains(response, "COMPLETED-1")
        mock_list.assert_called_once_with("fake-sub", "fake-id-token")

    @patch("clinical_sessions.views.list_sessions_confirmed_by")
    def test_status_filter_completed_hides_active_sessions(self, mock_list):
        mock_list.return_value = FAKE_SESSIONS
        self._login_with_neuroflex_session()

        response = self.client.get(
            reverse("clinical_sessions:session-list"), {"status": "completed"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "ACTIVE-1")
        self.assertContains(response, "COMPLETED-1")

    @patch("clinical_sessions.views.list_sessions_confirmed_by")
    def test_status_filter_confirmed_hides_completed_sessions(self, mock_list):
        mock_list.return_value = FAKE_SESSIONS
        self._login_with_neuroflex_session()

        response = self.client.get(
            reverse("clinical_sessions:session-list"), {"status": "confirmed"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ACTIVE-1")
        self.assertNotContains(response, "COMPLETED-1")

    @patch(
        "clinical_sessions.views.list_sessions_confirmed_by",
        side_effect=ExternalSessionServiceUnavailableError("down"),
    )
    def test_api_unavailable_shows_error_without_breaking_page(self, mock_list):
        self._login_with_neuroflex_session()

        response = self.client.get(reverse("clinical_sessions:session-list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "down")

    @patch("clinical_sessions.views.list_sessions_confirmed_by")
    def test_shows_metrics_availability_pill_per_completed_session(self, mock_list):
        mock_list.return_value = FAKE_SESSIONS
        self._login_with_neuroflex_session()

        response = self.client.get(reverse("clinical_sessions:session-list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Disponible")
        self.assertContains(response, "No Disponible")
        self.assertNotContains(response, "Ver metricas")
