import base64
import json
import time
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, Client

from offline_mode.models import OfflineDevice, OfflineSession
from offline_mode.services.sync_service import SyncService, UserInactiveError


User = get_user_model()


def _make_id_token(expires_in_seconds=3600):
    """JWT de prueba con ``exp`` futuro (o vencido si el offset es negativo)."""
    payload = base64.urlsafe_b64encode(
        json.dumps({"exp": int(time.time()) + expires_in_seconds}).encode()
    ).decode().rstrip("=")
    return f"header.{payload}.signature"


class SyncNowViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="esp", role="SPECIALIST", password="test"
        )
        self.client.force_login(self.user)
        self.device = OfflineDevice.objects.create(
            device_id="11111111-1111-1111-1111-111111111111",
            name="Quest",
            device_token_hash="a" * 64,
        )

    def _set_id_token(self, token):
        session = self.client.session
        session["cognito_id_token"] = token
        session.save()

    @patch("offline_mode.views.is_online", return_value=False)
    def test_sync_now_returns_503_when_offline(self, _):
        resp = self.client.post("/offline/sync/")
        self.assertEqual(resp.status_code, 503)
        data = resp.json()
        self.assertFalse(data["ok"])
        self.assertEqual(data["results"], [])
        self.assertFalse(data["user_inactive"])

    def test_admin_cannot_sync(self):
        admin = User.objects.create_user(username="adm", role="ADMIN", password="x")
        self.client.force_login(admin)
        resp = self.client.post("/offline/sync/")
        self.assertEqual(resp.status_code, 403)

    @patch("offline_mode.views.is_online", return_value=True)
    @patch.object(
        SyncService,
        "sync_all",
        return_value=[{"session_id": "s1", "ok": True, "error": None}],
    )
    def test_sync_now_returns_results(self, *_):
        self._set_id_token(_make_id_token())
        resp = self.client.post("/offline/sync/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(
            data["results"], [{"session_id": "s1", "ok": True, "error": None}]
        )
        self.assertFalse(data["user_inactive"])

    @patch("offline_mode.views.is_online", return_value=True)
    @patch.object(
        SyncService, "sync_all", side_effect=UserInactiveError("Usuario inactivo en AWS")
    )
    def test_sync_now_returns_403_user_inactive(self, *_):
        self._set_id_token(_make_id_token())
        resp = self.client.post("/offline/sync/")
        self.assertEqual(resp.status_code, 403)
        data = resp.json()
        self.assertFalse(data["ok"])
        self.assertEqual(data["results"], [])
        self.assertTrue(data["user_inactive"])
        self.assertIn("inactivo", data["error"].lower())

    @patch("offline_mode.views.is_online", return_value=True)
    @patch.object(SyncService, "sync_all")
    def test_sync_now_returns_403_reauth_required_when_token_missing(
        self, mock_sync, _
    ):
        resp = self.client.post("/offline/sync/")
        self.assertEqual(resp.status_code, 403)
        data = resp.json()
        self.assertFalse(data["ok"])
        self.assertEqual(data["results"], [])
        self.assertFalse(data["user_inactive"])
        self.assertTrue(data["reauth_required"])
        self.assertIn("online", data["error"].lower())
        mock_sync.assert_not_called()

    @patch("offline_mode.views.is_online", return_value=True)
    @patch.object(SyncService, "sync_all")
    def test_sync_now_returns_403_reauth_required_when_token_expired(
        self, mock_sync, _
    ):
        self._set_id_token(_make_id_token(expires_in_seconds=-60))
        resp = self.client.post("/offline/sync/")
        self.assertEqual(resp.status_code, 403)
        data = resp.json()
        self.assertFalse(data["ok"])
        self.assertTrue(data["reauth_required"])
        self.assertFalse(data["user_inactive"])
        mock_sync.assert_not_called()
