from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from offline_mode.forms import OfflineAuthenticationForm
from offline_mode.services.offline_auth_service import capture_credentials_on_online_login


User = get_user_model()


def _make_specialist(username="esp", password="S3gura!2026"):
    user = User.objects.create_user(username=username, role="SPECIALIST")
    capture_credentials_on_online_login(user, password)
    return user


class OfflineLoginFormTests(TestCase):
    def test_offline_login_view_sets_session_flag_and_redirects(self):
        _make_specialist()
        with patch("accounts.views.is_online", return_value=False):
            resp = self.client.post(
                "/login/",
                {"username": "esp", "password": "S3gura!2026"},
            )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/offline/", resp.url)
        self.assertTrue(self.client.session.get("offline_mode"))

    def test_offline_login_preserves_existing_cognito_token(self):
        """Un token AWS presente en la sesión sobrevive al login offline.

        Contrato de la vista: el login offline nunca descarta un
        ``cognito_id_token`` vigente — sin él, sincronizar exigiría
        re-autenticar online aunque el token aún no expire.
        """
        _make_specialist()
        session = self.client.session
        session["cognito_id_token"] = "tok"
        session["cognito_id_token_expires_at"] = 1893456000
        session.save()

        with patch("accounts.views.is_online", return_value=False):
            resp = self.client.post(
                "/login/",
                {"username": "esp", "password": "S3gura!2026"},
            )

        self.assertEqual(resp.status_code, 302)
        self.assertIn("/offline/", resp.url)
        self.assertTrue(self.client.session.get("offline_mode"))
        self.assertEqual(self.client.session.get("cognito_id_token"), "tok")
        self.assertEqual(
            self.client.session.get("cognito_id_token_expires_at"), 1893456000
        )

    def test_valid_offline_login(self):
        _make_specialist()
        form = OfflineAuthenticationForm(data={"username": "esp", "password": "S3gura!2026"})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.user_cache.username, "esp")

    def test_wrong_password_increments_attempts(self):
        user = _make_specialist()
        form = OfflineAuthenticationForm(data={"username": "esp", "password": "mala"})
        self.assertFalse(form.is_valid())
        user.offlineaccessgrant.refresh_from_db()
        self.assertEqual(user.offlineaccessgrant.failed_attempts, 1)

    def test_failed_attempts_are_audited_with_reason(self):
        from audit.models import AuditLog

        _make_specialist()
        OfflineAuthenticationForm(data={"username": "esp", "password": "mala"}).is_valid()
        self.assertTrue(AuditLog.objects.filter(
            action="OFFLINE_LOGIN_FAILURE", metadata__reason="bad_password").exists())

    def test_lockout_after_max_attempts(self):
        user = _make_specialist()
        for _ in range(5):
            OfflineAuthenticationForm(data={"username": "esp", "password": "mala"}).is_valid()
        user.offlineaccessgrant.refresh_from_db()
        self.assertIsNotNone(user.offlineaccessgrant.locked_until)
        form = OfflineAuthenticationForm(data={"username": "esp", "password": "S3gura!2026"})
        self.assertFalse(form.is_valid())

    def test_admin_rejected_with_internet_notice(self):
        admin = User.objects.create_user(username="adm", role="ADMIN")
        capture_credentials_on_online_login(admin, "S3gura!2026")
        form = OfflineAuthenticationForm(data={"username": "adm", "password": "S3gura!2026"})
        self.assertFalse(form.is_valid())
        self.assertIn("internet", str(form.errors).lower())

    def test_admin_attempt_is_audited(self):
        from audit.models import AuditLog

        admin = User.objects.create_user(username="adm2", role="ADMIN")
        capture_credentials_on_online_login(admin, "S3gura!2026")
        OfflineAuthenticationForm(data={"username": "adm2", "password": "S3gura!2026"}).is_valid()
        self.assertTrue(AuditLog.objects.filter(
            action="OFFLINE_LOGIN_FAILURE", metadata__reason="admin_role").exists())

    def test_expired_grant_rejected(self):
        user = _make_specialist()
        grant = user.offlineaccessgrant
        grant.offline_expires_at = timezone.now() - timedelta(days=1)
        grant.save()
        form = OfflineAuthenticationForm(data={"username": "esp", "password": "S3gura!2026"})
        self.assertFalse(form.is_valid())

    def test_grant_expiring_exactly_now_is_rejected(self):
        user = _make_specialist()
        fixed_now = timezone.now()
        grant = user.offlineaccessgrant
        grant.offline_expires_at = fixed_now
        grant.save()
        with patch("offline_mode.forms.timezone.now", return_value=fixed_now):
            form = OfflineAuthenticationForm(
                data={"username": "esp", "password": "S3gura!2026"}
            )
            self.assertFalse(form.is_valid())

    def test_inactive_user_rejected_and_audited(self):
        from audit.models import AuditLog

        user = _make_specialist()
        user.is_active = False
        user.save()
        form = OfflineAuthenticationForm(data={"username": "esp", "password": "S3gura!2026"})
        self.assertFalse(form.is_valid())
        self.assertTrue(AuditLog.objects.filter(
            action="OFFLINE_LOGIN_FAILURE", metadata__reason="inactive").exists())

    def test_missing_credentials_are_audited(self):
        from audit.models import AuditLog

        form = OfflineAuthenticationForm(data={"username": "esp", "password": ""})
        self.assertFalse(form.is_valid())
        self.assertTrue(AuditLog.objects.filter(
            action="OFFLINE_LOGIN_FAILURE",
            resource_id="esp",
            metadata__reason="missing_credentials",
        ).exists())

    def test_unknown_user_is_audited(self):
        from audit.models import AuditLog

        OfflineAuthenticationForm(data={"username": "noexiste", "password": "x"}).is_valid()
        self.assertTrue(AuditLog.objects.filter(
            action="OFFLINE_LOGIN_FAILURE", metadata__reason="user_not_found").exists())

    def test_locked_account_is_audited(self):
        from audit.models import AuditLog

        user = _make_specialist()
        grant = user.offlineaccessgrant
        grant.locked_until = timezone.now() + timedelta(minutes=10)
        grant.save()
        OfflineAuthenticationForm(data={"username": "esp", "password": "S3gura!2026"}).is_valid()
        self.assertTrue(AuditLog.objects.filter(
            action="OFFLINE_LOGIN_FAILURE", metadata__reason="locked").exists())

    def test_expired_grant_is_audited(self):
        from audit.models import AuditLog

        user = _make_specialist()
        grant = user.offlineaccessgrant
        grant.offline_expires_at = timezone.now() - timedelta(days=1)
        grant.save()
        OfflineAuthenticationForm(data={"username": "esp", "password": "S3gura!2026"}).is_valid()
        self.assertTrue(AuditLog.objects.filter(
            action="OFFLINE_LOGIN_FAILURE", metadata__reason="grant_expired").exists())

    def test_user_without_grant_rejected_cleanly(self):
        """Un especialista sin OfflineAccessGrant recibe ValidationError, no una excepción."""
        from audit.models import AuditLog

        user = User.objects.create_user(
            username="singrant", role="SPECIALIST", password="S3gura!2026"
        )
        self.assertFalse(hasattr(user, "offlineaccessgrant"))
        form = OfflineAuthenticationForm(
            data={"username": "singrant", "password": "S3gura!2026"}
        )
        self.assertFalse(form.is_valid())
        self.assertIn("expiró", str(form.errors))
        self.assertTrue(AuditLog.objects.filter(
            action="OFFLINE_LOGIN_FAILURE", metadata__reason="grant_expired").exists())
