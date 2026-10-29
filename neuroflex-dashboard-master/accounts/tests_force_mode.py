from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from offline_mode.services.connectivity import FORCED_OFFLINE_KEY


LOGIN_URL = reverse("accounts:login")
FORCE_URL = reverse("accounts:force-mode")
OFFLINE_BANNER = "Modo sin conexión — solo especialistas."


def _set_session_flag(client, value):
    session = client.session
    session[FORCED_OFFLINE_KEY] = value
    session.save()


class ForcedConnectivityModeTests(TestCase):
    def test_force_offline_sets_flag_and_redirects_to_login(self):
        response = self.client.post(FORCE_URL, {"mode": "offline"})

        self.assertRedirects(response, LOGIN_URL, fetch_redirect_response=False)
        self.assertIs(self.client.session[FORCED_OFFLINE_KEY], True)

    def test_forced_offline_login_shows_banner_without_health_check(self):
        _set_session_flag(self.client, True)

        with patch("accounts.views.is_online") as mocked_is_online:
            response = self.client.get(LOGIN_URL)

        mocked_is_online.assert_not_called()
        self.assertContains(response, OFFLINE_BANNER)

    def test_force_online_retries_real_connectivity_and_clears_flag(self):
        _set_session_flag(self.client, True)

        with patch("accounts.views.is_online") as mocked_is_online:
            response = self.client.post(FORCE_URL, {"mode": "online"})

        self.assertRedirects(response, LOGIN_URL, fetch_redirect_response=False)
        mocked_is_online.assert_not_called()

        with patch("accounts.views.is_online", return_value=True) as mocked_is_online:
            self.client.get(LOGIN_URL)

        mocked_is_online.assert_called_once_with(force=True)
        self.assertNotIn(FORCED_OFFLINE_KEY, self.client.session)

    def test_force_online_falls_back_to_offline_when_check_fails(self):
        _set_session_flag(self.client, True)

        with patch("accounts.views.is_online", return_value=False):
            self.client.post(FORCE_URL, {"mode": "online"})
            response = self.client.get(LOGIN_URL)

        self.assertContains(response, OFFLINE_BANNER)

    def test_invalid_mode_returns_400(self):
        response = self.client.post(FORCE_URL, {"mode": "otro"})

        self.assertEqual(response.status_code, 400)
        self.assertNotIn(FORCED_OFFLINE_KEY, self.client.session)

    def test_only_local_requests_can_force_mode(self):
        response = self.client.post(
            FORCE_URL, {"mode": "offline"}, REMOTE_ADDR="192.168.0.50"
        )

        self.assertEqual(response.status_code, 403)
        self.assertNotIn(FORCED_OFFLINE_KEY, self.client.session)

    def test_natural_detection_without_flag_is_unchanged(self):
        with patch("accounts.views.is_online", return_value=False):
            response = self.client.get(LOGIN_URL)

        self.assertContains(response, OFFLINE_BANNER)
