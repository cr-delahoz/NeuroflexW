from django.test import TestCase


class LocalhostGuardTests(TestCase):
    def test_lan_api_allowed_from_lan_ip(self):
        resp = self.client.get("/api/lan/terms/current", REMOTE_ADDR="192.168.1.50")
        self.assertEqual(resp.status_code, 401)  # pide token, NO 403

    def test_web_ui_forbidden_from_lan_ip(self):
        resp = self.client.get("/offline/panel/", REMOTE_ADDR="192.168.1.50")
        self.assertEqual(resp.status_code, 403)

    def test_proxy_header_rejected_even_from_localhost(self):
        resp = self.client.get("/offline/panel/", REMOTE_ADDR="127.0.0.1",
                               HTTP_X_FORWARDED_FOR="10.0.0.9")
        self.assertEqual(resp.status_code, 403)
