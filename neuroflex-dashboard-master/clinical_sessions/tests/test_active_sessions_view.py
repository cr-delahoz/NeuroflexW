import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

User = get_user_model()


class ActiveSessionsViewTests(TestCase):
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

    def test_unauthenticated_user_cannot_access(self):
        response = self.client.get(reverse("clinical_sessions:session-active"))

        self.assertEqual(response.status_code, 302)

    @patch("clinical_sessions.views.list_sessions_confirmed_by")
    def test_returns_only_confirmed_sessions(self, mock_list):
        mock_list.return_value = [
            {"session_id": "ACTIVE-1", "status": "confirmed"},
            {"session_id": "FINISHED-1", "status": "completed"},
        ]
        self._login_with_neuroflex_session()

        response = self.client.get(reverse("clinical_sessions:session-active"))
        payload = json.loads(response.content)

        session_ids = [item["session_id"] for item in payload["active_sessions"]]
        self.assertEqual(session_ids, ["ACTIVE-1"])
        mock_list.assert_called_once_with("fake-sub", "fake-id-token")

    def test_missing_neuroflex_session_returns_empty_list_without_calling_api(self):
        self.client.login(username="specialist_user", password="test-pass-123")

        with patch(
            "clinical_sessions.views.list_sessions_confirmed_by"
        ) as mock_list:
            response = self.client.get(reverse("clinical_sessions:session-active"))

        mock_list.assert_not_called()
        payload = json.loads(response.content)
        self.assertEqual(payload["active_sessions"], [])

    def test_admin_cannot_access(self):
        admin_user = User.objects.create_user(
            username="admin_user",
            password="test-pass-123",
            role=User.Role.ADMIN,
        )
        self.client.login(username="admin_user", password="test-pass-123")

        response = self.client.get(reverse("clinical_sessions:session-active"))

        self.assertEqual(response.status_code, 403)
