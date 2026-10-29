import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from offline_mode.models import (
    OfflineAccessGrant,
    OfflineDevice,
    OfflineSession,
    PairingRequest,
)
from offline_mode.services.checksums import sha256_hex
from offline_mode.services.offline_session_ui_service import list_visible_sessions

User = get_user_model()


class OfflineDeviceTests(TestCase):
    def test_create_device(self):
        user = User.objects.create_user(username="esp1", role="SPECIALIST")
        dev = OfflineDevice.objects.create(
            device_id=uuid.uuid4(),
            name="Quest-A4F2",
            device_token_hash=sha256_hex("tok"),
            paired_by=user,
        )
        self.assertFalse(dev.revoked)
        self.assertIsNotNone(dev.paired_at)


class PairingRequestTests(TestCase):
    def test_is_expired(self):
        req = PairingRequest.objects.create(
            device_id=uuid.uuid4(),
            device_name="Q",
            pin_hash=sha256_hex("123456"),
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        self.assertTrue(req.is_expired())


class OfflineSessionTests(TestCase):
    def _device(self, paired_by=None):
        return OfflineDevice.objects.create(
            device_id=uuid.uuid4(),
            name="Q",
            device_token_hash=sha256_hex("t"),
            paired_by=paired_by,
        )

    def test_default_status_is_pending(self):
        session = OfflineSession.objects.create(
            device=self._device(),
            terms_version_id="0.0.1",
            terms_content_hash="h" * 64,
            terms_accepted_at=timezone.now(),
            acceptance_token=uuid.uuid4(),
            metrics_token_hash=sha256_hex("m"),
        )
        self.assertEqual(session.status, OfflineSession.Status.PENDING)

    def test_status_choices_exact(self):
        self.assertEqual(
            [choice[0] for choice in OfflineSession.Status.choices],
            ["PENDING", "CONFIRMED", "COMPLETED", "SYNCING", "SYNCED", "ERROR"],
        )

    def test_list_visible_sessions_scopes_by_owner_excludes_synced_and_orders_newest_first(self):
        owner = User.objects.create_user(username="dueno", role="SPECIALIST")
        other = User.objects.create_user(username="otro", role="SPECIALIST")
        device = self._device(paired_by=owner)
        common = {
            "terms_version_id": "0.0.1",
            "terms_content_hash": "h" * 64,
            "terms_accepted_at": timezone.now(),
            "acceptance_token": uuid.uuid4(),
            "metrics_token_hash": sha256_hex("m"),
        }
        older = OfflineSession.objects.create(device=device, **common)
        newer = OfflineSession.objects.create(
            device=device, **{**common, "acceptance_token": uuid.uuid4()}
        )
        synced = OfflineSession.objects.create(
            device=device,
            **{
                **common,
                "acceptance_token": uuid.uuid4(),
                "status": OfflineSession.Status.SYNCED,
            },
        )
        foreign = OfflineSession.objects.create(
            device=self._device(paired_by=other),
            **{**common, "acceptance_token": uuid.uuid4()},
        )
        OfflineSession.objects.filter(session_id=older.session_id).update(
            created_at=timezone.now() - timedelta(minutes=1)
        )

        visible = list(list_visible_sessions(owner))
        self.assertEqual(visible, [newer, older])
        self.assertNotIn(synced, visible)
        self.assertNotIn(foreign, visible)


class OfflineAccessGrantTests(TestCase):
    def test_grant_defaults(self):
        user = User.objects.create_user(username="esp2", role="SPECIALIST")
        grant = OfflineAccessGrant.objects.create(
            user=user,
            offline_expires_at=timezone.now() + timedelta(days=15),
        )
        self.assertEqual(grant.failed_attempts, 0)
        self.assertIsNone(grant.locked_until)
