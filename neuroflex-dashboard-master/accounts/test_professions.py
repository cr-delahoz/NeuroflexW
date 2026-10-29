from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase, override_settings
from django.template import RequestContext
from django.urls import reverse

from audit.models import AuditLog
from integrations.services.api_gateway_professions_client import (
    ApiGatewayProfessionsClient,
    ApiGatewayProfessionsServiceError,
    DEFAULT_PROFESSION_ID,
)

from accounts.models import Profession
from accounts.services import (
    sync_local_user_from_remote_user,
    sync_professions_from_remote,
)
from accounts.views import (
    ProfessionCreateView,
    ProfessionDeleteView,
    UserListView,
    UserProfessionUpdateView,
)


User = get_user_model()


def _profession_payload(profession_id, name, is_default=False, is_active=True):
    return {
        "profession_id": profession_id,
        "name": name,
        "is_default": is_default,
        "is_active": is_active,
        "created_at": 1700000000,
    }


class ProfessionSyncTests(TestCase):
    def test_sync_creates_mirrors_and_deletes_removed_professions(self):
        Profession.objects.create(pk="vieja", name="Vieja profesion")

        sync_professions_from_remote(
            "token",
            type(
                "Client",
                (),
                {
                    "list_professions": lambda self, token: [
                        _profession_payload("sin-profesion", "Sin profesion asignada", is_default=True),
                        _profession_payload("p-1", "Kinesiologo"),
                    ]
                },
            )(),
        )

        self.assertTrue(Profession.objects.filter(pk="p-1", name="Kinesiologo").exists())
        self.assertFalse(Profession.objects.filter(pk="vieja").exists())
        default = Profession.objects.get(pk=DEFAULT_PROFESSION_ID)
        self.assertTrue(default.is_default)

    def test_sync_rejects_incomplete_payload(self):
        with self.assertRaises(ValueError):
            sync_professions_from_remote(
                "token",
                type(
                    "Client",
                    (),
                    {"list_professions": lambda self, token: [{"profession_id": "p-1"}]},
                )(),
            )


class UserProfessionSyncTests(TestCase):
    def test_sync_sets_profession_fk_when_mirror_exists(self):
        Profession.objects.create(pk="p-1", name="Psicologo")
        user = User.objects.create_user(username="ana@example.com", email="ana@example.com", password="x")

        synced = sync_local_user_from_remote_user({
            "user_id": "sub-1",
            "email": "ana@example.com",
            "role": "Specialist",
            "profession_id": "p-1",
        })

        self.assertEqual(synced.profession.pk, "p-1")

    def test_sync_without_profession_keeps_existing_assignment(self):
        Profession.objects.create(pk="p-1", name="Psicologo")
        user = User.objects.create_user(
            username="ana@example.com", email="ana@example.com", password="x"
        )
        user.profession_id = "p-1"
        user.save()

        synced = sync_local_user_from_remote_user({
            "user_id": "sub-1",
            "email": "ana@example.com",
            "role": "Specialist",
        })

        self.assertEqual(synced.profession.pk, "p-1")

    def test_sync_with_unknown_profession_id_falls_back_to_none(self):
        user = User.objects.create_user(username="ana@example.com", email="ana@example.com", password="x")

        synced = sync_local_user_from_remote_user({
            "user_id": "sub-1",
            "email": "ana@example.com",
            "role": "Specialist",
            "profession_id": "desconocida",
        })

        self.assertIsNone(synced.profession)


class ProfessionViewTestBase(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
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
        Profession.objects.create(
            pk=DEFAULT_PROFESSION_ID,
            name="Sin profesion asignada",
            is_default=True,
        )
        Profession.objects.create(pk="p-1", name="Kinesiologo")
        professions_patcher = patch(
            "accounts.views.ApiGatewayProfessionsClient.list_professions",
            return_value=[],
        )
        professions_patcher.start()
        self.addCleanup(professions_patcher.stop)

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


class UserProfessionUpdateViewTests(ProfessionViewTestBase):
    @patch("accounts.views.sync_professions_from_remote", return_value=None)
    @patch("accounts.views.sync_local_user_from_remote_user")
    @patch("accounts.views.ApiGatewayUsersClient.update_user_profession")
    def test_update_profession_audits_and_syncs(self, update, sync, _prof_sync):
        update.return_value = {
            "user_id": "sub-specialist",
            "email": "specialist@example.com",
            "role": "Specialist",
            "profession_id": "p-1",
        }
        response = UserProfessionUpdateView.as_view()(
            self.request("post", "/users/x/update-profession/", {"profession_id": "p-1"}),
            user_id=self.specialist.pk,
        )
        self.assertEqual(response.status_code, 302)
        update.assert_called_once_with("id-token", "sub-specialist", "p-1")
        entry = AuditLog.objects.get(action="user_profession_updated")
        self.assertEqual(entry.actor, self.admin)
        self.assertEqual(entry.resource_id, "sub-specialist")
        self.assertEqual(entry.metadata, {"profession_id": "p-1"})

    @patch(
        "accounts.views.ApiGatewayUsersClient.update_user_profession",
        side_effect=ApiGatewayProfessionsServiceError,
    )
    def test_api_failure_does_not_audit_success(self, _):
        response = UserProfessionUpdateView.as_view()(
            self.request("post", "/users/x/update-profession/", {"profession_id": "p-1"}),
            user_id=self.specialist.pk,
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(AuditLog.objects.filter(action="user_profession_updated").exists())

    def test_specialist_cannot_change_professions(self):
        response = UserProfessionUpdateView.as_view()(
            self.request(
                "post",
                "/users/x/update-profession/",
                {"profession_id": "p-1"},
                user=self.specialist,
            ),
            user_id=self.specialist.pk,
        )
        self.assertEqual(response.status_code, 403)


class ProfessionCreateViewTests(ProfessionViewTestBase):
    @patch("accounts.views.sync_professions_from_remote", return_value=None)
    @patch("accounts.views.ApiGatewayProfessionsClient.create_profession")
    def test_create_profession_audits_and_redirects(self, create, _sync):
        create.return_value = {
            "profession_id": "p-2",
            "name": "Psicologo",
            "is_default": False,
            "is_active": True,
            "created_at": 1700000000,
        }
        response = ProfessionCreateView.as_view()(
            self.request("post", "/professions/create/", {"name": "Psicologo"})
        )
        self.assertEqual(response.status_code, 302)
        create.assert_called_once_with("id-token", "Psicologo")
        entry = AuditLog.objects.get(action="profession_created")
        self.assertEqual(entry.actor, self.admin)
        self.assertEqual(entry.metadata, {"name": "Psicologo"})

    def test_empty_name_rejected_without_remote_call(self):
        with patch("accounts.views.ApiGatewayProfessionsClient.create_profession") as create:
            response = ProfessionCreateView.as_view()(
                self.request("post", "/professions/create/", {"name": "   "})
            )
            self.assertEqual(response.status_code, 400)
            create.assert_not_called()

    @patch(
        "accounts.views.ApiGatewayProfessionsClient.create_profession",
        side_effect=ApiGatewayProfessionsServiceError,
    )
    def test_api_failure_does_not_audit_success(self, _):
        response = ProfessionCreateView.as_view()(
            self.request("post", "/professions/create/", {"name": "Psicologo"})
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(AuditLog.objects.filter(action="profession_created").exists())


class ProfessionDeleteViewTests(ProfessionViewTestBase):
    def test_default_profession_is_protected(self):
        with patch.object(ApiGatewayProfessionsClient, "delete_profession") as delete:
            response = ProfessionDeleteView.as_view()(
                self.request("post", "/professions/sin-profesion/delete/"),
                profession_id=DEFAULT_PROFESSION_ID,
            )
            self.assertEqual(response.status_code, 403)
            delete.assert_not_called()

    @patch("accounts.views.sync_professions_from_remote", return_value=None)
    @patch("accounts.views.ApiGatewayProfessionsClient.delete_profession")
    def test_delete_audits_reassignment(self, delete, _sync):
        delete.return_value = {
            "profession_id": "p-1",
            "reassigned_users": 3,
            "reassigned_to": DEFAULT_PROFESSION_ID,
        }
        response = ProfessionDeleteView.as_view()(
            self.request(
                "post",
                "/professions/p-1/delete/",
                {"reassign_to": DEFAULT_PROFESSION_ID},
            ),
            profession_id="p-1",
        )
        self.assertEqual(response.status_code, 302)
        delete.assert_called_once_with(
            "id-token", "p-1", reassign_to=DEFAULT_PROFESSION_ID
        )
        entry = AuditLog.objects.get(action="profession_deleted")
        self.assertEqual(entry.metadata, {
            "reassigned_users": 3,
            "reassigned_to": DEFAULT_PROFESSION_ID,
        })

    @patch(
        "accounts.views.ApiGatewayProfessionsClient.delete_profession",
        side_effect=ApiGatewayProfessionsServiceError,
    )
    def test_api_failure_does_not_audit_success(self, _):
        response = ProfessionDeleteView.as_view()(
            self.request("post", "/professions/p-1/delete/"),
            profession_id="p-1",
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(AuditLog.objects.filter(action="profession_deleted").exists())


class UserListViewProfessionsTests(ProfessionViewTestBase):
    @patch("accounts.views.reconcile_local_users_from_remote_listing")
    @patch("accounts.views.sync_professions_from_remote", return_value=None)
    def test_list_renders_profession_select(self, _sync, reconcile):
        reconcile.return_value = [self.specialist]
        response = UserListView.as_view()(self.request("get", "/users/"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cambiar profesion")


@override_settings(STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage")
class SidebarLabelTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _render(self, variant, user, profession=None):
        request = self.factory.get("/")
        SessionMiddleware(lambda request: None).process_request(request)
        request.session.save()
        request.user = user
        context = RequestContext(request, {
            "sidebar_variant": variant,
            "role_label": "Especialista",
        })
        from django.template.loader import render_to_string

        return render_to_string(
            "components/sidebar.html",
            context.flatten(),
            request=request,
        )

    def test_specialist_shows_profession_name(self):
        Profession.objects.create(pk="p-1", name="Neurologo")
        user = User.objects.create_user(username="ana@example.com", password="x")
        user.profession_id = "p-1"
        user.save()
        content = self._render("specialist", user)
        self.assertIn("Neurologo", content)
        self.assertNotIn(">Especialista<", content)

    def test_specialist_without_profession_shows_default_label(self):
        user = User.objects.create_user(username="ana@example.com", password="x")
        content = self._render("specialist", user)
        self.assertIn("Sin profesion asignada", content)

    def test_admin_keeps_role_label(self):
        user = User.objects.create_user(
            username="admin@example.com", password="x", role=User.Role.ADMIN
        )
        context_vars = {"sidebar_variant": "admin", "role_label": "Administrador"}
        request = self.factory.get("/")
        request.user = user
        from django.template.loader import render_to_string

        content = render_to_string(
            "components/sidebar.html", context_vars, request=request
        )
        self.assertIn("Administrador", content)
        self.assertNotIn("Sin profesion asignada", content)


class RemoteUserCreationFormProfessionTests(TestCase):
    def test_form_builds_profession_choices_and_defaults(self):
        from accounts.forms import RemoteUserCreationForm

        Profession.objects.create(pk="p-1", name="Psiquiatra")
        form = RemoteUserCreationForm(
            professions=list(Profession.objects.filter(is_active=True).order_by("name"))
        )
        self.assertIn(("p-1", "Psiquiatra"), form.fields["profession_id"].choices)
        data = {
            "email": "n@example.com",
            "first_name": "N",
            "last_name": "P",
            "role": "Specialist",
        }
        bound = RemoteUserCreationForm(data)
        self.assertTrue(bound.is_valid())
        self.assertEqual(bound.cleaned_data["profession_id"], DEFAULT_PROFESSION_ID)
