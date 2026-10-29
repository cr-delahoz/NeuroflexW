import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from audit.models import AuditLog
from terms.models import TermsVersion
from terms.services import (
    TermsPublicationForbiddenError,
    TermsSyncError,
    TermsVersionNotFoundError,
)

ROOT = Path(__file__).resolve().parents[2]


@override_settings(MEDIA_ROOT=tempfile.gettempdir())
class TermsViewsTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        from accounts.models import CustomUser

        cls.admin_user = CustomUser.objects.create_user(
            username="admin_user",
            password="test-pass-123",
            role=CustomUser.Role.ADMIN,
        )
        cls.specialist_user = CustomUser.objects.create_user(
            username="specialist_user",
            password="test-pass-123",
            role=CustomUser.Role.SPECIALIST,
        )

    def setUp(self):
        self.base_url_patcher = patch(
            "integrations.services.neuroflex_api_client.RuntimeConfig.get_neuroflex_api_base_url",
            return_value="https://api.example.test/dev",
        )
        self.base_url_patcher.start()
        self.addCleanup(self.base_url_patcher.stop)

    def login_admin(self):
        self.client.login(username="admin_user", password="test-pass-123")
        session = self.client.session
        session["cognito_id_token"] = "id-token"
        session.save()
        return session

    def login_specialist(self):
        self.client.login(username="specialist_user", password="test-pass-123")
        session = self.client.session
        session["cognito_id_token"] = "id-token"
        session.save()
        return session


class TermsListViewTests(TermsViewsTestBase):
    @patch(
        "terms.views.sync_terms_history",
        return_value={"created": 2, "updated": 1, "unchanged": 0},
    )
    def test_admin_sees_history_after_sync(self, mock_sync):
        self.login_admin()
        TermsVersion.objects.create(
            version_id="tc-1",
            language="es",
            title="Terminos tc-1",
            content="",
            content_hash="x",
            published=True,
        )

        response = self.client.get(reverse("terms:terms-list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "tc-1")
        self.assertEqual(
            AuditLog.objects.filter(
                action="terms_catalog_synced", result=AuditLog.Result.SUCCESS
            ).count(),
            1,
        )

    @patch(
        "terms.views.sync_terms_history",
        return_value={"created": 0, "updated": 0, "unchanged": 0},
    )
    def test_messages_render_with_correct_tone(self, mock_sync):
        self.login_admin()
        TermsVersion.objects.create(
            version_id="tc-1",
            language="es",
            title="Terminos tc-1",
            content="",
            content_hash="x",
            published=True,
        )

        response = self.client.get(reverse("terms:terms-list"), follow=True)

        self.assertEqual(response.status_code, 200)
        source = (ROOT / "templates" / "terms" / "terms_list.html").read_text(encoding="utf-8")
        self.assertIn("tone=message.level_tag", source)
        self.assertNotIn("tone=level ", source)

    def test_detail_and_create_templates_use_level_tag_tone(self):
        for name in ("terms_detail.html", "terms_create.html"):
            source = (ROOT / "templates" / "terms" / name).read_text(encoding="utf-8")
            self.assertIn("tone=message.level_tag", source)
            self.assertNotIn('tone="error" message=message', source)

    @patch(
        "terms.views.sync_terms_history",
        side_effect=TermsSyncError("down"),
    )
    def test_sync_failure_still_renders_local_mirror(self, mock_sync):
        self.login_admin()
        TermsVersion.objects.create(
            version_id="tc-1",
            language="es",
            title="Terminos tc-1",
            content="",
            content_hash="x",
            published=True,
        )

        response = self.client.get(reverse("terms:terms-list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "tc-1")
        self.assertTrue(
            AuditLog.objects.filter(
                action="terms_catalog_synced", result=AuditLog.Result.FAILURE
            ).exists()
        )

    def test_specialist_is_denied(self):
        self.login_specialist()

        response = self.client.get(reverse("terms:terms-list"))

        self.assertEqual(response.status_code, 403)
        self.assertTrue(
            AuditLog.objects.filter(action="authorization_denied").exists()
        )

    def test_anonymous_redirects_to_login(self):
        response = self.client.get(reverse("terms:terms-list"))

        self.assertEqual(response.status_code, 302)


class TermsDetailViewTests(TermsViewsTestBase):
    @patch(
        "terms.views.fetch_terms_version",
        return_value={
            "version_id": "tc-1",
            "language": "es",
            "title": "Terminos tc-1",
            "content": "Contenido completo de los terminos",
            "content_hash": "sha256-new",
            "published": "true",
        },
    )
    def test_detail_fetches_and_caches_content(self, mock_fetch):
        self.login_admin()
        TermsVersion.objects.create(
            version_id="tc-1",
            language="es",
            title="Terminos tc-1",
            content="",
            content_hash="sha256-old",
            published=True,
        )

        response = self.client.get(
            reverse("terms:terms-detail", args=["tc-1", "es"])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Contenido completo de los terminos")
        cached = TermsVersion.objects.get(version_id="tc-1")
        self.assertEqual(cached.content, "Contenido completo de los terminos")
        self.assertEqual(cached.content_hash, "sha256-new")
        self.assertTrue(
            AuditLog.objects.filter(
                actor=self.admin_user,
                action="terms_viewed",
                resource_id="tc-1",
            ).exists()
        )

    def test_detail_uses_cached_content_without_fetch(self):
        self.login_admin()
        TermsVersion.objects.create(
            version_id="tc-1",
            language="es",
            title="Terminos tc-1",
            content="Contenido cacheado",
            content_hash="x",
            published=True,
        )

        with patch("terms.views.fetch_terms_version") as mock_fetch:
            response = self.client.get(
                reverse("terms:terms-detail", args=["tc-1", "es"])
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Contenido cacheado")
        mock_fetch.assert_not_called()

    @patch(
        "terms.views.fetch_terms_version",
        side_effect=TermsSyncError("down"),
    )
    def test_fetch_failure_renders_notice(self, mock_fetch):
        self.login_admin()
        TermsVersion.objects.create(
            version_id="tc-1",
            language="es",
            title="Terminos tc-1",
            content="",
            content_hash="x",
            published=True,
        )

        response = self.client.get(
            reverse("terms:terms-detail", args=["tc-1", "es"])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No fue posible cargar el contenido")
        self.assertTrue(
            AuditLog.objects.filter(
                action="terms_viewed", resource_id="tc-1"
            ).exists()
        )

    def test_unknown_version_returns_404(self):
        self.login_admin()

        response = self.client.get(
            reverse("terms:terms-detail", args=["tc-nope", "es"])
        )

        self.assertEqual(response.status_code, 404)


class TermsCreateViewTests(TermsViewsTestBase):
    def _post(self, **overrides):
        data = {
            "title": "Terminos y condiciones NeuroFlex",
            "language": "es",
            "published": "on",
            "content": "Nuevo contenido de los terminos",
        }
        data.update(overrides)
        return self.client.post(reverse("terms:terms-create"), data)

    @patch(
        "terms.views.create_terms_version",
        return_value={"version_id": "tc-20261001-120000", "content_hash": "sha256-new"},
    )
    def test_admin_creates_version_and_audits(self, mock_create):
        self.login_admin()

        response = self._post()

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("terms:terms-list"), fetch_redirect_response=False)
        created = TermsVersion.objects.get(version_id="tc-20261001-120000")
        self.assertEqual(created.content, "Nuevo contenido de los terminos")
        self.assertTrue(created.published)
        self.assertTrue(
            AuditLog.objects.filter(
                actor=self.admin_user,
                action="terms_version_created",
                resource_id="tc-20261001-120000",
                metadata__version_id="tc-20261001-120000",
            ).exists()
        )

    @patch("terms.views.create_terms_version")
    def test_conflict_regenerates_version_id(self, mock_create):
        from terms.services import TermsVersionConflictError

        mock_create.side_effect = [
            TermsVersionConflictError("duplicate"),
            {"version_id": "tc-suffixed", "content_hash": "h"},
        ]
        self.login_admin()

        response = self._post()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(mock_create.call_count, 2)
        first_id = mock_create.call_args_list[0].args[1]
        second_id = mock_create.call_args_list[1].args[1]
        self.assertNotEqual(first_id, second_id)
        self.assertRegex(second_id, r"-[0-9a-f]{4}$")
        self.assertTrue(
            TermsVersion.objects.filter(version_id="tc-suffixed").exists()
        )

    @patch(
        "terms.views.create_terms_version",
        side_effect=TermsSyncError("down"),
    )
    def test_api_failure_shows_error_and_audits_nothing(self, mock_create):
        self.login_admin()

        response = self._post()

        self.assertEqual(response.status_code, 200)
        self.assertFalse(TermsVersion.objects.exists())
        self.assertFalse(
            AuditLog.objects.filter(action="terms_version_created").exists()
        )

    def test_specialist_is_denied(self):
        self.login_specialist()

        response = self._post()

        self.assertEqual(response.status_code, 403)

    @patch(
        "terms.views.create_terms_version",
        return_value={"version_id": "tc-meta", "content_hash": "h"},
    )
    def test_created_audit_metadata_excludes_content(self, mock_create):
        self.login_admin()
        self._post()

        logged = AuditLog.objects.get(action="terms_version_created")
        self.assertNotIn("content", logged.metadata)
        self.assertNotIn("content_file", logged.metadata)
        self.assertEqual(logged.metadata["content_length"], len("Nuevo contenido de los terminos"))


class TermsSetCurrentViewTests(TermsViewsTestBase):
    def _create_history(self):
        TermsVersion.objects.create(
            version_id='tc-vigente',
            language='es',
            title='Version vigente',
            content='Contenido vigente',
            content_hash='h-vigente',
            published=True,
        )
        TermsVersion.objects.create(
            version_id='tc-historica',
            language='es',
            title='Version historica',
            content='Contenido historico',
            content_hash='h-historica',
            published=False,
        )

    @patch(
        'terms.views.set_terms_publication',
        return_value={'version_id': 'tc-historica', 'language': 'es', 'published': True},
    )
    def test_admin_sets_current_and_audits(self, mock_set):
        self.login_admin()
        self._create_history()

        response = self.client.post(
            reverse('terms:terms-set-current', args=['tc-historica', 'es'])
        )

        self.assertRedirects(response, reverse('terms:terms-list'), fetch_redirect_response=False)
        mock_set.assert_called_once_with('id-token', 'tc-historica', 'es', published=True)
        self.assertTrue(
            TermsVersion.objects.get(version_id='tc-historica').published
        )
        self.assertFalse(
            TermsVersion.objects.get(version_id='tc-vigente').published
        )
        self.assertTrue(
            AuditLog.objects.filter(
                actor=self.admin_user,
                action='terms_publication_changed',
                resource_id='tc-historica',
                result=AuditLog.Result.SUCCESS,
            ).exists()
        )

    @patch(
        'terms.views.set_terms_publication',
        side_effect=TermsSyncError('down'),
    )
    def test_api_failure_keeps_mirror_and_audits_failure(self, mock_set):
        self.login_admin()
        self._create_history()

        response = self.client.post(
            reverse('terms:terms-set-current', args=['tc-historica', 'es']), follow=True
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No fue posible cambiar la vigencia')
        self.assertTrue(
            TermsVersion.objects.get(version_id='tc-vigente').published
        )
        self.assertFalse(
            TermsVersion.objects.get(version_id='tc-historica').published
        )
        self.assertTrue(
            AuditLog.objects.filter(
                action='terms_publication_changed',
                result=AuditLog.Result.FAILURE,
                resource_id='tc-historica',
            ).exists()
        )

    @patch(
        'terms.views.set_terms_publication',
        side_effect=TermsVersionNotFoundError('gone'),
    )
    def test_missing_version_shows_message_without_audit(self, mock_set):
        self.login_admin()
        self._create_history()

        response = self.client.post(
            reverse('terms:terms-set-current', args=['tc-historica', 'es']), follow=True
        )

        self.assertRedirects(response, reverse('terms:terms-list'), fetch_redirect_response=False)
        self.assertContains(response, 'ya no existe en la API')
        self.assertFalse(
            AuditLog.objects.filter(action='terms_publication_changed').exists()
        )

    def test_specialist_is_denied(self):
        self.login_specialist()

        response = self.client.post(
            reverse('terms:terms-set-current', args=['tc-historica', 'es'])
        )

        self.assertEqual(response.status_code, 403)


class TermsUnpublishViewTests(TermsViewsTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

    def _create_single(self):
        TermsVersion.objects.create(
            version_id='tc-unica',
            language='es',
            title='Unica vigente',
            content='Contenido',
            content_hash='h-unica',
            published=True,
        )

    @patch(
        'terms.views.set_terms_publication',
        return_value={'version_id': 'tc-unica', 'language': 'es', 'published': False},
    )
    def test_admin_unpublishes_and_audits(self, mock_set):
        self.login_admin()
        self._create_single()

        response = self.client.post(
            reverse('terms:terms-set-current', args=['tc-unica', 'es']),
            {'published': 'false'},
        )

        self.assertRedirects(response, reverse('terms:terms-list'), fetch_redirect_response=False)
        mock_set.assert_called_once_with('id-token', 'tc-unica', 'es', published=False)
        self.assertFalse(
            TermsVersion.objects.get(version_id='tc-unica').published
        )
        logged = AuditLog.objects.get(
            action='terms_publication_changed',
            result=AuditLog.Result.SUCCESS,
        )
        self.assertEqual(logged.metadata['published'], False)

    @patch(
        'terms.views.set_terms_publication',
        side_effect=TermsPublicationForbiddenError('blocked'),
    )
    def test_unpublish_protection_shows_friendly_message(self, mock_set):
        self.login_admin()
        self._create_single()

        response = self.client.post(
            reverse('terms:terms-set-current', args=['tc-unica', 'es']),
            {'published': 'false'}, follow=True
        )

        self.assertRedirects(response, reverse('terms:terms-list'), fetch_redirect_response=False)
        self.assertContains(response, 'debe existir siempre una version vigente')
        self.assertTrue(
            TermsVersion.objects.get(version_id='tc-unica').published
        )
        self.assertFalse(
            AuditLog.objects.filter(action='terms_publication_changed').exists()
        )
