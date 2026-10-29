import base64
import json
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from audit.models import AuditLog
from integrations.services.api_gateway_users_client import ApiGatewayUsersServiceError
from integrations.services.cognito_auth_client import CognitoInvalidCredentialsError
from integrations.services.cognito_signup_client import (
    CognitoCodeMismatchError,
    CognitoConfigurationError,
    CognitoInvalidParameterError,
    CognitoLimitExceededError,
    CognitoNetworkError,
    CognitoNotAuthorizedError,
    CognitoServiceError,
    CognitoUserNotConfirmedError,
    CognitoUserNotFoundError,
)
from accounts.services import sync_local_user_from_remote_user


User = get_user_model()


def _build_fake_jwt(claims):
    def _b64(segment):
        return base64.urlsafe_b64encode(json.dumps(segment).encode()).rstrip(b"=").decode()

    return f"{_b64({'alg': 'RS256'})}.{_b64(claims)}.fake-signature"


def _mock_cognito_success_with_sub(*args, **kwargs):
    return _mock_cognito_success_with_claims({"sub": "known-sub-123"})


def _mock_cognito_success_with_claims(claims):
    return {
        "status": "authenticated",
        "id_token": _build_fake_jwt(claims),
        "access_token": "fake-access-token",
        "refresh_token": "fake-refresh-token",
        "expires_in": 3600,
    }


def _remote_user(sub, email, role="Specialist", is_active=True):
    return {
        "user_id": sub,
        "email": email,
        "role": role,
        "is_active": is_active,
    }


class UserManagementTests(TestCase):
    def setUp(self):
        runtime = Mock()
        runtime.get_cognito_client_id.return_value = "test-client-id"
        runtime.get_neuroflex_api_base_url.return_value = "https://api.example.test/dev"
        self.cognito_patcher = patch(
            "integrations.services.cognito_signup_client.RuntimeConfig",
            return_value=runtime,
        )
        self.neuroflex_patcher = patch(
            "integrations.services.neuroflex_api_client.RuntimeConfig",
            return_value=runtime,
        )
        self.online_patcher = patch("accounts.views.is_online", return_value=True)
        # El login online exitoso ahora sincroniza TyC; se aísla para que los
        # tests no realicen llamadas de red reales.
        self.terms_sync_patcher = patch("accounts.views.sync_terms_versions")
        self.cognito_patcher.start()
        self.neuroflex_patcher.start()
        self.online_patcher.start()
        self.terms_sync_patcher.start()
        self.addCleanup(self.cognito_patcher.stop)
        self.addCleanup(self.neuroflex_patcher.stop)
        self.addCleanup(self.online_patcher.stop)
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

    @patch("accounts.views.reconcile_local_users_from_remote_listing")
    def test_admin_can_list_users(self, mock_reconcile):
        self.client.login(username="admin_user", password="test-pass-123")
        session = self.client.session
        session["cognito_id_token"] = "id-token"
        session.save()
        mock_reconcile.return_value = [self.admin_user, self.specialist_user]

        response = self.client.get(reverse("accounts:user-list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "admin_user")
        self.assertContains(response, "specialist_user")

    def test_non_authenticated_user_cannot_list_users(self):
        response = self.client.get(reverse("accounts:user-list"))

        self.assertEqual(response.status_code, 302)

    def test_specialist_cannot_list_users(self):
        self.client.login(username="specialist_user", password="test-pass-123")

        response = self.client.get(reverse("accounts:user-list"))

        self.assertEqual(response.status_code, 403)

    @patch(
        "accounts.views.ApiGatewayUsersClient.create_user",
        return_value=_remote_user("sub-ana", "ana@example.com"),
    )
    @patch("accounts.views.CognitoSignUpClient.confirm_sign_up")
    @patch("accounts.views.CognitoSignUpClient.sign_up")
    def test_admin_creates_remote_user_without_legacy_signup(
        self, mock_sign_up, mock_confirm, mock_create
    ):
        self.client.login(username="admin_user", password="test-pass-123")
        session = self.client.session
        session["cognito_id_token"] = "id-token"
        session.save()

        response = self.client.post(
            reverse("accounts:user-create"),
            {
                "first_name": "Ana",
                "last_name": "Perez",
                "email": "ana@example.com",
                "role": "Specialist",
            },
        )

        self.assertRedirects(response, reverse("accounts:user-list"), fetch_redirect_response=False)
        mock_create.assert_called_once_with(
            "id-token", "ana@example.com", "Specialist", profession_id="sin-profesion"
        )
        mock_sign_up.assert_not_called()
        mock_confirm.assert_not_called()
        messages = list(response.wsgi_request._messages)
        self.assertTrue(
            any("Se enviará una contraseña temporal a su correo" in str(m) for m in messages)
        )
        created_user = User.objects.get(cognito_sub="sub-ana")
        self.assertEqual(created_user.role, User.Role.SPECIALIST)
        self.assertEqual(created_user.first_name, "Ana")
        self.assertEqual(created_user.last_name, "Perez")
        self.assertTrue(
            AuditLog.objects.filter(
                actor=self.admin_user,
                action="user_created",
                resource_type="user",
                resource_id="sub-ana",
                result=AuditLog.Result.SUCCESS,
                metadata={"role": "Specialist", "profession_id": "sin-profesion"},
            ).exists()
        )

    @patch(
        "accounts.views.ApiGatewayUsersClient.create_user",
        side_effect=ApiGatewayUsersServiceError("duplicate"),
    )
    def test_remote_create_failure_does_not_audit_success(self, mock_create):
        self.client.login(username="admin_user", password="test-pass-123")
        session = self.client.session
        session["cognito_id_token"] = "id-token"
        session.save()

        response = self.client.post(
            reverse("accounts:user-create"),
            {
                "first_name": "Ana",
                "last_name": "Perez",
                "email": "duplicate@example.com",
                "role": "Specialist",
            },
        )

        self.assertRedirects(
            response, reverse("accounts:user-list"), fetch_redirect_response=False
        )
        messages = list(response.wsgi_request._messages)
        self.assertTrue(
            any(
                "No fue posible registrar al usuario en este momento" in str(m)
                for m in messages
            )
        )
        mock_create.assert_called_once()
        self.assertFalse(
            AuditLog.objects.filter(action="user_created").exists()
        )

    @patch(
        "accounts.views.ApiGatewayUsersClient.update_user_status",
        return_value=_remote_user("sub-specialist", "specialist_user", is_active=False),
    )
    def test_admin_can_deactivate_other_user(self, mock_status):
        self.specialist_user.cognito_sub = "sub-specialist"
        self.specialist_user.save(update_fields=["cognito_sub"])
        self.client.login(username="admin_user", password="test-pass-123")
        session = self.client.session
        session["cognito_id_token"] = "id-token"
        session.save()

        response = self.client.post(
            reverse("accounts:user-deactivate", args=[self.specialist_user.id])
        )

        self.assertRedirects(response, reverse("accounts:user-list"), fetch_redirect_response=False)
        mock_status.assert_called_once_with("id-token", "sub-specialist", False)
        self.specialist_user.refresh_from_db()
        self.assertFalse(self.specialist_user.is_active)
        self.assertTrue(
            AuditLog.objects.filter(
                actor=self.admin_user,
                action="user_deactivated",
                resource_type="user",
                resource_id="sub-specialist",
                result=AuditLog.Result.SUCCESS,
                metadata={"active": False},
            ).exists()
        )

    def test_admin_cannot_deactivate_self(self):
        self.client.login(username="admin_user", password="test-pass-123")
        session = self.client.session
        session["cognito_id_token"] = "id-token"
        session.save()

        response = self.client.post(
            reverse("accounts:user-deactivate", args=[self.admin_user.id])
        )

        self.assertEqual(response.status_code, 403)
        self.admin_user.refresh_from_db()
        self.assertTrue(self.admin_user.is_active)

    def test_delete_confirmation_page_renders_for_admin(self):
        self.client.login(username="admin_user", password="test-pass-123")

        response = self.client.get(
            reverse("accounts:user-delete", args=[self.specialist_user.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ELIMINAR")

    def test_delete_requires_exact_confirmation_word(self):
        self.client.login(username="admin_user", password="test-pass-123")

        response = self.client.post(
            reverse("accounts:user-delete", args=[self.specialist_user.id]),
            {"confirmation_word": "eliminar"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertTrue(User.objects.filter(pk=self.specialist_user.pk).exists())

    def test_admin_can_delete_specialist_with_correct_confirmation(self):
        self.client.login(username="admin_user", password="test-pass-123")
        specialist_id = self.specialist_user.pk
        specialist_username = self.specialist_user.username

        response = self.client.post(
            reverse("accounts:user-delete", args=[specialist_id]),
            {"confirmation_word": "ELIMINAR"},
        )

        self.assertRedirects(response, reverse("accounts:user-list"), fetch_redirect_response=False)
        self.assertFalse(User.objects.filter(pk=specialist_id).exists())
        self.assertTrue(
            AuditLog.objects.filter(
                actor=self.admin_user,
                action="user_deleted",
                resource_type="user",
                resource_id=str(specialist_id),
                metadata__username=specialist_username,
            ).exists()
        )

    def test_deleting_specialist_orphans_sessions_and_reports_instead_of_deleting_them(self):
        from clinical_sessions.models import SpecialistSession
        from reports.models import ReportRequest

        session = SpecialistSession.objects.create(
            specialist=self.specialist_user,
            session_id="SESSION-999",
            status="completed",
        )
        report = ReportRequest.objects.create(
            session_id="SESSION-999",
            requested_by=self.specialist_user,
            status=ReportRequest.Status.GENERATED,
        )
        self.client.login(username="admin_user", password="test-pass-123")

        self.client.post(
            reverse("accounts:user-delete", args=[self.specialist_user.id]),
            {"confirmation_word": "ELIMINAR"},
        )

        session.refresh_from_db()
        report.refresh_from_db()
        self.assertIsNone(session.specialist_id)
        self.assertIsNone(report.requested_by_id)

    def test_admin_cannot_delete_own_account(self):
        self.client.login(username="admin_user", password="test-pass-123")

        response = self.client.post(
            reverse("accounts:user-delete", args=[self.admin_user.id]),
            {"confirmation_word": "ELIMINAR"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(User.objects.filter(pk=self.admin_user.pk).exists())

    def test_specialist_cannot_delete_accounts(self):
        self.client.login(username="specialist_user", password="test-pass-123")

        response = self.client.post(
            reverse("accounts:user-delete", args=[self.admin_user.id]),
            {"confirmation_word": "ELIMINAR"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(User.objects.filter(pk=self.admin_user.pk).exists())

    @patch("accounts.views.CognitoSignUpClient.forgot_password")
    def test_admin_can_request_password_reset(self, mock_forgot_password):
        old_password_hash = self.specialist_user.password
        self.client.login(username="admin_user", password="test-pass-123")

        response = self.client.post(
            reverse("accounts:user-reset-password", args=[self.specialist_user.id])
        )

        self.assertRedirects(response, reverse("accounts:user-list"), fetch_redirect_response=False)
        # The fixture has no email set, so the stored username is used as the
        # Cognito identifier (email is preferred when present).
        mock_forgot_password.assert_called_once_with(self.specialist_user.username)
        messages = list(response.wsgi_request._messages)
        self.assertTrue(
            any("código de recuperación" in str(m) for m in messages)
        )
        self.assertTrue(
            any("página de confirmación" in str(m) for m in messages)
        )
        self.assertFalse(any("test-pass-123" in str(m) for m in messages))
        self.specialist_user.refresh_from_db()
        self.assertEqual(self.specialist_user.password, old_password_hash)
        self.assertTrue(
            AuditLog.objects.filter(
                actor=self.admin_user,
                action="password_reset_requested",
                resource_type="user",
                resource_id=str(self.specialist_user.pk),
                result=AuditLog.Result.SUCCESS,
            ).exists()
        )

    @patch("accounts.forms.ApiGatewayUsersClient.get_user")
    @patch(
        "accounts.forms.CognitoAuthClient.initiate_auth",
        side_effect=_mock_cognito_success_with_sub,
    )
    def test_successful_login_creates_audit_log_and_stores_id_token(
        self, mock_initiate_auth, mock_get_user
    ):
        mock_get_user.return_value = _remote_user("known-sub-123", "admin_user", "Administrator")
        expected_id_token = _build_fake_jwt({"sub": "known-sub-123"})
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "admin_user", "password": "test-pass-123"},
        )

        self.assertRedirects(response, reverse("dashboard:admin"))
        self.assertEqual(self.client.session["cognito_id_token"], expected_id_token)
        self.assertTrue(
            AuditLog.objects.filter(
                actor=self.admin_user,
                action="user_logged_in",
                resource_type="session",
                result=AuditLog.Result.SUCCESS,
            ).exists()
        )

    @patch("accounts.forms.ApiGatewayUsersClient.get_user")
    @patch(
        "accounts.forms.CognitoAuthClient.initiate_auth",
        side_effect=_mock_cognito_success_with_sub,
    )
    def test_successful_login_stores_cognito_sub_from_id_token(
        self, mock_initiate_auth, mock_get_user
    ):
        mock_get_user.return_value = _remote_user("known-sub-123", "admin_user", "Administrator")
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "admin_user", "password": "test-pass-123"},
        )

        self.assertRedirects(response, reverse("dashboard:admin"))
        self.assertEqual(self.client.session["cognito_sub"], "known-sub-123")

    @patch(
        "accounts.forms.CognitoAuthClient.initiate_auth",
        side_effect=CognitoInvalidCredentialsError("bad credentials"),
    )
    def test_login_is_blocked_when_cognito_rejects_credentials(self, mock_initiate_auth):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "admin_user", "password": "test-pass-123"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertFalse(
            AuditLog.objects.filter(action="user_logged_in").exists()
        )

    def test_successful_logout_creates_audit_log(self):
        self.client.login(username="admin_user", password="test-pass-123")

        response = self.client.post(reverse("accounts:logout"))

        self.assertRedirects(response, reverse("accounts:login"))
        self.assertTrue(
            AuditLog.objects.filter(
                actor=self.admin_user,
                action="user_logged_out",
                resource_type="session",
                result=AuditLog.Result.SUCCESS,
            ).exists()
        )

    def test_admin_can_grant_pdf_permission(self):
        self.client.login(username="admin_user", password="test-pass-123")

        response = self.client.post(
            reverse("accounts:user-grant-pdf-permission", args=[self.specialist_user.pk])
        )

        self.assertRedirects(response, reverse("accounts:user-list"), fetch_redirect_response=False)
        self.specialist_user.refresh_from_db()
        self.assertTrue(self.specialist_user.can_generate_pdf_without_approval)
        self.assertTrue(
            AuditLog.objects.filter(
                actor=self.admin_user,
                action="pdf_permission_granted",
                resource_type="user",
                resource_id=str(self.specialist_user.pk),
            ).exists()
        )

    def test_specialist_cannot_grant_pdf_permission(self):
        self.client.login(username="specialist_user", password="test-pass-123")

        response = self.client.post(
            reverse("accounts:user-grant-pdf-permission", args=[self.specialist_user.pk])
        )

        self.assertEqual(response.status_code, 403)

    def test_admin_can_revoke_pdf_permission(self):
        self.specialist_user.can_generate_pdf_without_approval = True
        self.specialist_user.save(update_fields=["can_generate_pdf_without_approval"])
        self.client.login(username="admin_user", password="test-pass-123")

        response = self.client.post(
            reverse("accounts:user-revoke-pdf-permission", args=[self.specialist_user.pk])
        )

        self.assertRedirects(response, reverse("accounts:user-list"), fetch_redirect_response=False)
        self.specialist_user.refresh_from_db()
        self.assertFalse(self.specialist_user.can_generate_pdf_without_approval)
        self.assertTrue(
            AuditLog.objects.filter(
                actor=self.admin_user,
                action="pdf_permission_revoked",
                resource_type="user",
                resource_id=str(self.specialist_user.pk),
            ).exists()
        )

    def test_admin_can_view_edit_name_form_prefilled(self):
        self.specialist_user.first_name = "Pedro"
        self.specialist_user.last_name = "Gonzalez"
        self.specialist_user.save(update_fields=["first_name", "last_name"])
        self.client.login(username="admin_user", password="test-pass-123")

        response = self.client.get(
            reverse("accounts:user-edit-name", args=[self.specialist_user.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pedro")
        self.assertContains(response, "Gonzalez")

    def test_admin_can_update_name(self):
        self.client.login(username="admin_user", password="test-pass-123")

        response = self.client.post(
            reverse("accounts:user-edit-name", args=[self.specialist_user.pk]),
            {"first_name": "Ana", "last_name": "Torres"},
        )

        self.assertRedirects(response, reverse("accounts:user-list"), fetch_redirect_response=False)
        self.specialist_user.refresh_from_db()
        self.assertEqual(self.specialist_user.first_name, "Ana")
        self.assertEqual(self.specialist_user.last_name, "Torres")
        self.assertTrue(
            AuditLog.objects.filter(
                actor=self.admin_user,
                action="user_name_updated",
                resource_type="user",
                resource_id=str(self.specialist_user.pk),
                metadata__first_name="Ana",
                metadata__last_name="Torres",
            ).exists()
        )

    def test_specialist_cannot_update_name(self):
        self.client.login(username="specialist_user", password="test-pass-123")

        response = self.client.post(
            reverse("accounts:user-edit-name", args=[self.specialist_user.pk]),
            {"first_name": "Ana", "last_name": "Torres"},
        )

        self.assertEqual(response.status_code, 403)


class SpecialistProfileViewTests(TestCase):
    def setUp(self):
        runtime = Mock()
        runtime.get_neuroflex_api_base_url.return_value = "https://api.example.test/dev"
        self.runtime_patcher = patch(
            "integrations.services.neuroflex_api_client.RuntimeConfig",
            return_value=runtime,
        )
        self.runtime_patcher.start()
        self.addCleanup(self.runtime_patcher.stop)

    @classmethod
    def setUpTestData(cls):
        cls.admin_user = User.objects.create_user(
            username="admin_user",
            password="test-pass-123",
            role=User.Role.ADMIN,
        )
        cls.specialist_user = User.objects.create_user(
            username="specialist@example.com",
            email="specialist@example.com",
            password="test-pass-123",
            role=User.Role.SPECIALIST,
            cognito_sub="specialist-sub-123",
        )

    @patch(
        "accounts.views.ApiGatewayUsersClient.get_user",
        return_value=_remote_user("specialist-sub-123", "specialist@example.com"),
    )
    def test_specialist_can_view_own_profile(self, mock_get_user):
        self.client.login(username="specialist@example.com", password="test-pass-123")
        session = self.client.session
        session["cognito_id_token"] = "id-token"
        session.save()

        response = self.client.get(reverse("accounts:specialist-profile"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "specialist@example.com")
        mock_get_user.assert_called_once_with("id-token", "specialist-sub-123")

    def test_admin_cannot_view_specialist_profile(self):
        self.client.login(username="admin_user", password="test-pass-123")

        response = self.client.get(reverse("accounts:specialist-profile"))

        self.assertEqual(response.status_code, 403)

    def test_unauthenticated_user_redirected(self):
        response = self.client.get(reverse("accounts:specialist-profile"))

        self.assertRedirects(
            response,
            f"{reverse('accounts:login')}?next={reverse('accounts:specialist-profile')}",
        )

    @patch(
        "accounts.views.ApiGatewayUsersClient.get_user",
        side_effect=ApiGatewayUsersServiceError("unavailable"),
    )
    def test_profile_view_handles_api_error(self, mock_get_user):
        self.client.login(username="specialist@example.com", password="test-pass-123")
        session = self.client.session
        session["cognito_id_token"] = "id-token"
        session.save()

        response = self.client.get(reverse("accounts:specialist-profile"))

        self.assertRedirects(
            response, reverse("dashboard:specialist"), fetch_redirect_response=False
        )
        messages = list(response.wsgi_request._messages)
        self.assertTrue(
            any("No fue posible obtener tu perfil" in str(m) for m in messages)
        )


class AdminPasswordResetViewTests(TestCase):
    """Admin-triggered Cognito ForgotPassword flow (PasswordResetView)."""

    @classmethod
    def setUpTestData(cls):
        cls.admin_user = User.objects.create_user(
            username="admin_user",
            password="test-pass-123",
            role=User.Role.ADMIN,
        )
        cls.specialist_user = User.objects.create_user(
            username="specialist@example.com",
            password="test-pass-123",
            role=User.Role.SPECIALIST,
            email="specialist@example.com",
        )

    def setUp(self):
        runtime = Mock()
        runtime.get_cognito_client_id.return_value = "test-client-id"
        self.runtime_patcher = patch(
            "integrations.services.cognito_signup_client.RuntimeConfig",
            return_value=runtime,
        )
        self.runtime_patcher.start()
        self.addCleanup(self.runtime_patcher.stop)
        self.client.login(username="admin_user", password="test-pass-123")

    def _post_reset(self, user=None):
        return self.client.post(
            reverse("accounts:user-reset-password", args=[(user or self.specialist_user).id])
        )

    def _messages(self, response):
        return [str(m) for m in response.wsgi_request._messages]

    @patch("accounts.views.CognitoSignUpClient.forgot_password")
    def test_uses_username_as_cognito_identifier(self, mock_forgot_password):
        self._post_reset()

        mock_forgot_password.assert_called_once_with(self.specialist_user.get_username())

    @patch("accounts.views.CognitoSignUpClient.forgot_password")
    def test_falls_back_to_email_when_username_is_empty(self, mock_forgot_password):
        self.specialist_user.username = ""
        self.specialist_user.save(update_fields=["username"])

        response = self._post_reset()

        self.assertRedirects(
            response, reverse("accounts:user-list"), fetch_redirect_response=False
        )
        mock_forgot_password.assert_called_once_with("specialist@example.com")

    @patch("accounts.views.CognitoSignUpClient.forgot_password")
    def test_success_shows_clear_message_with_confirmation_hint(self, mock_forgot_password):
        response = self._post_reset()

        self.assertRedirects(response, reverse("accounts:user-list"), fetch_redirect_response=False)
        messages = self._messages(response)
        self.assertTrue(
            any("código de recuperación" in m for m in messages),
            f"Expected a recovery-code success message, got {messages!r}",
        )
        self.assertTrue(
            any("página de confirmación" in m for m in messages),
            f"Expected the confirmation-page hint, got {messages!r}",
        )
        self.assertTrue(
            any("specialist@example.com" in m for m in messages),
            f"Expected the target identifier in the message, got {messages!r}",
        )

    @patch("accounts.views.CognitoSignUpClient.forgot_password")
    def test_success_audits_reset_request_without_password(self, mock_forgot_password):
        response = self._post_reset()

        self.assertEqual(response.status_code, 302)
        entry = AuditLog.objects.get(action="password_reset_requested")
        self.assertEqual(entry.actor, self.admin_user)
        self.assertEqual(entry.resource_id, str(self.specialist_user.pk))
        self.assertEqual(entry.metadata, {"username": "specialist@example.com"})
        self.assertNotIn("password", str(entry.metadata).lower())

    @patch(
        "accounts.views.CognitoSignUpClient.forgot_password",
        side_effect=CognitoUserNotFoundError("no such user"),
    )
    def test_user_not_found_shows_specific_message(self, mock_forgot_password):
        response = self._post_reset()

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            any("no existe o no está confirmado" in m for m in self._messages(response))
        )
        self.assertFalse(
            AuditLog.objects.filter(action="password_reset_requested").exists()
        )

    @patch(
        "accounts.views.CognitoSignUpClient.forgot_password",
        side_effect=CognitoUserNotConfirmedError("not confirmed"),
    )
    def test_user_not_confirmed_shows_specific_message(self, mock_forgot_password):
        response = self._post_reset()

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            any("no existe o no está confirmado" in m for m in self._messages(response))
        )

    @patch(
        "accounts.views.CognitoSignUpClient.forgot_password",
        side_effect=CognitoInvalidParameterError("bad param"),
    )
    def test_invalid_parameter_shows_specific_message(self, mock_forgot_password):
        response = self._post_reset()

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            any("identificador de usuario no es válido" in m for m in self._messages(response))
        )

    @patch(
        "accounts.views.CognitoSignUpClient.forgot_password",
        side_effect=CognitoLimitExceededError("too many"),
    )
    def test_limit_exceeded_shows_specific_message(self, mock_forgot_password):
        response = self._post_reset()

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            any("excedió el límite de intentos" in m for m in self._messages(response))
        )

    @patch(
        "accounts.views.CognitoSignUpClient.forgot_password",
        side_effect=CognitoNetworkError("offline"),
    )
    def test_network_error_shows_specific_message(self, mock_forgot_password):
        response = self._post_reset()

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            any("No se pudo conectar con Cognito" in m for m in self._messages(response))
        )

    @patch(
        "accounts.views.CognitoSignUpClient.forgot_password",
        side_effect=CognitoConfigurationError("misconfigured"),
    )
    def test_configuration_error_shows_specific_message(self, mock_forgot_password):
        response = self._post_reset()

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            any("configuración de Cognito no es válida" in m for m in self._messages(response))
        )

    @patch(
        "accounts.views.CognitoSignUpClient.forgot_password",
        side_effect=CognitoNotAuthorizedError("not authorized"),
    )
    def test_not_authorized_shows_specific_message(self, mock_forgot_password):
        response = self._post_reset()

        self.assertEqual(response.status_code, 302)
        messages = self._messages(response)
        self.assertTrue(
            any("autorización para restablecer" in m for m in messages),
            f"Expected the not-authorized message, got {messages!r}",
        )
        # Must NOT fall through to the generic fallback.
        self.assertFalse(
            any("No fue posible iniciar el restablecimiento" in m for m in messages)
        )
        self.assertFalse(
            AuditLog.objects.filter(action="password_reset_requested").exists()
        )

    @patch(
        "accounts.views.CognitoSignUpClient.forgot_password",
        side_effect=CognitoServiceError("unexpected cognito error"),
    )
    def test_unexpected_cognito_error_shows_fallback_message(self, mock_forgot_password):
        response = self._post_reset()

        self.assertEqual(response.status_code, 302)
        messages = self._messages(response)
        self.assertTrue(
            any("No fue posible iniciar el restablecimiento" in m for m in messages),
            f"Expected the generic fallback message, got {messages!r}",
        )
        # Specific messages must NOT leak for unmapped Cognito errors.
        self.assertFalse(
            any("no existe o no está confirmado" in m for m in messages)
        )
        self.assertFalse(
            AuditLog.objects.filter(action="password_reset_requested").exists()
        )

    def test_specialist_cannot_trigger_admin_password_reset(self):
        self.client.login(username="specialist@example.com", password="test-pass-123")

        response = self.client.post(
            reverse("accounts:user-reset-password", args=[self.admin_user.id])
        )

        self.assertEqual(response.status_code, 403)
        denial = AuditLog.objects.get(action="authorization_denied")
        self.assertEqual(denial.result, AuditLog.Result.FAILURE)
        self.assertEqual(denial.actor, self.specialist_user)


class RequestPasswordResetViewTests(TestCase):
    def setUp(self):
        runtime = Mock()
        runtime.get_cognito_client_id.return_value = "test-client-id"
        self.runtime_patcher = patch(
            "integrations.services.cognito_signup_client.RuntimeConfig",
            return_value=runtime,
        )
        self.runtime_patcher.start()
        self.addCleanup(self.runtime_patcher.stop)

    @patch("accounts.views.CognitoSignUpClient.forgot_password")
    def test_request_password_reset_sends_recovery_code(self, mock_forgot_password):
        response = self.client.post(
            reverse("accounts:reset-password-request"),
            {"email": "specialist@example.com"},
        )

        self.assertRedirects(
            response, reverse("accounts:reset-password-confirm"), fetch_redirect_response=False
        )
        mock_forgot_password.assert_called_once_with("specialist@example.com")
        messages = list(response.wsgi_request._messages)
        self.assertTrue(
            any("Revisa tu correo para continuar con la recuperacion" in str(m) for m in messages)
        )


class ResetPasswordConfirmViewTests(TestCase):
    def setUp(self):
        runtime = Mock()
        runtime.get_cognito_client_id.return_value = "test-client-id"
        self.runtime_patcher = patch(
            "integrations.services.cognito_signup_client.RuntimeConfig",
            return_value=runtime,
        )
        self.runtime_patcher.start()
        self.addCleanup(self.runtime_patcher.stop)

    @classmethod
    def setUpTestData(cls):
        cls.specialist_user = User.objects.create_user(
            username="specialist@example.com",
            password="Old-pass-123!",
            role=User.Role.SPECIALIST,
        )

    def _post_reset(self, **overrides):
        data = {
            "email": "specialist@example.com",
            "confirmation_code": "123456",
            "new_password1": "New-pass-456!",
            "new_password2": "New-pass-456!",
        }
        data.update(overrides)
        return self.client.post(reverse("accounts:reset-password-confirm"), data)

    def test_get_renders_form_without_login(self):
        response = self.client.get(reverse("accounts:reset-password-confirm"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Restablecer contrasena")

    @patch("accounts.views.CognitoSignUpClient.confirm_forgot_password")
    def test_happy_path_syncs_new_password_without_temporary_password(
        self, mock_confirm_forgot_password
    ):
        response = self._post_reset()

        self.assertRedirects(response, reverse("accounts:login"))
        mock_confirm_forgot_password.assert_called_once_with(
            "specialist@example.com", "123456", "New-pass-456!"
        )
        self.specialist_user.refresh_from_db()
        self.assertTrue(self.specialist_user.check_password("New-pass-456!"))
        self.assertTrue(
            AuditLog.objects.filter(
                action="password_reset_confirmed",
                metadata__username="specialist@example.com",
            ).exists()
        )

    def test_password_mismatch_is_rejected_before_calling_cognito(self):
        response = self._post_reset(new_password2="Different-pass-789!")

        self.assertEqual(response.status_code, 400)
        self.specialist_user.refresh_from_db()
        self.assertTrue(self.specialist_user.check_password("Old-pass-123!"))

    @patch(
        "accounts.views.CognitoSignUpClient.confirm_forgot_password",
        side_effect=CognitoCodeMismatchError("invalid code"),
    )
    def test_invalid_code_shows_form_error_without_changing_django(
        self, mock_confirm_forgot_password
    ):
        response = self._post_reset()

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "El codigo ingresado no es valido", status_code=400)
        self.specialist_user.refresh_from_db()
        self.assertTrue(self.specialist_user.check_password("Old-pass-123!"))


class CanonicalRemoteLoginTests(TestCase):
    def setUp(self):
        runtime = Mock()
        runtime.get_cognito_client_id.return_value = "test-client-id"
        runtime.get_neuroflex_api_base_url.return_value = "https://api.example.test/dev"
        self.forms_patcher = patch("accounts.forms.RuntimeConfig", return_value=runtime)
        self.neuroflex_patcher = patch(
            "integrations.services.neuroflex_api_client.RuntimeConfig",
            return_value=runtime,
        )
        self.online_patcher = patch("accounts.views.is_online", return_value=True)
        # El login online exitoso ahora sincroniza TyC; se aísla para que los
        # tests no realicen llamadas de red reales.
        self.terms_sync_patcher = patch("accounts.views.sync_terms_versions")
        self.forms_patcher.start()
        self.neuroflex_patcher.start()
        self.online_patcher.start()
        self.terms_sync_patcher.start()
        self.addCleanup(self.forms_patcher.stop)
        self.addCleanup(self.neuroflex_patcher.stop)
        self.addCleanup(self.online_patcher.stop)
        self.addCleanup(self.terms_sync_patcher.stop)
    @patch("accounts.forms.ApiGatewayUsersClient.get_user")
    @patch(
        "accounts.forms.CognitoAuthClient.initiate_auth",
        side_effect=_mock_cognito_success_with_sub,
    )
    def test_login_syncs_account_from_remote_user(self, mock_auth, mock_get_user):
        id_token = _build_fake_jwt({"sub": "known-sub-123"})
        mock_get_user.return_value = _remote_user(
            "known-sub-123", "remote@example.com", "Administrator"
        )

        response = self.client.post(
            reverse("accounts:login"),
            {"username": "remote@example.com", "password": "password"},
        )

        self.assertRedirects(response, reverse("dashboard:admin"))
        mock_get_user.assert_called_once_with(id_token, "known-sub-123")
        user = User.objects.get(cognito_sub="known-sub-123")
        self.assertEqual(user.username, "remote@example.com")
        self.assertEqual(user.role, User.Role.ADMIN)
        self.assertFalse(
            AuditLog.objects.filter(action="user_created", metadata__auto_created=True).exists()
        )

    @patch("accounts.forms.ApiGatewayUsersClient.get_user")
    @patch(
        "accounts.forms.CognitoAuthClient.initiate_auth",
        return_value=_mock_cognito_success_with_claims({}),
    )
    def test_login_fails_when_sub_is_missing(self, mock_auth, mock_get_user):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "missing-sub@example.com", "password": "password"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        mock_get_user.assert_not_called()

    @patch("accounts.forms.ApiGatewayUsersClient.get_user")
    @patch(
        "accounts.forms.CognitoAuthClient.initiate_auth",
        side_effect=_mock_cognito_success_with_sub,
    )
    def test_login_fails_when_remote_user_is_inactive(self, mock_auth, mock_get_user):
        mock_get_user.return_value = _remote_user(
            "known-sub-123", "inactive@example.com", is_active=False
        )

        response = self.client.post(
            reverse("accounts:login"),
            {"username": "inactive@example.com", "password": "password"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    @patch("accounts.forms.ApiGatewayUsersClient.get_user")
    @patch(
        "accounts.forms.CognitoAuthClient.initiate_auth",
        side_effect=_mock_cognito_success_with_sub,
    )
    def test_login_succeeds_when_remote_user_collides_with_linked_local_user(
        self, mock_auth, mock_get_user
    ):
        user = User.objects.create_user(
            username="collision@example.com",
            email="collision@example.com",
            role=User.Role.SPECIALIST,
            cognito_sub="other-sub",
        )
        mock_get_user.return_value = _remote_user(
            "known-sub-123", "collision@example.com"
        )

        response = self.client.post(
            reverse("accounts:login"),
            {"username": "collision@example.com", "password": "password"},
        )

        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertEqual(user.cognito_sub, "known-sub-123")


class RemoteUserStatusSyncTests(TestCase):
    def test_sync_local_user_stores_onboarding_status(self):
        user = sync_local_user_from_remote_user(
            {
                **_remote_user("sub-ana", "ana@example.com"),
                "onboarding_status": "COMPLETED",
            }
        )

        self.assertEqual(user.onboarding_status, "COMPLETED")

    def test_sync_local_user_stores_cognito_status(self):
        user = sync_local_user_from_remote_user(
            {
                **_remote_user("sub-ana", "ana@example.com"),
                "cognito_status": "CONFIRMED",
            }
        )

        self.assertEqual(user.cognito_status, "CONFIRMED")

    def test_sync_local_user_preserves_existing_status_when_missing(self):
        user = User.objects.create_user(
            username="ana@example.com",
            email="ana@example.com",
            cognito_sub="sub-ana",
            onboarding_status="COMPLETED",
            cognito_status="CONFIRMED",
        )

        sync_local_user_from_remote_user(_remote_user("sub-ana", "ana@example.com"))

        user.refresh_from_db()
        self.assertEqual(user.onboarding_status, "COMPLETED")
        self.assertEqual(user.cognito_status, "CONFIRMED")


class SyncLocalUserConflictTests(TestCase):
    def test_sync_updates_user_with_same_email_but_different_sub(self):
        user = User.objects.create_user(
            username="test@example.com",
            email="test@example.com",
            cognito_sub="old-sub",
            role=User.Role.ADMIN,
        )

        with self.assertLogs("accounts.services", level="WARNING"):
            synced_user = sync_local_user_from_remote_user(
                _remote_user("new-sub", "test@example.com", "Administrator")
            )

        user.refresh_from_db()
        self.assertEqual(synced_user.pk, user.pk)
        self.assertEqual(user.cognito_sub, "new-sub")
        self.assertEqual(user.role, User.Role.ADMIN)

    def test_sync_creates_user_when_no_match(self):
        user = sync_local_user_from_remote_user(
            _remote_user("new-sub", "test@example.com", "Administrator")
        )

        self.assertEqual(user.username, "test@example.com")
        self.assertEqual(user.cognito_sub, "new-sub")
        self.assertEqual(user.role, User.Role.ADMIN)

    def test_sync_updates_user_by_matching_sub(self):
        user = User.objects.create_user(
            username="old@example.com",
            email="old@example.com",
            cognito_sub="matching-sub",
            role=User.Role.SPECIALIST,
        )

        synced_user = sync_local_user_from_remote_user(
            _remote_user("matching-sub", "new@example.com", "Administrator")
        )

        user.refresh_from_db()
        self.assertEqual(synced_user.pk, user.pk)
        self.assertEqual(user.email, "new@example.com")
        self.assertEqual(user.role, User.Role.ADMIN)

    def test_sync_ignores_invalid_remote_payload(self):
        remote_user = _remote_user("new-sub", "test@example.com")
        for field in ("user_id", "email"):
            with self.subTest(field=field):
                invalid_remote_user = remote_user.copy()
                del invalid_remote_user[field]

                with self.assertRaises(ValueError):
                    sync_local_user_from_remote_user(invalid_remote_user)

    def test_sync_handles_duplicate_username_gracefully(self):
        user = User.objects.create_user(
            username="test@example.com",
            cognito_sub="old-sub",
            role=User.Role.SPECIALIST,
        )

        synced_user = sync_local_user_from_remote_user(
            _remote_user("new-sub", "test@example.com", "Administrator")
        )

        user.refresh_from_db()
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(synced_user.pk, user.pk)
        self.assertEqual(user.cognito_sub, "new-sub")
