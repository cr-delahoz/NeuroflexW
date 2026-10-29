import re
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from offline_mode.models import OfflineDevice, OfflineSession
from offline_mode.services import offline_session_ui_service
from offline_mode.services.checksums import sha256_hex


User = get_user_model()


def _session(status="PENDING", owner=None):
    device = OfflineDevice.objects.create(
        device_id=uuid.uuid4(), name="Q", device_token_hash=sha256_hex("t"),
        paired_by=owner,
    )
    return OfflineSession.objects.create(
        device=device,
        status=status,
        terms_version_id="0.0.1",
        terms_content_hash="a" * 64,
        terms_accepted_at=timezone.now(),
        acceptance_token=uuid.uuid4(),
        metrics_token_hash=sha256_hex("m"),
        metrics={"Precision": 0.9} if status == "COMPLETED" else None,
    )


class CountPendingSessionsTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="esp", role="SPECIALIST")

    def test_counts_only_completed_and_error_for_device_owner(self):
        for status in ("PENDING", "CONFIRMED", "COMPLETED", "ERROR", "SYNCING", "SYNCED"):
            _session(status=status, owner=self.owner)
        self.assertEqual(
            offline_session_ui_service.count_pending_sessions(self.owner), 2
        )

    def test_does_not_count_sessions_from_other_users_devices(self):
        other = User.objects.create_user(username="otro", role="SPECIALIST")
        _session(status="COMPLETED", owner=other)
        _session(status="ERROR", owner=other)
        self.assertEqual(
            offline_session_ui_service.count_pending_sessions(self.owner), 0
        )


class DeleteUnfinishedSessionTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="esp", role="SPECIALIST")

    def test_deletes_unfinished_session(self):
        for status in ("PENDING", "CONFIRMED", "ERROR"):
            s = _session(status=status, owner=self.owner)
            self.assertTrue(
                offline_session_ui_service.delete_unfinished_session(
                    session_id=s.session_id, user=self.owner
                )
            )
        self.assertEqual(
            offline_session_ui_service.list_visible_sessions(self.owner).count(), 0
        )
    def test_cannot_delete_completed_or_syncing_session(self):
        for status in ("COMPLETED", "SYNCING", "SYNCED"):
            s = _session(status=status, owner=self.owner)
            self.assertFalse(
                offline_session_ui_service.delete_unfinished_session(
                    session_id=s.session_id, user=self.owner
                )
            )
        # SYNCED ya no existe localmente: quedan COMPLETED y SYNCING.
        self.assertEqual(
            offline_session_ui_service.list_visible_sessions(self.owner).count(), 2
        )

    def test_cannot_delete_sessions_from_other_users_devices(self):
        other = User.objects.create_user(username="otro", role="SPECIALIST")
        s = _session(status="PENDING", owner=other)
        self.assertFalse(
            offline_session_ui_service.delete_unfinished_session(
                session_id=s.session_id, user=self.owner
            )
        )

    def test_delete_view_redirects_to_panel(self):
        self.owner_client = self.client
        self.client.force_login(self.owner)
        s = _session(status="PENDING", owner=self.owner)
        resp = self.client.post(f"/offline/sessions/{s.session_id}/delete")
        self.assertRedirects(resp, "/offline/panel/", target_status_code=200)
        self.assertFalse(
            OfflineSession.objects.filter(session_id=s.session_id).exists()
        )


class QueueViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="esp", role="SPECIALIST", password="x"
        )
        self.client.force_login(self.user)

    def test_queue_lists_sessions(self):
        _session(status="COMPLETED", owner=self.user)
        resp = self.client.get("/offline/panel/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Completada")

    def test_queue_warns_how_to_sync_when_no_terms_available(self):
        resp = self.client.get("/offline/panel/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(
            resp,
            "No hay terminos y condiciones disponibles. Conecte internet e "
            "inicie sesion online para sincronizarlos.",
        )

    def test_queue_does_not_list_sessions_from_other_users_devices(self):
        other = User.objects.create_user(username="otro", role="SPECIALIST")
        _session(status="COMPLETED", owner=other)
        resp = self.client.get("/offline/panel/")
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "Completada")
        self.assertContains(resp, "Sin sesiones locales")

    def test_pending_session_shown_in_unlinked_section(self):
        _session(owner=self.user)
        resp = self.client.get("/offline/panel/")
        self.assertContains(resp, "Sesiones en curso del visor")
        self.assertContains(resp, "Vincular sesion")
        self.assertContains(resp, "Pendiente")

    def test_pending_session_not_in_finished_table(self):
        _session(owner=self.user)
        resp = self.client.get("/offline/panel/")
        # La sesion pendiente solo aparece en la seccion aislada (1 vez).
        self.assertEqual(resp.content.decode().count("Pendiente"), 1)
        self.assertContains(resp, "Sin sesiones locales")

    @patch("offline_mode.context_processors.is_online", return_value=True)
    def test_queue_renders_fetch_sync_button_when_online_and_pending(self, _):
        _session(status="COMPLETED", owner=self.user)
        resp = self.client.get("/offline/panel/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="btn-sync"')
        self.assertContains(resp, 'data-url="/offline/sync/"')
        token = re.search(r'"X-CSRFToken": "([^"]+)"', resp.content.decode())
        self.assertTrue(
            token, "El header X-CSRFToken debe renderizar un token no vacio"
        )

    @patch("offline_mode.context_processors.is_online", return_value=True)
    def test_queue_hides_sync_button_without_pending_sessions(self, _):
        resp = self.client.get("/offline/panel/")
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'id="btn-sync"')

    def test_confirm_links_specialist(self):
        s = _session(owner=self.user)
        resp = self.client.post(f"/offline/sessions/{s.session_id}/confirm")
        self.assertEqual(resp.status_code, 302)
        s.refresh_from_db()
        self.assertEqual(s.status, "CONFIRMED")
        self.assertEqual(s.specialist, self.user)

    def test_confirm_rejects_sessions_from_other_users_devices(self):
        other = User.objects.create_user(username="otro", role="SPECIALIST")
        s = _session(owner=other)
        resp = self.client.post(f"/offline/sessions/{s.session_id}/confirm")
        self.assertEqual(resp.status_code, 302)
        s.refresh_from_db()
        self.assertEqual(s.status, "PENDING")
        self.assertIsNone(s.specialist)

    def test_detail_shows_metrics_readonly(self):
        s = _session(status="COMPLETED", owner=self.user)
        resp = self.client.get(f"/offline/sessions/{s.session_id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Precision")

    def test_detail_404_for_sessions_from_other_users_devices(self):
        other = User.objects.create_user(username="otro", role="SPECIALIST")
        s = _session(status="COMPLETED", owner=other)
        resp = self.client.get(f"/offline/sessions/{s.session_id}/")
        self.assertEqual(resp.status_code, 404)

    @patch("offline_mode.views.offline_session_ui_service.get_session_for_detail")
    def test_detail_uses_service_lookup(self, get_session_for_detail):
        s = _session(status="COMPLETED", owner=self.user)
        get_session_for_detail.return_value = s

        resp = self.client.get(f"/offline/sessions/{s.session_id}/")

        self.assertEqual(resp.status_code, 200)
        get_session_for_detail.assert_called_once_with(s.session_id, self.user)

    def test_admin_cannot_access_panel(self):
        admin = User.objects.create_user(username="adm", role="ADMIN", password="x")
        self.client.force_login(admin)
        resp = self.client.get("/offline/panel/")
        self.assertEqual(resp.status_code, 403)

    def test_anonymous_redirected_from_panel(self):
        self.client.logout()
        resp = self.client.get("/offline/panel/")
        self.assertEqual(resp.status_code, 302)  # redirect a login


class PairingSearchControlTests(TestCase):
    def setUp(self):
        from django.core.cache import cache

        cache.delete("pairing_window_open")
        self.user = User.objects.create_user(
            username="esp-busqueda", role="SPECIALIST", password="x"
        )
        self.client.force_login(self.user)

    def test_panel_load_does_not_start_search(self):
        from offline_mode.services import pairing_service

        resp = self.client.get("/offline/panel/")
        self.assertFalse(pairing_service.pairing_window_open())
        self.assertContains(resp, "Iniciar busqueda")
        self.assertNotContains(resp, "Detener busqueda")

    def test_start_opens_window_and_shows_stop_button(self):
        from offline_mode.services import pairing_service

        resp = self.client.post("/offline/pairing/start")
        self.assertRedirects(resp, "/offline/panel/", target_status_code=200)
        self.assertTrue(pairing_service.pairing_window_open())
        resp = self.client.get("/offline/panel/")
        self.assertContains(resp, "Detener busqueda")
        self.assertContains(resp, "Buscando dispositivo VR cercano")
        self.assertNotContains(resp, "Iniciar busqueda")

    def test_stop_closes_window(self):
        from offline_mode.services import pairing_service

        pairing_service.open_pairing_window()
        self.client.post("/offline/pairing/stop")
        self.assertFalse(pairing_service.pairing_window_open())

    def test_stop_cancels_pending_request(self):
        from offline_mode.services import pairing_service

        pairing_service.open_pairing_window()
        pairing_service.create_request(
            device_id=str(uuid.uuid4()), device_name="Quest", pin="123456"
        )
        self.assertIsNotNone(pairing_service.active_request())
        self.client.post("/offline/pairing/stop")
        self.assertIsNone(pairing_service.active_request())

    def test_start_and_stop_require_post(self):
        self.assertEqual(self.client.get("/offline/pairing/start").status_code, 405)
        self.assertEqual(self.client.get("/offline/pairing/stop").status_code, 405)

    def test_status_keeps_active_search_alive(self):
        from django.core.cache import cache
        from offline_mode.services import pairing_service

        pairing_service.open_pairing_window()
        with patch.object(
            pairing_service, "open_pairing_window", wraps=pairing_service.open_pairing_window
        ) as refresh:
            data = self.client.get("/offline/panel/status").json()
        refresh.assert_called_once()
        self.assertTrue(data["searching"])
        self.assertIsNotNone(cache.get("pairing_window_open"))

    def test_status_does_not_reopen_stopped_search(self):
        from offline_mode.services import pairing_service

        data = self.client.get("/offline/panel/status").json()
        self.assertFalse(data["searching"])
        self.assertFalse(pairing_service.pairing_window_open())

    def test_successful_pairing_closes_search(self):
        from offline_mode.services import pairing_service

        pairing_service.open_pairing_window()
        pairing_service.create_request(
            device_id=str(uuid.uuid4()), device_name="Quest", pin="123456"
        )
        self.client.post("/offline/pairing/confirm", {"pin": "123456"})
        self.assertFalse(pairing_service.pairing_window_open())

    @patch("offline_mode.context_processors.is_online", return_value=True)
    def test_panel_shows_volver_al_panel_when_online(self, _):
        resp = self.client.get("/offline/panel/")
        self.assertContains(resp, "Volver al Panel")

    @patch("offline_mode.context_processors.is_online", return_value=False)
    def test_panel_hides_volver_al_panel_when_offline(self, _):
        resp = self.client.get("/offline/panel/")
        self.assertNotContains(resp, "Volver al Panel")


class GoOnlineTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="esp-online", role="SPECIALIST", password="x"
        )
        self.client.force_login(self.user)
        session = self.client.session
        session["offline_mode"] = True
        session.save()

    @patch("offline_mode.views.is_online", return_value=True)
    def test_go_online_clears_flag_and_redirects_home(self, _):
        resp = self.client.post("/offline/go-online")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, "/")
        self.assertFalse(self.client.session.get("offline_mode"))

    @patch("offline_mode.views.is_online", return_value=False)
    def test_go_online_without_connection_keeps_offline(self, _):
        resp = self.client.post("/offline/go-online")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, "/offline/panel/")
        self.assertTrue(self.client.session.get("offline_mode"))

    def test_go_online_requires_post(self):
        self.assertEqual(self.client.get("/offline/go-online").status_code, 405)
