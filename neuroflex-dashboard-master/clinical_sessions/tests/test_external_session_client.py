from unittest.mock import Mock

from django.test import SimpleTestCase

from clinical_sessions.services.external_session_client import (
    ExternalSessionServiceUnavailableError,
    InvalidDisplayCodeError,
    confirm_display_code,
    list_sessions_confirmed_by,
)
from integrations.services.neuroflex_api_client import (
    NeuroflexApiNetworkError,
    NeuroflexApiResponseError,
)


class ConfirmDisplayCodeTests(SimpleTestCase):
    def test_confirm_display_code_success(self):
        client = Mock()
        client.post.return_value = {
            "session_id": "abc123",
            "status": "confirmed",
            "terms_version_id": "v1.0.0",
        }

        result = confirm_display_code("123456", "fake-id-token", api_client=client)

        self.assertEqual(result["session_id"], "abc123")
        client.post.assert_called_once_with(
            "/sessions/confirm",
            token="fake-id-token",
            json_body={"display_code": "123456"},
        )

    def test_confirm_display_code_rejected_raises_invalid_code(self):
        client = Mock()
        client.post.side_effect = NeuroflexApiResponseError("bad request")

        with self.assertRaises(InvalidDisplayCodeError):
            confirm_display_code("000000", "fake-id-token", api_client=client)

    def test_confirm_display_code_network_error_raises_unavailable(self):
        client = Mock()
        client.post.side_effect = NeuroflexApiNetworkError("no network")

        with self.assertRaises(ExternalSessionServiceUnavailableError):
            confirm_display_code("123456", "fake-id-token", api_client=client)

    def test_confirm_display_code_missing_session_id_raises_invalid_code(self):
        client = Mock()
        client.post.return_value = {}

        with self.assertRaises(InvalidDisplayCodeError):
            confirm_display_code("123456", "fake-id-token", api_client=client)


class ListSessionsConfirmedByTests(SimpleTestCase):
    def test_calls_api_with_sub_and_bearer_token(self):
        client = Mock()
        client.get.return_value = {"sessions": [{"session_id": "s1"}], "next_cursor": None}

        sessions = list_sessions_confirmed_by("sub-123", "fake-id-token", api_client=client)

        self.assertEqual(sessions, [{"session_id": "s1"}])
        client.get.assert_called_once_with(
            "/sessions",
            token="fake-id-token",
            params={"confirmed_by_sub": "sub-123"},
        )

    def test_follows_next_cursor_until_exhausted(self):
        client = Mock()
        client.get.side_effect = [
            {"sessions": [{"session_id": "s1"}], "next_cursor": "cursor-2"},
            {"sessions": [{"session_id": "s2"}], "next_cursor": None},
        ]

        sessions = list_sessions_confirmed_by("sub-123", "fake-id-token", api_client=client)

        self.assertEqual(sessions, [{"session_id": "s1"}, {"session_id": "s2"}])
        self.assertEqual(client.get.call_count, 2)
        second_call_params = client.get.call_args_list[1].kwargs["params"]
        self.assertEqual(second_call_params["cursor"], "cursor-2")

    def test_network_error_raises_unavailable(self):
        client = Mock()
        client.get.side_effect = NeuroflexApiNetworkError("no network")

        with self.assertRaises(ExternalSessionServiceUnavailableError):
            list_sessions_confirmed_by("sub-123", "fake-id-token", api_client=client)
