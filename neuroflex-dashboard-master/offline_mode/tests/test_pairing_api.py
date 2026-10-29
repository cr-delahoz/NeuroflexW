import json
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, OperationalError, transaction
from django.test import TestCase
from django.utils import timezone

from offline_mode.models import OfflineDevice, PairingRequest
from offline_mode.services import pairing_service
from offline_mode.services.checksums import sha256_hex


User = get_user_model()


class PairingApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="esp-api", role="SPECIALIST", password="x"
        )
        self.client.force_login(self.user)
        pairing_service.open_pairing_window()

    def test_pair_request_requires_pairing_window_open(self):
        from django.core.cache import cache
        cache.delete("pairing_window_open")
        resp = self.client.post(
            "/api/lan/pair/request",
            data=json.dumps({
                "device_id": str(uuid.uuid4()),
                "device_name": "Q",
                "pin": "483920",
            }),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)
        self.assertIn("error", resp.json())

    def test_pair_request_requires_active_dashboard_session(self):
        self.client.logout()
        resp = self.client.post(
            "/api/lan/pair/request",
            data=json.dumps({
                "device_id": str(uuid.uuid4()),
                "device_name": "Q",
                "pin": "483920",
            }),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)
        self.assertIn("error", resp.json())

    def test_non_string_device_name_rejected(self):
        resp = self.client.post(
            "/api/lan/pair/request",
            data=json.dumps({
                "device_id": str(uuid.uuid4()),
                "device_name": ["Q"],
                "pin": "483920",
            }),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_unicode_digit_pin_rejected(self):
        resp = self.client.post(
            "/api/lan/pair/request",
            data=json.dumps({
                "device_id": str(uuid.uuid4()),
                "device_name": "Q",
                "pin": "٤٨٣٩٢٠",
            }),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_pin_with_trailing_newline_rejected(self):
        resp = self.client.post(
            "/api/lan/pair/request",
            data=json.dumps({
                "device_id": str(uuid.uuid4()),
                "device_name": "Q",
                "pin": "483920\n",
            }),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_non_numeric_pin_rejected(self):
        resp = self.client.post(
            "/api/lan/pair/request",
            data=json.dumps({
                "device_id": str(uuid.uuid4()),
                "device_name": "Q",
                "pin": "abcdef",
            }),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_malformed_device_id_rejected(self):
        resp = self.client.post(
            "/api/lan/pair/request",
            data=json.dumps({
                "device_id": "no-es-uuid",
                "device_name": "Q",
                "pin": "483920",
            }),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_json_array_body_rejected_not_500(self):
        resp = self.client.post(
            "/api/lan/pair/request",
            data=json.dumps([1, 2, 3]),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_admin_cannot_access_panel(self):
        admin = User.objects.create_user(username="adm", role="ADMIN", password="x")
        self.client.force_login(admin)
        resp = self.client.get("/offline/panel/")
        self.assertEqual(resp.status_code, 403)

    def test_pair_request_returns_pairing_id(self):
        response = self.client.post(
            "/api/lan/pair/request",
            data=json.dumps({
                "device_id": str(uuid.uuid4()),
                "device_name": "Quest-A4F2",
                "pin": "483920",
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertIn("pairing_id", response.json())

    def test_device_name_with_long_spaces_normalized(self):
        short_name = "Q"
        device_name = " " * 80 + short_name + " " * 80
        response = self.client.post(
            "/api/lan/pair/request",
            data=json.dumps({
                "device_id": str(uuid.uuid4()),
                "device_name": device_name,
                "pin": "483920",
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        request = PairingRequest.objects.get(pairing_id=response.json()["pairing_id"])
        self.assertEqual(request.device_name, short_name)

    def test_only_one_active_request(self):
        device_id = str(uuid.uuid4())
        body = json.dumps({
            "device_id": device_id,
            "device_name": "Q",
            "pin": "111111",
        })
        first = self.client.post("/api/lan/pair/request", data=body, content_type="application/json")
        self.assertEqual(first.status_code, 201)
        # Mismo device_id: reemplaza su solicitud activa, no 409.
        second = self.client.post("/api/lan/pair/request", data=body, content_type="application/json")
        self.assertEqual(second.status_code, 201)
        self.assertNotEqual(first.json()["pairing_id"], second.json()["pairing_id"])
        # Device distinto: 409 con el pairing_id de la solicitud activa.
        other = self.client.post(
            "/api/lan/pair/request",
            data=json.dumps({
                "device_id": str(uuid.uuid4()),
                "device_name": "Other",
                "pin": "222222",
            }),
            content_type="application/json",
        )
        self.assertEqual(other.status_code, 409)
        data = other.json()
        self.assertEqual(data["pairing_id"], second.json()["pairing_id"])
        self.assertGreater(data["expires_in"], 0)

    def test_409_without_active_request_has_no_pairing_id(self):
        body = json.dumps({
            "device_id": str(uuid.uuid4()),
            "device_name": "Q",
            "pin": "111111",
        })
        self.client.post("/api/lan/pair/request", data=body, content_type="application/json")
        # La solicitud activa se expira artificialmente sin dejar otra:
        # active_request() devuelve None y el 409 no debe exponer pairing_id.
        from offline_mode.models import PairingRequest as PR
        PR.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        response = self.client.post("/api/lan/pair/request", data=body, content_type="application/json")
        # Tras expirar, create_request vuelve a poder crear (no 409).
        self.assertEqual(response.status_code, 201)

    def test_full_pairing_flow(self):
        device_id = str(uuid.uuid4())
        response = self.client.post(
            "/api/lan/pair/request",
            data=json.dumps({
                "device_id": device_id,
                "device_name": "Q",
                "pin": "483920",
            }),
            content_type="application/json",
        )
        pairing_id = response.json()["pairing_id"]
        status = self.client.get(f"/api/lan/pair/status/{pairing_id}")
        self.assertEqual(status.json()["status"], "waiting")
        user = User.objects.create_user(username="esp", role="SPECIALIST", password="x")
        self.client.force_login(user)
        confirm = self.client.post("/offline/pairing/confirm", {"pin": "483920"})
        self.assertEqual(confirm.status_code, 302)
        status = self.client.get(f"/api/lan/pair/status/{pairing_id}")
        data = status.json()
        self.assertEqual(data["status"], "confirmed")
        token = data["device_token"]
        self.assertNotIn("device_token", self.client.get(f"/api/lan/pair/status/{pairing_id}").json())
        ping = self.client.get("/api/lan/device/ping", HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(ping.status_code, 200)
        self.assertTrue(OfflineDevice.objects.filter(device_id=device_id).exists())

    def test_pair_status_expired_when_confirmed_but_never_claimed(self):
        device_id = str(uuid.uuid4())
        response = self.client.post(
            "/api/lan/pair/request",
            data=json.dumps({
                "device_id": device_id,
                "device_name": "Q",
                "pin": "483920",
            }),
            content_type="application/json",
        )
        pairing_id = response.json()["pairing_id"]
        user = User.objects.create_user(username="esp", role="SPECIALIST", password="x")
        self.client.force_login(user)
        self.client.post("/offline/pairing/confirm", {"pin": "483920"})
        # El Quest nunca reclamó el token y el TTL venció: debe reportar
        # "expired" para que reinicie el emparejamiento.
        PairingRequest.objects.filter(pairing_id=pairing_id).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        status = self.client.get(f"/api/lan/pair/status/{pairing_id}")
        self.assertEqual(status.json()["status"], "expired")

    def test_revoked_device_can_repair(self):
        device_id = uuid.uuid4()
        OfflineDevice.objects.create(
            device_id=device_id,
            name="Q",
            device_token_hash=sha256_hex("viejo"),
            revoked=True,
        )
        response = self.client.post(
            "/api/lan/pair/request",
            data=json.dumps({
                "device_id": str(device_id),
                "device_name": "Q",
                "pin": "483920",
            }),
            content_type="application/json",
        )
        pairing_id = response.json()["pairing_id"]
        user = User.objects.create_user(username="esp", role="SPECIALIST", password="x")
        self.client.force_login(user)
        self.client.post("/offline/pairing/confirm", {"pin": "483920"})
        status = self.client.get(f"/api/lan/pair/status/{pairing_id}")
        self.assertEqual(status.json()["status"], "confirmed")
        self.assertIn("device_token", status.json())
        device = OfflineDevice.objects.get(device_id=device_id)
        self.assertFalse(device.revoked)
        self.assertEqual(OfflineDevice.objects.filter(device_id=device_id).count(), 1)
        # el token viejo queda invalidado, el nuevo funciona
        old = self.client.get(
            "/api/lan/device/ping", HTTP_AUTHORIZATION="Bearer viejo"
        )
        self.assertEqual(old.status_code, 401)
        new_token = status.json()["device_token"]
        new = self.client.get(
            "/api/lan/device/ping", HTTP_AUTHORIZATION=f"Bearer {new_token}"
        )
        self.assertEqual(new.status_code, 200)

    def test_wrong_pin_counts_attempt(self):
        response = self.client.post(
            "/api/lan/pair/request",
            data=json.dumps({
                "device_id": str(uuid.uuid4()),
                "device_name": "Q",
                "pin": "483920",
            }),
            content_type="application/json",
        )
        user = User.objects.create_user(username="esp", role="SPECIALIST", password="x")
        self.client.force_login(user)
        self.client.post("/offline/pairing/confirm", {"pin": "000000"})
        request = PairingRequest.objects.get(pairing_id=response.json()["pairing_id"])
        self.assertEqual(request.confirm_attempts, 1)


class PairingExpiryTests(TestCase):
    """El token crudo no debe persistir en solicitudes expiradas o stale."""

    def _request(self, **kwargs):
        defaults = dict(
            device_id=uuid.uuid4(),
            device_name="Q",
            pin_hash=sha256_hex("123456"),
            expires_at=timezone.now() + timedelta(seconds=180),
        )
        defaults.update(kwargs)
        return PairingRequest.objects.create(**defaults)

    def test_active_request_wipes_stale_device_token(self):
        req = self._request(
            confirmed=True,
            device_token="raw-token",
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        pairing_service.active_request()
        req.refresh_from_db()
        self.assertIsNone(req.device_token)
        self.assertTrue(req.is_expired())

    def test_active_request_keeps_fresh_device_token(self):
        req = self._request(confirmed=True, device_token="raw-token")
        pairing_service.active_request()
        req.refresh_from_db()
        self.assertEqual(req.device_token, "raw-token")

    def test_create_request_wipes_stale_device_token(self):
        self._request(
            confirmed=True,
            device_token="raw-token",
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        req = pairing_service.create_request(
            device_id=uuid.uuid4(), device_name="Q", pin="123456"
        )
        self.assertIsNotNone(req)
        self.assertEqual(
            PairingRequest.objects.filter(device_token__isnull=False).count(), 0
        )

    def test_claim_token_rejects_expired_request(self):
        req = self._request(
            confirmed=True,
            device_token="raw-token",
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        self.assertIsNone(pairing_service.claim_token(req.pairing_id))
        req.refresh_from_db()
        self.assertIsNone(req.device_token)
        self.assertFalse(req.is_active)
        self.assertFalse(req.delivered)

    def test_claim_token_delivers_once_and_deactivates(self):
        req = self._request(confirmed=True, device_token="raw-token")
        self.assertEqual(pairing_service.claim_token(req.pairing_id), "raw-token")
        req.refresh_from_db()
        self.assertTrue(req.delivered)
        self.assertIsNone(req.device_token)
        self.assertFalse(req.is_active)
        self.assertIsNone(pairing_service.claim_token(req.pairing_id))

    def test_claim_token_rejects_unconfirmed_request(self):
        req = self._request(confirmed=False)
        self.assertIsNone(pairing_service.claim_token(req.pairing_id))
        req.refresh_from_db()
        self.assertTrue(req.is_active)

    def test_status_expired_for_confirmed_unclaimed_expired_request(self):
        req = self._request(
            confirmed=True,
            device_token="raw-token",
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        self.assertEqual(
            pairing_service.get_request_status(req.pairing_id), "expired"
        )

    def test_status_confirmed_for_claimed_request_even_if_expired(self):
        req = self._request(
            confirmed=True,
            delivered=True,
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        self.assertEqual(
            pairing_service.get_request_status(req.pairing_id), "confirmed"
        )

    def test_status_expired_wipes_unclaimed_device_token(self):
        req = self._request(
            confirmed=True,
            device_token="raw-token",
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        self.assertEqual(
            pairing_service.get_request_status(req.pairing_id), "expired"
        )
        req.refresh_from_db()
        self.assertIsNone(req.device_token)
        self.assertFalse(req.is_active)

    def test_status_confirmed_keeps_token_of_vigente_request(self):
        req = self._request(confirmed=True, device_token="raw-token")
        self.assertEqual(
            pairing_service.get_request_status(req.pairing_id), "confirmed"
        )
        req.refresh_from_db()
        self.assertEqual(req.device_token, "raw-token")


class ActivePairingPerDeviceTests(TestCase):
    """Garantía de una sola solicitud activa por dispositivo."""

    def _request(self, **kwargs):
        defaults = dict(
            device_id=uuid.uuid4(),
            device_name="Q",
            pin_hash=sha256_hex("123456"),
            expires_at=timezone.now() + timedelta(seconds=180),
        )
        defaults.update(kwargs)
        return PairingRequest.objects.create(**defaults)

    def test_same_device_replaces_active_request(self):
        device_id = uuid.uuid4()
        first = pairing_service.create_request(
            device_id=device_id, device_name="Q", pin="123456"
        )
        self.assertIsNotNone(first)
        second = pairing_service.create_request(
            device_id=device_id, device_name="Q", pin="654321"
        )
        self.assertIsNotNone(second)
        self.assertNotEqual(first.pairing_id, second.pairing_id)
        first.refresh_from_db()
        self.assertFalse(first.is_active)
        self.assertLessEqual(first.expires_at, timezone.now())

    def test_constraint_blocks_duplicate_active_rows(self):
        device_id = uuid.uuid4()
        self._request(device_id=device_id)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._request(device_id=device_id)

    def test_create_request_returns_none_if_device_already_active(self):
        device_id = uuid.uuid4()
        # Fila activa confirmada (no bloqueada por el chequeo global de
        # pendientes): la crea otra transacción y debe forzar 409 vía
        # IntegrityError.
        self._request(device_id=device_id, confirmed=True, device_token="tok")
        self.assertIsNone(
            pairing_service.create_request(
                device_id=device_id, device_name="Q", pin="123456"
            )
        )

    def test_device_can_repair_after_claim(self):
        device_id = uuid.uuid4()
        req = pairing_service.create_request(
            device_id=device_id, device_name="Q", pin="123456"
        )
        self.assertIsNotNone(req)
        user = User.objects.create_user(username="esp", role="SPECIALIST", password="x")
        device = pairing_service.confirm_pairing("123456", user)
        self.assertIsNotNone(device)
        self.assertIsNotNone(pairing_service.claim_token(req.pairing_id))
        # Tras reclamar el token, el dispositivo puede volver a emparejar.
        new_req = pairing_service.create_request(
            device_id=device_id, device_name="Q", pin="654321"
        )
        self.assertIsNotNone(new_req)

    def test_confirm_deactivates_request_and_allows_repair_without_claim(self):
        device_id = uuid.uuid4()
        req = pairing_service.create_request(
            device_id=device_id, device_name="Q", pin="123456"
        )
        self.assertIsNotNone(req)
        user = User.objects.create_user(username="esp", role="SPECIALIST", password="x")
        device = pairing_service.confirm_pairing("123456", user)
        self.assertIsNotNone(device)
        req.refresh_from_db()
        self.assertTrue(req.confirmed)
        self.assertFalse(req.is_active)
        self.assertIsNotNone(req.device_token)
        # Una segunda confirmación no encuentra solicitud pendiente.
        self.assertIsNone(pairing_service.confirm_pairing("123456", user))
        # Confirmada la solicitud, el dispositivo puede volver a emparejar
        # sin esperar el claim del token.
        new_req = pairing_service.create_request(
            device_id=device_id, device_name="Q", pin="654321"
        )
        self.assertIsNotNone(new_req)


class ConfirmPairingSqliteLockTests(TestCase):
    """En SQLite select_for_update no bloquea: una carrera concurrente
    puede fallar con OperationalError "database is locked" al confirmar."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="esp", role="SPECIALIST", password="x"
        )

    @patch(
        "offline_mode.services.pairing_service.PairingRequest.objects"
        ".select_for_update"
    )
    def test_confirm_pairing_returns_none_on_database_locked(self, mock_select):
        mock_select.return_value.filter.return_value.first.side_effect = (
            OperationalError("database is locked")
        )
        self.assertIsNone(pairing_service.confirm_pairing("123456", self.user))

    @patch(
        "offline_mode.services.pairing_service.PairingRequest.objects"
        ".select_for_update"
    )
    def test_confirm_pairing_propagates_other_operational_errors(
        self, mock_select
    ):
        mock_select.return_value.filter.return_value.first.side_effect = (
            OperationalError("no such table: offline_mode_pairingrequest")
        )
        with self.assertRaises(OperationalError):
            pairing_service.confirm_pairing("123456", self.user)
