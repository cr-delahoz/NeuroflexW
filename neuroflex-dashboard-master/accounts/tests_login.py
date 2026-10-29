import base64
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model

from accounts.forms import (
    CognitoAuthenticationForm,
    NewPasswordRequiredForm,
    RemoteUserCreationForm,
)
from audit.models import AuditLog
from integrations.services.api_gateway_users_client import ApiGatewayUsersNotFoundError
from offline_mode.models import OfflineAccessGrant
from terms.services import TermsSyncError


User = get_user_model()


def _build_fake_jwt(payload):
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=")
    return f"header.{encoded.decode()}.signature"


class CognitoRemoteLoginTests(TestCase):
    def setUp(self):
        runtime = Mock()
        runtime.get_cognito_client_id.return_value = "test-client-id"
        self.runtime_patcher = patch("accounts.forms.RuntimeConfig", return_value=runtime)
        self.runtime_patcher.start()
        self.addCleanup(self.runtime_patcher.stop)

    @patch(
        "accounts.forms.sync_local_user_from_remote_user",
        return_value=SimpleNamespace(is_active=True),
    )
    @patch(
        "accounts.forms.ApiGatewayUsersClient.get_user",
        return_value={
            "user_id": "sub-1",
            "email": "ana@example.com",
            "role": "Administrator",
            "is_active": True,
        },
    )
    @patch(
        "accounts.forms.CognitoAuthClient.initiate_auth",
        return_value={
            "status": "authenticated",
            "id_token": _build_fake_jwt({"sub": "sub-1"}),
            "access_token": "access",
            "refresh_token": "refresh",
            "expires_in": 3600,
        },
    )
    def test_login_fetches_remote_user_before_sync(self, mock_auth, mock_get, mock_sync):
        form = CognitoAuthenticationForm(
            data={"username": "ana@example.com", "password": "pass"}
        )

        self.assertTrue(form.is_valid())
        mock_get.assert_called_once_with(mock_auth.return_value["id_token"], "sub-1")
        mock_sync.assert_called_once_with(mock_get.return_value)

    @patch("accounts.forms.sync_local_user_from_remote_user")
    @patch(
        "accounts.forms.ApiGatewayUsersClient.get_user",
        side_effect=ApiGatewayUsersNotFoundError("missing"),
    )
    @patch(
        "accounts.forms.CognitoAuthClient.initiate_auth",
        return_value={"status": "authenticated", "id_token": _build_fake_jwt({"sub": "sub-1"})},
    )
    def test_login_404_rejects_without_sync(self, mock_auth, mock_get, mock_sync):
        form = CognitoAuthenticationForm(
            data={"username": "ana@example.com", "password": "pass"}
        )

        self.assertFalse(form.is_valid())
        mock_sync.assert_not_called()

    @patch("accounts.forms.decode_jwt_claims")
    @patch(
        "accounts.forms.CognitoAuthClient.initiate_auth",
        return_value={
            "status": "new_password_required",
            "session": "secret",
            "required_attributes": ["email"],
        },
    )
    def test_challenge_exposes_session_for_storage_without_decoding_tokens(self, mock_auth, mock_decode):
        form = CognitoAuthenticationForm(
            data={"username": "ana@example.com", "password": "pass"}
        )

        self.assertTrue(form.is_valid())
        self.assertEqual(
            form.auth_result,
            {"status": "new_password_required", "session": "secret"},
        )
        self.assertTrue(form.new_password_required)
        self.assertEqual(form.required_attributes, ["email"])
        self.assertEqual(form.challenge_username, "ana@example.com")
        mock_decode.assert_not_called()

    @patch("accounts.forms.CognitoAuthClient.respond_to_new_password_challenge")
    @patch("accounts.forms.CognitoAuthClient.initiate_auth")
    def test_new_password_post_without_challenge_data_raises_expired_error(
        self, mock_auth, mock_respond
    ):
        # Second POST carrying new passwords but no stored challenge session
        # (expired or user navigated back). The legacy fallback that re-ran
        # initiate_auth with the temporary password is gone, so the form must
        # surface a clear non-field error instead.
        form = CognitoAuthenticationForm(
            data={
                "username": "ana@example.com",
                "temporary_password": "temporary",
                "new_password1": "new-password",
                "new_password2": "new-password",
            }
        )

        self.assertFalse(form.is_valid())
        non_field_errors = form.non_field_errors()
        self.assertEqual(len(non_field_errors), 1)
        self.assertEqual(non_field_errors.as_data()[0].code, "challenge_expired")
        self.assertIn(
            "La sesión de cambio de contraseña expiró",
            str(non_field_errors),
        )
        # temporary_password is never required when new passwords are present.
        self.assertNotIn("temporary_password", form.errors)
        # Neither Cognito call is made: no silent re-authentication.
        mock_auth.assert_not_called()
        mock_respond.assert_not_called()

    @patch(
        "accounts.forms.sync_local_user_from_remote_user",
        return_value=SimpleNamespace(is_active=True),
    )
    @patch(
        "accounts.forms.ApiGatewayUsersClient.get_user",
        return_value={
            "user_id": "sub-1",
            "email": "ana@example.com",
            "role": "Administrator",
            "is_active": True,
        },
    )
    @patch(
        "accounts.forms.CognitoAuthClient.respond_to_new_password_challenge",
        return_value={
            "status": "authenticated",
            "id_token": _build_fake_jwt({"sub": "sub-1"}),
        },
    )
    @patch("accounts.forms.CognitoAuthClient.initiate_auth")
    def test_new_password_challenge_uses_stored_session_without_initiate_auth(
        self, mock_auth, mock_respond, mock_get, mock_sync
    ):
        form = CognitoAuthenticationForm(
            data={
                "username": "ana@example.com",
                "new_password1": "new-password",
                "new_password2": "new-password",
            },
            challenge_data={
                "username": "ana@example.com",
                "session": "stored-session",
                "required_attributes": ["email"],
            },
        )

        self.assertTrue(form.is_valid())
        mock_auth.assert_not_called()
        mock_respond.assert_called_once_with(
            "ana@example.com", "new-password", "stored-session", ["email"]
        )
        mock_get.assert_called_once_with(mock_respond.return_value["id_token"], "sub-1")
        mock_sync.assert_called_once_with(mock_get.return_value)

    @patch(
        "accounts.forms.ApiGatewayUsersClient.get_user",
        return_value={
            "user_id": "sub-1",
            "email": "ana@example.com",
            "role": "Specialist",
            "is_active": True,
        },
    )
    @patch("accounts.forms.CognitoAuthClient.respond_to_new_password_challenge")
    def test_successful_new_password_challenge_captures_new_password(
        self, mock_respond, mock_get
    ):
        user = User.objects.create_user(
            username="ana@example.com", role="SPECIALIST", cognito_sub="sub-1"
        )
        mock_respond.return_value = {
            "status": "authenticated",
            "id_token": _build_fake_jwt({"sub": "sub-1"}),
        }

        form = CognitoAuthenticationForm(
            data={
                "username": "ana@example.com",
                "new_password1": "new-password",
                "new_password2": "new-password",
            },
            challenge_data={
                "username": "ana@example.com",
                "session": "stored-session",
                "required_attributes": ["email"],
            },
        )

        self.assertTrue(form.is_valid())
        grant = OfflineAccessGrant.objects.get(user=user)
        user.refresh_from_db()
        self.assertTrue(user.check_password("new-password"))
        self.assertEqual(grant.failed_attempts, 0)
        self.assertIsNone(grant.locked_until)

    def test_new_password_challenge_requires_new_passwords_without_temporary_password(self):
        form = CognitoAuthenticationForm(
            data={"username": "ana@example.com"},
            challenge_data={
                "username": "ana@example.com",
                "session": "stored-session",
                "required_attributes": ["email"],
            },
        )

        self.assertFalse(form.is_valid())
        self.assertIn("new_password1", form.errors)
        self.assertIn("new_password2", form.errors)
        # temporary_password is NOT required in challenge mode.
        self.assertNotIn("temporary_password", form.errors)

    @patch(
        "accounts.forms.CognitoAuthClient.respond_to_new_password_challenge"
    )
    def test_new_password_challenge_rejects_tampered_required_attributes(
        self, mock_respond
    ):
        form = CognitoAuthenticationForm(
            data={
                "username": "ana@example.com",
                "new_password1": "new-password",
                "new_password2": "new-password",
            },
            challenge_data={
                "username": "ana@example.com",
                "session": "stored-session",
                "required_attributes": ["phone_number"],
            },
        )

        self.assertFalse(form.is_valid())
        self.assertIn("No fue posible completar el cambio de contrasena.", form.errors["__all__"])
        mock_respond.assert_not_called()

    def test_new_password_challenge_rejects_mismatched_passwords(self):
        form = CognitoAuthenticationForm(
            data={
                "username": "ana@example.com",
                "new_password1": "new-password",
                "new_password2": "other-password",
            },
            challenge_data={
                "username": "ana@example.com",
                "session": "stored-session",
                "required_attributes": ["email"],
            },
        )

        self.assertFalse(form.is_valid())
        self.assertIn("new_password2", form.errors)
        # Mismatch is a field error, not a non-field error.
        self.assertEqual(form.non_field_errors(), [])

    def test_remote_creation_form_allows_only_remote_roles(self):
        self.assertTrue(
            RemoteUserCreationForm(
                {
                    "email": "ana@example.com",
                    "first_name": "Ana",
                    "last_name": "Paz",
                    "role": "Administrator",
                }
            ).is_valid()
        )
        self.assertFalse(
            RemoteUserCreationForm(
                {
                    "email": "ana@example.com",
                    "first_name": "Ana",
                    "last_name": "Paz",
                    "role": "ADMIN",
                }
            ).is_valid()
        )

    def test_new_password_form_accepts_optional_new_passwords(self):
        self.assertTrue(
            NewPasswordRequiredForm(
                {"username": "ana@example.com", "temporary_password": "temporary"}
            ).is_valid()
        )

    def test_login_rejects_missing_cognito_client_id_with_validation_error(self):
        runtime = Mock()
        runtime.get_cognito_client_id.return_value = ""
        with patch("accounts.forms.RuntimeConfig", return_value=runtime):
            form = CognitoAuthenticationForm(
                data={"username": "ana@example.com", "password": "pass"}
            )

        self.assertFalse(form.is_valid())
        self.assertIn(
            "No fue posible validar tus credenciales con NeuroFlex.",
            form.errors["__all__"][0],
        )


class RoleBasedLoginViewTests(TestCase):
    def setUp(self):
        runtime = Mock()
        runtime.get_cognito_client_id.return_value = "test-client-id"
        self.runtime_patcher = patch("accounts.forms.RuntimeConfig", return_value=runtime)
        self.online_patcher = patch("accounts.views.is_online", return_value=True)
        # El login online exitoso ahora sincroniza TyC; se aísla para que los
        # tests no realicen llamadas reales a la API de NeuroFlex.
        self.terms_sync_patcher = patch("accounts.views.sync_terms_versions")
        self.runtime_patcher.start()
        self.online_patcher.start()
        self.terms_sync = self.terms_sync_patcher.start()
        self.addCleanup(self.runtime_patcher.stop)
        self.addCleanup(self.online_patcher.stop)
        self.addCleanup(self.terms_sync_patcher.stop)

    @patch(
        "accounts.forms.CognitoAuthClient.initiate_auth",
        return_value={
            "status": "new_password_required",
            "session": "cognito-challenge-session",
            "required_attributes": ["email"],
        },
    )
    def test_first_post_renders_challenge_and_stores_session_without_cognito_tokens(
        self, mock_auth
    ):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "ana@example.com", "password": "temporary"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].new_password_required)
        self.assertEqual(response.context["form"].challenge_username, "ana@example.com")
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertFalse(
            {"cognito_id_token", "cognito_access_token", "cognito_sub"}
            & set(self.client.session.keys())
        )
        # The challenge session IS stored server-side so the second step does
        # not require re-entering the temporary password.
        self.assertEqual(
            self.client.session.get("cognito_new_password_challenge"),
            {
                "username": "ana@example.com",
                "session": "cognito-challenge-session",
                "required_attributes": ["email"],
            },
        )
        # The raw Cognito session string must not leak into the rendered page
        # or the template context.
        self.assertNotIn("cognito-challenge-session", response.content.decode())
        self.assertNotIn("cognito-challenge-session", str(response.context))
        self.assertEqual(AuditLog.objects.count(), 0)
        mock_auth.assert_called_once_with("ana@example.com", "temporary")

    @patch(
        "accounts.forms.CognitoAuthClient.initiate_auth",
        return_value={
            "status": "new_password_required",
            "session": "cognito-challenge-session",
            "required_attributes": ["email"],
        },
    )
    def test_challenge_mode_template_hides_temporary_password_field(self, mock_auth):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "ana@example.com", "password": "temporary"},
        )

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        # Challenge mode must NOT render the temporary password field (neither
        # its name nor its input id) nor the old instructional copy that asked
        # the user to re-enter the temporary password.
        self.assertNotIn('name="temporary_password"', html)
        self.assertNotIn("id_temporary_password", html)
        self.assertNotIn("Reingresa tu contraseña temporal", html)
        # It MUST render the new-password instructional copy instead.
        self.assertIn("Define una nueva contraseña para continuar", html)

    @patch("accounts.views.log_event")
    @patch("accounts.forms.sync_local_user_from_remote_user")
    @patch("accounts.forms.ApiGatewayUsersClient.get_user")
    @patch("accounts.forms.CognitoAuthClient.respond_to_new_password_challenge")
    @patch("accounts.forms.CognitoAuthClient.initiate_auth")
    def test_second_post_logs_in_with_final_cognito_tokens_only(
        self, mock_auth, mock_respond, mock_get, mock_sync, mock_log
    ):
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.create_user(
            username="ana@example.com",
            password="local-password",
            role=get_user_model().Role.ADMIN,
        )
        mock_auth.return_value = {
            "status": "new_password_required",
            "session": "fresh-cognito-challenge",
            "required_attributes": ["email"],
        }
        mock_respond.return_value = {
            "status": "authenticated",
            "id_token": _build_fake_jwt({"sub": "sub-1"}),
            "access_token": "final-access-token",
        }
        mock_get.return_value = {
            "user_id": "sub-1",
            "email": "ana@example.com",
            "role": "Administrator",
            "is_active": True,
        }
        mock_sync.return_value = user

        self.client.post(
            reverse("accounts:login"),
            {"username": "ana@example.com", "password": "temporary"},
        )
        # Second POST: only the new password is required. The temporary
        # password is NOT re-entered; the stored challenge session is used.
        response = self.client.post(
            reverse("accounts:login"),
            {
                "username": "ana@example.com",
                "new_password1": "new-password",
                "new_password2": "new-password",
            },
        )

        self.assertRedirects(response, reverse("dashboard:admin"))
        self.assertEqual(self.client.session["cognito_sub"], "sub-1")
        self.assertEqual(
            self.client.session["cognito_id_token"], mock_respond.return_value["id_token"]
        )
        self.assertEqual(self.client.session["cognito_access_token"], "final-access-token")
        # The challenge session is cleared after a successful final login.
        self.assertNotIn("cognito_new_password_challenge", self.client.session)
        # initiate_auth is only called on the first POST; the second POST uses
        # the stored session via respond_to_new_password_challenge.
        mock_auth.assert_called_once_with("ana@example.com", "temporary")
        mock_respond.assert_called_once_with(
            "ana@example.com", "new-password", "fresh-cognito-challenge", ["email"]
        )
        mock_log.assert_called_once()

    def test_login_view_returns_validation_error_when_client_id_missing(self):
        runtime = Mock()
        runtime.get_cognito_client_id.return_value = ""
        with patch("accounts.forms.RuntimeConfig", return_value=runtime):
            response = self.client.post(
                reverse("accounts:login"),
                {"username": "ana@example.com", "password": "pass"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["form"].is_valid())
        self.assertIn(
            "No fue posible validar tus credenciales con NeuroFlex.",
            response.context["form"].errors["__all__"][0],
        )

    @patch("accounts.forms.CognitoAuthClient.respond_to_new_password_challenge")
    @patch("accounts.forms.CognitoAuthClient.initiate_auth")
    def test_second_post_without_stored_challenge_session_renders_expired_error(
        self, mock_auth, mock_respond
    ):
        # Simulate the challenge session expiring server-side before the
        # second POST: no ``cognito_new_password_challenge`` is stored, so the
        # view passes ``challenge_data=None`` to the form. The form must surface
        # a clear non-field error instead of falling back to the temporary
        # password.
        response = self.client.post(
            reverse("accounts:login"),
            {
                "username": "ana@example.com",
                "new_password1": "new-password",
                "new_password2": "new-password",
            },
        )

        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertFalse(form.is_valid())
        non_field_errors = form.non_field_errors()
        self.assertEqual(len(non_field_errors), 1)
        self.assertEqual(non_field_errors.as_data()[0].code, "challenge_expired")
        # The expired error is rendered in login.html so the user sees it.
        self.assertContains(response, "La sesión de cambio de contraseña expiró")
        # No Cognito call is made and the user is not logged in.
        mock_auth.assert_not_called()
        mock_respond.assert_not_called()
        self.assertNotIn("_auth_user_id", self.client.session)
        failed_login = AuditLog.objects.get(action="user_login_failed")
        self.assertEqual(failed_login.result, AuditLog.Result.FAILURE)

    @patch("accounts.views.log_event")
    @patch("accounts.forms.sync_local_user_from_remote_user")
    @patch("accounts.forms.ApiGatewayUsersClient.get_user")
    @patch("accounts.forms.CognitoAuthClient.initiate_auth")
    def test_online_login_success_syncs_terms_versions(
        self, mock_auth, mock_get, mock_sync, mock_log
    ):
        user = User.objects.create_user(
            username="ana@example.com",
            password="local-password",
            role=User.Role.ADMIN,
        )
        mock_auth.return_value = {
            "status": "authenticated",
            "id_token": _build_fake_jwt({"sub": "sub-1"}),
            "access_token": "access-token",
        }
        mock_get.return_value = {
            "user_id": "sub-1",
            "email": "ana@example.com",
            "role": "Administrator",
            "is_active": True,
        }
        mock_sync.return_value = user

        response = self.client.post(
            reverse("accounts:login"),
            {"username": "ana@example.com", "password": "pass"},
        )

        self.assertRedirects(response, reverse("dashboard:admin"))
        # La sincronización de TyC se dispara con el id_token del login online.
        self.terms_sync.assert_called_once_with(mock_auth.return_value["id_token"])

    @patch("accounts.views.log_event")
    @patch("accounts.forms.sync_local_user_from_remote_user")
    @patch("accounts.forms.ApiGatewayUsersClient.get_user")
    @patch("accounts.forms.CognitoAuthClient.initiate_auth")
    def test_online_login_succeeds_when_terms_sync_fails(
        self, mock_auth, mock_get, mock_sync, mock_log
    ):
        user = User.objects.create_user(
            username="ana@example.com",
            password="local-password",
            role=User.Role.ADMIN,
        )
        mock_auth.return_value = {
            "status": "authenticated",
            "id_token": _build_fake_jwt({"sub": "sub-1"}),
            "access_token": "access-token",
        }
        mock_get.return_value = {
            "user_id": "sub-1",
            "email": "ana@example.com",
            "role": "Administrator",
            "is_active": True,
        }
        mock_sync.return_value = user
        self.terms_sync.side_effect = TermsSyncError("API no disponible")

        response = self.client.post(
            reverse("accounts:login"),
            {"username": "ana@example.com", "password": "pass"},
        )

        # El fallo de sincronización de TyC no impide el login.
        self.assertRedirects(response, reverse("dashboard:admin"))
        self.terms_sync.assert_called_once()
        self.assertEqual(self.client.session["cognito_sub"], "sub-1")
