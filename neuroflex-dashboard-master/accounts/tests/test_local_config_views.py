import json
from unittest.mock import patch

from django.test import SimpleTestCase
from django.urls import reverse

from accounts.local_config_service import LocalConfigValidationError


class LocalConfigViewTests(SimpleTestCase):
    def test_rejects_non_local_request(self):
        response = self.client.get(
            reverse("accounts:local-config"), REMOTE_ADDR="192.0.2.1"
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"error": "Acceso denegado."})

    def test_rejects_forwarded_request_from_localhost(self):
        response = self.client.get(
            reverse("accounts:local-config"),
            REMOTE_ADDR="127.0.0.1",
            HTTP_X_FORWARDED_FOR="198.51.100.10",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"error": "Acceso denegado."})

    def test_rejects_other_proxy_headers_from_localhost(self):
        for header in (
            "HTTP_FORWARDED",
            "HTTP_X_REAL_IP",
            "HTTP_X_FORWARDED_HOST",
            "HTTP_X_FORWARDED_PROTO",
        ):
            with self.subTest(header=header):
                response = self.client.get(
                    reverse("accounts:local-config"),
                    REMOTE_ADDR="127.0.0.1",
                    **{header: "198.51.100.10"},
                )

                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json(), {"error": "Acceso denegado."})

    def test_get_returns_config(self):
        config = {
            "NEUROFLEX_API_BASE_URL": "https://api.example.com",
            "COGNITO_CLIENT_ID": "client-123",
            "GITHUB_TOKEN": "••••abcd",
        }
        with patch("accounts.views.read_config", return_value=config):
            response = self.client.get(reverse("accounts:local-config"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), config)

    def test_post_writes_json_and_returns_config(self):
        payload = {
            "NEUROFLEX_API_BASE_URL": "https://api.example.com",
            "COGNITO_CLIENT_ID": "client-123",
            "GITHUB_TOKEN": "github-token",
        }
        result = {**payload, "GITHUB_TOKEN": "••••oken"}
        with patch("accounts.views.write_config", return_value=result) as write:
            response = self.client.post(
                reverse("accounts:local-config"),
                data=json.dumps(payload),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), result)
        write.assert_called_once_with(payload)

    def test_post_invalid_json_returns_400(self):
        response = self.client.post(
            reverse("accounts:local-config"),
            data="not-json",
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_post_non_object_returns_400(self):
        response = self.client.post(
            reverse("accounts:local-config"),
            data=json.dumps(["value"]),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_post_validation_error_returns_400(self):
        with patch(
            "accounts.views.write_config",
            side_effect=LocalConfigValidationError("Claves no permitidas: X."),
        ):
            response = self.client.post(
                reverse("accounts:local-config"),
                data=json.dumps({"X": "value"}),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": "Claves no permitidas: X."})

    def test_post_oserror_returns_500(self):
        with patch(
            "accounts.views.write_config",
            side_effect=OSError("config file unavailable"),
        ):
            response = self.client.post(
                reverse("accounts:local-config"),
                data=json.dumps({"NEUROFLEX_API_BASE_URL": "https://api.example.com"}),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.json(), {"error": "No fue posible guardar la configuración."}
        )

    def test_post_unexpected_error_returns_generic_json_500(self):
        with patch(
            "accounts.views.write_config",
            side_effect=ValueError("internal implementation detail"),
        ):
            response = self.client.post(
                reverse("accounts:local-config"),
                data=json.dumps({"NEUROFLEX_API_BASE_URL": "https://api.example.com"}),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.json(), {"error": "No fue posible guardar la configuración."}
        )
