import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, RequestFactory
from django.utils import timezone

from offline_mode.context_processors import sync_banner
from offline_mode.models import OfflineDevice, OfflineSession


User = get_user_model()


class SyncBannerTests(TestCase):
    def test_anonymous_gets_empty_context(self):
        request = RequestFactory().get("/")
        request.user = type("Anon", (), {"is_authenticated": False})()
        self.assertEqual(sync_banner(request), {})

    def test_admin_gets_empty_context(self):
        request = RequestFactory().get("/")
        request.user = User.objects.create_user(username="adm", role="ADMIN")
        request.session = {}
        self.assertEqual(sync_banner(request), {})

    @patch("offline_mode.context_processors.is_online", return_value=True)
    def test_banner_shows_pending_when_online_and_sessions(self, _):
        request = RequestFactory().get("/")
        request.user = User.objects.create_user(username="esp", role="SPECIALIST")
        request.session = {}
        OfflineSession.objects.create(
            device=OfflineDevice.objects.create(
                device_id=uuid.uuid4(), name="Q", device_token_hash="a" * 64,
                paired_by=request.user,
            ),
            status="COMPLETED",
            terms_version_id="0.0.1",
            terms_content_hash="a" * 64,
            terms_accepted_at=timezone.now(),
            acceptance_token=uuid.uuid4(),
            metrics_token_hash="b" * 64,
        )
        ctx = sync_banner(request)
        self.assertEqual(ctx["offline_sync_banner"]["pending_count"], 1)

    @patch("offline_mode.context_processors.is_online", return_value=True)
    def test_banner_does_not_count_other_users_sessions(self, _):
        # El contador es por usuario: las pendientes de otro especialista
        # no aparecen en mi banner.
        request = RequestFactory().get("/")
        request.user = User.objects.create_user(username="esp", role="SPECIALIST")
        request.session = {}
        other = User.objects.create_user(username="otro", role="SPECIALIST")
        OfflineSession.objects.create(
            device=OfflineDevice.objects.create(
                device_id=uuid.uuid4(), name="Q", device_token_hash="a" * 64,
                paired_by=other,
            ),
            status="COMPLETED",
            terms_version_id="0.0.1",
            terms_content_hash="a" * 64,
            terms_accepted_at=timezone.now(),
            acceptance_token=uuid.uuid4(),
            metrics_token_hash="b" * 64,
        )
        ctx = sync_banner(request)
        self.assertEqual(ctx["offline_sync_banner"]["pending_count"], 0)

    @patch("offline_mode.context_processors.is_online", return_value=True)
    def test_counts_completed_sessions(self, _):
        request = RequestFactory().get("/")
        request.user = User.objects.create_user(username="esp", role="SPECIALIST")
        request.session = {}
        ctx = sync_banner(request)
        self.assertTrue(ctx["offline_sync_banner"]["is_online"])
        self.assertEqual(ctx["offline_sync_banner"]["pending_count"], 0)

    def test_offline_banner_context(self):
        request = RequestFactory().get("/")
        request.user = User.objects.create_user(username="esp", role="SPECIALIST")
        request.session = {}
        with patch("offline_mode.context_processors.is_online", return_value=False):
            ctx = sync_banner(request)
        self.assertFalse(ctx["offline_sync_banner"]["is_online"])
        self.assertEqual(ctx["offline_sync_banner"]["pending_count"], 0)
