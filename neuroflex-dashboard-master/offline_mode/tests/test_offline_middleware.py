from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


User = get_user_model()


class OfflineModeMiddlewareTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="esp", role="SPECIALIST", password="x")
        self.client.force_login(self.user)

    def _set_offline_session(self):
        session = self.client.session
        session["offline_mode"] = True
        session.save()

    def test_offline_session_redirected_from_dashboard(self):
        self._set_offline_session()
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/offline/", resp.url)

    def test_offline_session_can_access_offline_queue(self):
        self._set_offline_session()
        resp = self.client.get("/offline/panel/")
        self.assertEqual(resp.status_code, 200)

    def test_offline_session_can_access_real_login_url(self):
        self.client.logout()
        self._set_offline_session()
        resp = self.client.get(reverse("accounts:login"))
        self.assertEqual(resp.status_code, 200)

    def test_offline_session_can_logout_via_real_logout_url(self):
        self._set_offline_session()
        resp = self.client.post(reverse("accounts:logout"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("accounts:login"))
        self.assertFalse(self.client.session.get("offline_mode"))

    def test_online_session_not_redirected(self):
        resp = self.client.get("/offline/panel/")
        self.assertEqual(resp.status_code, 200)
