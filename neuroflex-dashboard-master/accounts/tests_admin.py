from unittest.mock import ANY, patch

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase
from django.urls import reverse

from audit.models import AuditLog
from integrations.services.api_gateway_users_client import (
    ApiGatewayUsersInvalidResponseError,
    ApiGatewayUsersNotFoundError,
    ApiGatewayUsersServiceError,
)
from .views import (
    PdfPermissionGrantView,
    PdfPermissionRevokeView,
    SpecialistCreateView,
    UserActivateView,
    UserDeactivateView,
    UserListView,
    UserRoleUpdateView,
)


User = get_user_model()


class RemoteUserAdministrationTests(TestCase):
    def setUp(self):
        self.base_url_patcher = patch(
            "integrations.services.neuroflex_api_client.RuntimeConfig.get_neuroflex_api_base_url",
            return_value="https://api.example.test/dev",
        )
        self.base_url_patcher.start()
        self.addCleanup(self.base_url_patcher.stop)
        self.professions_patcher = patch(
            "accounts.views.ApiGatewayProfessionsClient.list_professions",
            return_value=[],
        )
        self.professions_patcher.start()
        self.addCleanup(self.professions_patcher.stop)
        self.admin = User.objects.create_user(
            username="admin@example.com",
            role=User.Role.ADMIN,
            cognito_sub="sub-admin",
        )
        self.specialist = User.objects.create_user(
            username="specialist@example.com",
            role=User.Role.SPECIALIST,
            cognito_sub="sub-specialist",
        )
        self.factory = RequestFactory()

    def request(self, method, path, data=None, user=None, token="id-token"):
        request = getattr(self.factory, method)(path, data or {})
        SessionMiddleware(lambda request: None).process_request(request)
        request.session.save()
        setattr(request, "_messages", FallbackStorage(request))
        if token:
            request.session["cognito_id_token"] = token
            request.session.save()
        request.user = user or self.admin
        return request

    @patch("accounts.views.reconcile_local_users_from_remote_listing")
    def test_list_reconciles_remote_users_with_session_token(self, reconcile):
        reconcile.return_value = [self.specialist]
        response = UserListView.as_view()(self.request("get", "/users/"))
        self.assertEqual(response.status_code, 200)
        reconcile.assert_called_once_with("id-token", ANY)

    @patch("accounts.views.ApiGatewayUsersClient.list_users", return_value=([], None))
    def test_list_filters_by_role(self, list_users):
        response = UserListView.as_view()(
            self.request("get", "/users/", {"role": "Administrator"})
        )

        self.assertEqual(response.status_code, 200)
        list_users.assert_called_once_with(
            "id-token", role="Administrator", is_active=None, limit=50, next_token=None
        )

    @patch("accounts.views.ApiGatewayUsersClient.list_users", return_value=([], None))
    def test_list_filters_by_active_status(self, list_users):
        response = UserListView.as_view()(
            self.request("get", "/users/", {"is_active": "true"})
        )

        self.assertEqual(response.status_code, 200)
        list_users.assert_called_once_with(
            "id-token", role=None, is_active=True, limit=50, next_token=None
        )

    @patch("accounts.views.ApiGatewayUsersClient.list_users", return_value=([], None))
    def test_list_filters_by_role_and_active_status(self, list_users):
        response = UserListView.as_view()(
            self.request(
                "get", "/users/", {"role": "Administrator", "is_active": "false"}
            )
        )

        self.assertEqual(response.status_code, 200)
        list_users.assert_called_once_with(
            "id-token", role="Administrator", is_active=False, limit=50, next_token=None
        )

    @patch("accounts.views.ApiGatewayUsersClient.list_users", return_value=([], None))
    def test_list_ignores_invalid_filters(self, list_users):
        response = UserListView.as_view()(
            self.request("get", "/users/", {"role": "Invalid", "is_active": "maybe"})
        )

        self.assertEqual(response.status_code, 200)
        list_users.assert_called_once_with(
            "id-token", role=None, is_active=None, limit=50, next_token=None
        )

    @patch(
        "accounts.views.ApiGatewayUsersClient.create_user",
        return_value={
            "user_id": "sub-new",
            "email": "new@example.com",
            "role": "Administrator",
            "is_active": True,
        },
    )
    def test_create_sends_remote_contract_and_saves_only_names(self, mock_create):
        request = self.request(
            "post",
            "/users/create/",
            {
                "email": "new@example.com",
                "first_name": "Ana",
                "last_name": "Paz",
                "role": "Administrator",
            },
        )
        response = SpecialistCreateView.as_view()(request)
        self.assertEqual(response.status_code, 302)
        mock_create.assert_called_once_with(
            "id-token", "new@example.com", "Administrator", profession_id="sin-profesion"
        )
        user = User.objects.get(cognito_sub="sub-new")
        self.assertEqual((user.first_name, user.last_name), ("Ana", "Paz"))
        self.assertEqual(user.role, User.Role.ADMIN)
        entry = AuditLog.objects.get(action="user_created")
        self.assertEqual(
            entry.metadata, {"role": "Administrator", "profession_id": "sin-profesion"}
        )

    @patch(
        "accounts.views.ApiGatewayUsersClient.create_user",
        return_value={
            "user_id": "sub-new",
            "email": "new@example.com",
            "is_active": True,
        },
    )
    def test_create_uses_requested_role_when_remote_payload_lacks_role(self, mock_create):
        request = self.request(
            "post",
            "/users/create/",
            {
                "email": "new@example.com",
                "first_name": "Ana",
                "last_name": "Paz",
                "role": "Administrator",
            },
        )
        response = SpecialistCreateView.as_view()(request)
        self.assertEqual(response.status_code, 302)
        mock_create.assert_called_once_with(
            "id-token", "new@example.com", "Administrator", profession_id="sin-profesion"
        )
        user = User.objects.get(cognito_sub="sub-new")
        self.assertEqual(user.role, User.Role.ADMIN)
        entry = AuditLog.objects.get(action="user_created")
        self.assertEqual(
            entry.metadata, {"role": "Administrator", "profession_id": "sin-profesion"}
        )

    @patch("accounts.views.ApiGatewayUsersClient.update_user_role")
    def test_invalid_role_never_calls_remote_api(self, update):
        response = UserRoleUpdateView.as_view()(
            self.request("post", "/users/role/", {"role": "ADMIN"}),
            user_id=self.specialist.pk,
        )
        self.assertEqual(response.status_code, 400)
        update.assert_not_called()

    @patch("accounts.views.ApiGatewayUsersClient.update_user_status")
    @patch("accounts.views.sync_local_user_from_remote_user")
    def test_status_audits_success_without_secrets(self, sync, update):
        for view, path, active, action in (
            (UserActivateView, "/users/activate/", True, "user_activated"),
            (UserDeactivateView, "/users/deactivate/", False, "user_deactivated"),
        ):
            remote_user = {
                "user_id": "sub-specialist",
                "email": self.specialist.username,
                "role": "Specialist",
                "is_active": active,
            }
            update.return_value = remote_user
            response = view.as_view()(self.request("post", path), user_id=self.specialist.pk)
            self.assertEqual(response.status_code, 302)
            update.assert_called_once_with("id-token", "sub-specialist", active)
            sync.assert_called_once_with(remote_user)
            entry = AuditLog.objects.get(action=action)
            self.assertEqual(entry.actor, self.admin)
            self.assertEqual(entry.resource_id, "sub-specialist")
            self.assertEqual(entry.metadata, {"active": active})
            self.assertNotIn("id-token", str(entry.metadata))
            self.assertNotIn("password", str(entry.metadata).lower())
            update.reset_mock()
            sync.reset_mock()
            AuditLog.objects.all().delete()

    @patch("accounts.views.ApiGatewayUsersClient.update_user_role")
    @patch("accounts.views.sync_local_user_from_remote_user")
    def test_role_change_audits_explicit_action_without_secrets(self, sync, update):
        remote_user = {
            "user_id": "sub-specialist",
            "email": self.specialist.username,
            "role": "Administrator",
            "is_active": True,
        }
        update.return_value = remote_user
        response = UserRoleUpdateView.as_view()(
            self.request("post", "/users/role/", {"role": "Administrator"}),
            user_id=self.specialist.pk,
        )
        self.assertEqual(response.status_code, 302)
        entry = AuditLog.objects.get(action="user_role_changed")
        self.assertEqual(entry.actor, self.admin)
        self.assertEqual(entry.resource_id, "sub-specialist")
        self.assertEqual(entry.metadata, {"role": "Administrator"})
        self.assertNotIn("id-token", str(entry.metadata))
        self.assertNotIn("password", str(entry.metadata).lower())

    @patch("accounts.views.ApiGatewayUsersClient.update_user_status")
    @patch("accounts.views.sync_local_user_from_remote_user")
    def test_status_success_shows_feedback_message(self, sync, update):
        for view, path, active, expected in (
            (UserActivateView, "/users/activate/", True, "fue activada"),
            (UserDeactivateView, "/users/deactivate/", False, "fue desactivada"),
        ):
            remote_user = {
                "user_id": "sub-specialist",
                "email": self.specialist.username,
                "role": "Specialist",
                "is_active": active,
            }
            update.return_value = remote_user
            request = self.request("post", path)
            response = view.as_view()(request, user_id=self.specialist.pk)
            self.assertEqual(response.status_code, 302)
            rendered = [str(message) for message in get_messages(request)]
            self.assertTrue(
                any(expected in message for message in rendered),
                f"Expected a success message containing {expected!r}, got {rendered!r}",
            )
            update.reset_mock()
            sync.reset_mock()

    @patch("accounts.views.ApiGatewayUsersClient.update_user_role")
    @patch("accounts.views.sync_local_user_from_remote_user")
    def test_role_change_success_shows_feedback_message(self, sync, update):
        remote_user = {
            "user_id": "sub-specialist",
            "email": self.specialist.username,
            "role": "Administrator",
            "is_active": True,
        }
        update.return_value = remote_user
        request = self.request("post", "/users/role/", {"role": "Administrator"})
        response = UserRoleUpdateView.as_view()(request, user_id=self.specialist.pk)
        self.assertEqual(response.status_code, 302)
        rendered = [str(message) for message in get_messages(request)]
        self.assertTrue(
            any("fue actualizado a 'Administrador'" in message for message in rendered),
            f"Expected a role-change success message, got {rendered!r}",
        )

    def test_pdf_permission_change_shows_feedback_message(self):
        for view, path, expected in (
            (PdfPermissionGrantView, "/users/pdf-grant/", "Se habilito"),
            (PdfPermissionRevokeView, "/users/pdf-revoke/", "Se deshabilito"),
        ):
            request = self.request("post", path)
            response = view.as_view()(request, user_id=self.specialist.pk)
            self.assertEqual(response.status_code, 302)
            rendered = [str(message) for message in get_messages(request)]
            self.assertTrue(
                any(expected in message for message in rendered),
                f"Expected a PDF permission message containing {expected!r}, got {rendered!r}",
            )

    @patch(
        "accounts.views.ApiGatewayUsersClient.create_user",
        side_effect=ApiGatewayUsersServiceError,
    )
    def test_create_api_failure_does_not_audit_success(self, _):
        response = SpecialistCreateView.as_view()(
            self.request(
                "post",
                "/users/create/",
                {
                    "email": "new@example.com",
                    "first_name": "Ana",
                    "last_name": "Paz",
                    "role": "Administrator",
                },
            )
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(AuditLog.objects.filter(action="user_created").exists())

    @patch(
        "accounts.views.reconcile_local_users_from_remote_listing",
        side_effect=ApiGatewayUsersInvalidResponseError,
    )
    def test_list_invalid_response_redirects_with_no_audit(self, _):
        response = UserListView.as_view()(self.request("get", "/users/"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("accounts:user-list"))
        self.assertFalse(AuditLog.objects.exists())

    @patch(
        "accounts.views.ApiGatewayUsersClient.create_user",
        side_effect=ApiGatewayUsersInvalidResponseError,
    )
    def test_create_invalid_response_redirects_without_local_user(self, _):
        response = SpecialistCreateView.as_view()(
            self.request(
                "post",
                "/users/create/",
                {
                    "email": "new@example.com",
                    "first_name": "Ana",
                    "last_name": "Paz",
                    "role": "Administrator",
                },
            )
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(User.objects.filter(username="new@example.com").exists())
        self.assertFalse(AuditLog.objects.filter(action="user_created").exists())

    @patch(
        "accounts.views.ApiGatewayUsersClient.update_user_status",
        side_effect=ApiGatewayUsersServiceError,
    )
    def test_status_api_failure_does_not_audit_success(self, _):
        response = UserDeactivateView.as_view()(
            self.request("post", "/users/deactivate/"), user_id=self.specialist.pk
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(AuditLog.objects.filter(action="user_deactivated").exists())

    @patch(
        "accounts.views.ApiGatewayUsersClient.update_user_status",
        side_effect=ApiGatewayUsersNotFoundError,
    )
    def test_status_not_found_redirects_without_local_mutation(self, _):
        response = UserDeactivateView.as_view()(
            self.request("post", "/users/deactivate/"), user_id=self.specialist.pk
        )
        self.specialist.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.specialist.is_active)
        self.assertFalse(AuditLog.objects.filter(action="user_deactivated").exists())

    @patch(
        "accounts.views.ApiGatewayUsersClient.update_user_role",
        side_effect=ApiGatewayUsersServiceError,
    )
    def test_role_api_failure_does_not_audit_success(self, _):
        response = UserRoleUpdateView.as_view()(
            self.request("post", "/users/role/", {"role": "Administrator"}),
            user_id=self.specialist.pk,
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(AuditLog.objects.filter(action="user_role_changed").exists())

    @patch(
        "accounts.views.ApiGatewayUsersClient.update_user_role",
        side_effect=ApiGatewayUsersNotFoundError,
    )
    def test_role_not_found_redirects_without_local_mutation(self, _):
        response = UserRoleUpdateView.as_view()(
            self.request("post", "/users/role/", {"role": "Administrator"}),
            user_id=self.specialist.pk,
        )
        self.specialist.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.specialist.role, User.Role.SPECIALIST)
        self.assertFalse(AuditLog.objects.filter(action="user_role_changed").exists())

    @patch("accounts.views.ApiGatewayUsersClient")
    def test_missing_token_redirects_without_api_call(self, mock_client):
        requests = (
            (UserListView, "get", "/users/", None, {}),
            (SpecialistCreateView, "post", "/users/create/", None, {}),
            (UserDeactivateView, "post", "/users/deactivate/", self.specialist.pk, {}),
            (UserRoleUpdateView, "post", "/users/role/", self.specialist.pk, {"role": "Administrator"}),
        )
        for view, method, path, user_id, data in requests:
            kwargs = {} if user_id is None else {"user_id": user_id}
            response = view.as_view()(
                self.request(method, path, data, token=""), **kwargs
            )
            self.assertEqual(response.url, reverse("accounts:login"))
        mock_client.assert_not_called()
        self.assertFalse(AuditLog.objects.exists())

    def test_specialist_cannot_mutate_remote_users(self):
        requests = (
            (SpecialistCreateView, "/users/create/", None),
            (UserDeactivateView, "/users/deactivate/", self.admin.pk),
            (UserRoleUpdateView, "/users/role/", self.admin.pk),
        )
        for view, path, user_id in requests:
            kwargs = {} if user_id is None else {"user_id": user_id}
            response = view.as_view()(
                self.request(
                    "post", path, {"role": "Administrator"}, user=self.specialist
                ),
                **kwargs,
            )
            self.assertEqual(response.status_code, 403)
