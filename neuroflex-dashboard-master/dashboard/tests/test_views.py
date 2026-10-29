import base64
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse


User = get_user_model()


def _build_fake_jwt(claims):
    def _b64(segment):
        return base64.urlsafe_b64encode(json.dumps(segment).encode()).rstrip(b"=").decode()

    return f"{_b64({'alg': 'RS256'})}.{_b64(claims)}.fake-signature"


def _mock_cognito_success(*args, **kwargs):
    return {
        "status": "authenticated",
        "id_token": _build_fake_jwt({"sub": "known-sub-123"}),
        "access_token": "fake-access-token",
        "refresh_token": "fake-refresh-token",
        "expires_in": 3600,
    }


class DashboardAccessTests(TestCase):
    def setUp(self):
        # El login online exitoso ahora sincroniza TyC; se aísla para que los
        # tests no realicen llamadas de red reales.
        self.terms_sync_patcher = patch("accounts.views.sync_terms_versions")
        self.terms_sync_patcher.start()
        self.addCleanup(self.terms_sync_patcher.stop)

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

    def test_unauthenticated_user_is_redirected_to_login(self):
        response = self.client.get(reverse("dashboard:admin"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_admin_user_can_access_admin_dashboard(self):
        self.client.login(username="admin_user", password="test-pass-123")

        response = self.client.get(reverse("dashboard:admin"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dashboard administrativo")

    def test_admin_dashboard_shows_unassociated_sessions_count(self):
        from clinical_sessions.models import SpecialistSession

        SpecialistSession.objects.create(
            specialist=None, session_id="ORPHAN-1", status="completed"
        )
        SpecialistSession.objects.create(
            specialist=self.specialist_user, session_id="OWNED-1", status="completed"
        )
        self.client.login(username="admin_user", password="test-pass-123")

        response = self.client.get(reverse("dashboard:admin"))

        self.assertEqual(response.context["unassociated_sessions_count"], 1)
        self.assertContains(response, "Sesiones no asociadas")

    def test_specialist_user_can_access_specialist_dashboard(self):
        self.client.login(username="specialist_user", password="test-pass-123")

        response = self.client.get(reverse("dashboard:specialist"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dashboard de especialista")

    def test_admin_user_cannot_access_specialist_dashboard(self):
        self.client.login(username="admin_user", password="test-pass-123")

        response = self.client.get(reverse("dashboard:specialist"))

        self.assertEqual(response.status_code, 403)

    def test_specialist_user_cannot_access_admin_dashboard(self):
        self.client.login(username="specialist_user", password="test-pass-123")

        response = self.client.get(reverse("dashboard:admin"))

        self.assertEqual(response.status_code, 403)

    @override_settings(
        AUTHENTICATION_BACKENDS=["django.contrib.auth.backends.AllowAllUsersModelBackend"]
    )
    def test_authenticated_inactive_user_cannot_access_admin_dashboard(self):
        self.admin_user.is_active = False
        self.admin_user.save(update_fields=["is_active"])
        self.client.force_login(
            self.admin_user,
            backend="django.contrib.auth.backends.AllowAllUsersModelBackend",
        )

        response = self.client.get(reverse("dashboard:admin"))

        self.assertEqual(response.status_code, 403)

    @patch("accounts.views.is_online", return_value=True)
    @patch(
        "integrations.services.neuroflex_api_client.RuntimeConfig.get_neuroflex_api_base_url",
        return_value="https://api.example.test/dev",
    )
    @patch(
        "accounts.forms.RuntimeConfig.get_cognito_client_id",
        return_value="test-client-id",
    )
    @patch(
        "accounts.forms.ApiGatewayUsersClient.get_user",
        return_value={
            "user_id": "known-sub-123",
            "email": "admin_user",
            "role": "Administrator",
            "is_active": True,
        },
    )
    @patch(
        "accounts.forms.CognitoAuthClient.initiate_auth",
        side_effect=_mock_cognito_success,
    )
    def test_login_redirects_admin_to_admin_dashboard(
        self,
        mock_initiate_auth,
        mock_get_user,
        mock_cognito_client_id,
        mock_base_url,
        mock_is_online,
    ):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "admin_user", "password": "test-pass-123"},
        )

        self.assertRedirects(response, reverse("dashboard:admin"))

    @patch("accounts.views.is_online", return_value=True)
    @patch(
        "integrations.services.neuroflex_api_client.RuntimeConfig.get_neuroflex_api_base_url",
        return_value="https://api.example.test/dev",
    )
    @patch(
        "accounts.forms.RuntimeConfig.get_cognito_client_id",
        return_value="test-client-id",
    )
    @patch(
        "accounts.forms.ApiGatewayUsersClient.get_user",
        return_value={
            "user_id": "known-sub-123",
            "email": "specialist_user",
            "role": "Specialist",
            "is_active": True,
        },
    )
    @patch(
        "accounts.forms.CognitoAuthClient.initiate_auth",
        side_effect=_mock_cognito_success,
    )
    def test_login_redirects_specialist_to_specialist_dashboard(
        self,
        mock_initiate_auth,
        mock_get_user,
        mock_cognito_client_id,
        mock_base_url,
        mock_is_online,
    ):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "specialist_user", "password": "test-pass-123"},
        )

        self.assertRedirects(response, reverse("dashboard:specialist"))
