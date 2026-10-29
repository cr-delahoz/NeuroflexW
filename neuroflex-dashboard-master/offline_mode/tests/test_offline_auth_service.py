from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from offline_mode.models import OfflineAccessGrant
from offline_mode.services.offline_auth_service import capture_credentials_on_online_login


User = get_user_model()


class CaptureTests(TestCase):
    def test_capture_sets_usable_local_password_and_grant(self):
        user = User.objects.create_user(username="esp", role="SPECIALIST")
        capture_credentials_on_online_login(user, "S3gura!2026")
        user.refresh_from_db()
        self.assertTrue(user.check_password("S3gura!2026"))
        grant = OfflineAccessGrant.objects.get(user=user)
        self.assertGreater(grant.offline_expires_at, grant.last_online_validation)

    def test_capture_resets_failed_attempts_and_lockout(self):
        user = User.objects.create_user(username="esp3", role="SPECIALIST")
        capture_credentials_on_online_login(user, "Clave1!")
        grant = OfflineAccessGrant.objects.get(user=user)
        grant.failed_attempts = 3
        grant.locked_until = timezone.now() + timedelta(minutes=5)
        grant.save()

        capture_credentials_on_online_login(user, "ClaveNueva2!")

        grant.refresh_from_db()
        user.refresh_from_db()
        self.assertEqual(grant.failed_attempts, 0)
        self.assertIsNone(grant.locked_until)
        self.assertTrue(user.check_password("ClaveNueva2!"))
