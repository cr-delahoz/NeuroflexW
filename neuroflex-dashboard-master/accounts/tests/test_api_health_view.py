from unittest.mock import Mock, patch

import requests
from django.test import SimpleTestCase
from django.urls import reverse


class ApiHealthCheckViewTests(SimpleTestCase):
    def _runtime(self, base_url):
        runtime = Mock()
        runtime.get_neuroflex_api_base_url.return_value = base_url
        return patch("accounts.views.RuntimeConfig", return_value=runtime)

    def test_rejects_non_local_request(self):
        response = self.client.get(
            reverse("accounts:api-health"), REMOTE_ADDR="192.0.2.1"
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"error": "Acceso denegado."})

    def test_rejects_forwarded_request_from_localhost(self):
        response = self.client.get(
            reverse("accounts:api-health"),
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
                    reverse("accounts:api-health"),
                    REMOTE_ADDR="127.0.0.1",
                    **{header: "198.51.100.10"},
                )

                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json(), {"error": "Acceso denegado."})

    def test_returns_unavailable_for_malformed_url(self):
        with self._runtime("http://[invalid"):
            response = self.client.get(reverse("accounts:api-health"))

        self.assertEqual(response.json(), {"available": False})

    def test_returns_available_true_for_2xx(self):
        with self._runtime("https://api.example.com"), patch(
            "accounts.views.requests.Session"
        ) as session_class:
            session_class.return_value.__enter__.return_value.get.return_value = Mock(
                status_code=204
            )
            response = self.client.get(reverse("accounts:api-health"))

        self.assertEqual(response.json(), {"available": True})

    def test_returns_unavailable_for_non_2xx(self):
        with self._runtime("https://api.example.com"), patch(
            "accounts.views.requests.Session"
        ) as session_class:
            session_class.return_value.__enter__.return_value.get.return_value = Mock(
                status_code=503
            )
            response = self.client.get(reverse("accounts:api-health"))

        self.assertEqual(response.json(), {"available": False})

    def test_returns_unavailable_for_exception(self):
        with self._runtime("https://api.example.com"), patch(
            "accounts.views.requests.Session"
        ) as session_class:
            session_class.return_value.__enter__.return_value.get.side_effect = (
                requests.RequestException()
            )
            response = self.client.get(reverse("accounts:api-health"))

        self.assertEqual(response.json(), {"available": False})

    def test_unexpected_exception_propagates(self):
        with self._runtime("https://api.example.com"), patch(
            "accounts.views.requests.Session"
        ) as session_class:
            session_class.return_value.__enter__.return_value.get.side_effect = (
                RuntimeError("unexpected failure")
            )

            with self.assertRaises(RuntimeError):
                self.client.get(reverse("accounts:api-health"))

    def test_invalid_scheme_does_not_request(self):
        with self._runtime("ftp://api.example.com"), patch(
            "accounts.views.requests.Session"
        ) as session_class:
            response = self.client.get(reverse("accounts:api-health"))

        self.assertEqual(response.json(), {"available": False})
        session_class.assert_not_called()

    def test_uses_health_path_and_five_second_timeout(self):
        with self._runtime("https://api.example.com/"), patch(
            "accounts.views.requests.Session"
        ) as session_class:
            session_class.return_value.__enter__.return_value.get.return_value = Mock(
                status_code=200
            )
            self.client.get(reverse("accounts:api-health"))

        session = session_class.return_value.__enter__.return_value
        session.get.assert_called_once_with("https://api.example.com/health", timeout=5)

    def test_limits_health_check_redirects_to_three(self):
        with self._runtime("https://api.example.com"), patch(
            "accounts.views.requests.Session"
        ) as session_class:
            session_class.return_value.__enter__.return_value.get.return_value = Mock(
                status_code=200
            )
            self.client.get(reverse("accounts:api-health"))

        session = session_class.return_value.__enter__.return_value
        self.assertEqual(session.max_redirects, 3)

    def test_appends_health_to_base_path_without_query_or_fragment(self):
        with self._runtime("https://api.example.com/v1?x=1#section"), patch(
            "accounts.views.requests.Session"
        ) as session_class:
            session_class.return_value.__enter__.return_value.get.return_value = Mock(
                status_code=200
            )
            self.client.get(reverse("accounts:api-health"))

        session = session_class.return_value.__enter__.return_value
        session.get.assert_called_once_with(
            "https://api.example.com/v1/health", timeout=5
        )
