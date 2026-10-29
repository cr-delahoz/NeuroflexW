from unittest.mock import Mock, patch

import requests
from django.test import SimpleTestCase

from integrations.services.neuroflex_api_client import (
    NeuroflexApiClient,
    NeuroflexApiConfigurationError,
    NeuroflexApiInvalidResponseError,
    NeuroflexApiNetworkError,
    NeuroflexApiResponseError,
)


class NeuroflexApiClientTests(SimpleTestCase):
    def setUp(self):
        runtime = Mock()
        runtime.get_neuroflex_api_base_url.return_value = "https://api.neuroflex.example.com"
        self.runtime_patcher = patch(
            "integrations.services.neuroflex_api_client.RuntimeConfig",
            return_value=runtime,
        )
        self.runtime_patcher.start()
        self.addCleanup(self.runtime_patcher.stop)
        self.client = NeuroflexApiClient()

    @patch("integrations.services.neuroflex_api_client.requests.request")
    def test_get_success_parses_json(self, mock_request):
        mock_request.return_value = Mock(
            status_code=200,
            content=b'{"session_id": "abc123"}',
            json=Mock(return_value={"session_id": "abc123"}),
        )

        result = self.client.get("/sessions/abc123")

        self.assertEqual(result, {"session_id": "abc123"})
        called_headers = mock_request.call_args.kwargs["headers"]
        self.assertNotIn("Authorization", called_headers)

    @patch("integrations.services.neuroflex_api_client.requests.request")
    def test_get_with_token_sends_authorization_header(self, mock_request):
        mock_request.return_value = Mock(
            status_code=200,
            content=b"{}",
            json=Mock(return_value={}),
        )

        self.client.get("/sessions", token="fake-jwt-token")

        called_headers = mock_request.call_args.kwargs["headers"]
        self.assertEqual(called_headers["Authorization"], "Bearer fake-jwt-token")

    @patch("integrations.services.neuroflex_api_client.requests.request")
    def test_post_success_parses_json(self, mock_request):
        mock_request.return_value = Mock(
            status_code=201,
            content=b'{"status": "confirmed"}',
            json=Mock(return_value={"status": "confirmed"}),
        )

        result = self.client.post(
            "/sessions/confirm", json_body={"display_code": "123456"}
        )

        self.assertEqual(result, {"status": "confirmed"})
        self.assertEqual(
            mock_request.call_args.kwargs["json"], {"display_code": "123456"}
        )
        self.assertEqual(
            mock_request.call_args.args,
            ("POST", "https://api.neuroflex.example.com/sessions/confirm"),
        )

    @patch("integrations.services.neuroflex_api_client.requests.request")
    def test_post_with_response_preserves_http_status(self, mock_request):
        mock_request.return_value = Mock(
            status_code=202,
            content=b'{"status": "pending"}',
            json=Mock(return_value={"status": "pending"}),
        )

        result = self.client.post_with_response(
            "/sessions/sync", json_body={"session_id": "abc123"}
        )

        self.assertEqual(result.status_code, 202)
        self.assertEqual(result.json(), {"status": "pending"})

    @patch("integrations.services.neuroflex_api_client.requests.request")
    def test_patch_sends_json_and_response_error_keeps_404_details(self, mock_request):
        mock_request.return_value = Mock(
            status_code=404,
            content=b'{"message":"missing"}',
            text='{"message":"missing"}',
            json=Mock(return_value={"message": "missing"}),
        )

        with self.assertRaises(NeuroflexApiResponseError) as raised:
            self.client.patch(
                "/users/missing/status", token="id-token", json_body={"is_active": False}
            )

        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(raised.exception.payload, {"message": "missing"})
        self.assertEqual(raised.exception.text, '{"message":"missing"}')
        self.assertEqual(mock_request.call_args.args[0], "PATCH")
        self.assertEqual(mock_request.call_args.kwargs["json"], {"is_active": False})

    @patch("integrations.services.neuroflex_api_client.requests.request")
    def test_non_2xx_response_raises_response_error(self, mock_request):
        mock_request.return_value = Mock(status_code=404, content=b"{}")

        with self.assertRaises(NeuroflexApiResponseError):
            self.client.get("/sessions/unknown")

    @patch(
        "integrations.services.neuroflex_api_client.requests.request",
        side_effect=requests.exceptions.ConnectionError,
    )
    def test_network_error_is_wrapped(self, mock_request):
        with self.assertRaises(NeuroflexApiNetworkError):
            self.client.get("/sessions")

    @patch(
        "integrations.services.neuroflex_api_client.requests.request",
        side_effect=requests.exceptions.Timeout,
    )
    def test_timeout_is_wrapped(self, mock_request):
        with self.assertRaises(NeuroflexApiNetworkError):
            self.client.get("/sessions")

    @patch("integrations.services.neuroflex_api_client.requests.request")
    def test_malformed_json_response_raises_invalid_response(self, mock_request):
        mock_request.return_value = Mock(
            status_code=200,
            content=b"not-json",
            json=Mock(side_effect=ValueError),
        )

        with self.assertRaises(NeuroflexApiInvalidResponseError):
            self.client.get("/sessions")

    def test_missing_base_url_raises_configuration_error(self):
        with self.assertRaises(NeuroflexApiConfigurationError):
            NeuroflexApiClient(base_url="change-me")

    @patch("integrations.services.neuroflex_api_client.requests.request")
    def test_empty_response_body_returns_none(self, mock_request):
        mock_request.return_value = Mock(status_code=204, content=b"")

        result = self.client.get("/sessions/abc123")

        self.assertIsNone(result)
