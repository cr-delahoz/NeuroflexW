from unittest.mock import Mock

from django.test import SimpleTestCase

from integrations.services.api_gateway_users_client import (
    ApiGatewayUsersClient,
    ApiGatewayUsersInvalidResponseError,
    ApiGatewayUsersNotFoundError,
    ApiGatewayUsersServiceError,
)
from integrations.services.neuroflex_api_client import (
    NeuroflexApiInvalidResponseError,
    NeuroflexApiNetworkError,
    NeuroflexApiResponseError,
)


class ApiGatewayUsersClientTests(SimpleTestCase):
    def setUp(self):
        self.transport = Mock()
        self.client = ApiGatewayUsersClient(api_client=self.transport)
        self.user = {
            "user_id": "sub-1",
            "email": "ana@example.com",
            "role": "Specialist",
            "is_active": True,
            "onboarding_status": "",
            "cognito_status": "",
        }

    def test_list_users_uses_filters_and_returns_page(self):
        self.transport.get.return_value = {"users": [self.user], "next_token": "page-2"}

        users, next_token = self.client.list_users(
            "id-token",
            role="Specialist",
            is_active=True,
            limit=50,
            next_token="page-1",
        )

        self.assertEqual(next_token, "page-2")
        self.assertEqual(users[0]["user_id"], "sub-1")
        self.transport.get.assert_called_once_with(
            "/users",
            token="id-token",
            params={
                "role": "Specialist",
                "is_active": "true",
                "limit": 50,
                "next_token": "page-1",
            },
        )

    def test_list_users_omits_optional_filters(self):
        self.transport.get.return_value = {"users": [], "next_token": None}

        users, next_token = self.client.list_users("id-token")

        self.assertEqual(users, [])
        self.assertIsNone(next_token)
        self.transport.get.assert_called_once_with(
            "/users", token="id-token", params={"limit": 50}
        )

    def test_get_user_uses_user_endpoint(self):
        self.transport.get.return_value = self.user

        user = self.client.get_user("id-token", "sub-1")

        self.assertEqual(user, self.user)
        self.transport.get.assert_called_once_with("/users/sub-1", token="id-token")

    def test_create_user_validates_role_and_sends_payload(self):
        self.transport.post.return_value = self.user

        user = self.client.create_user("id-token", "ana@example.com", "Specialist")

        self.assertEqual(user, self.user)
        self.transport.post.assert_called_once_with(
            "/users",
            token="id-token",
            json_body={
                "email": "ana@example.com",
                "role": "Specialist",
            },
        )

    def test_update_user_status_sends_status_endpoint_and_payload(self):
        self.transport.patch.return_value = {**self.user, "is_active": False}

        user = self.client.update_user_status("id-token", "sub-1", False)

        self.assertFalse(user["is_active"])
        self.transport.patch.assert_called_once_with(
            "/users/sub-1/status", token="id-token", json_body={"is_active": False}
        )

    def test_update_user_role_validates_role_and_sends_payload(self):
        self.transport.patch.return_value = {**self.user, "role": "Administrator"}

        user = self.client.update_user_role("id-token", "sub-1", "Administrator")

        self.assertEqual(user["role"], "Administrator")
        self.transport.patch.assert_called_once_with(
            "/users/sub-1/role",
            token="id-token",
            json_body={"role": "Administrator"},
        )

    def test_invalid_remote_role_is_rejected_before_requests(self):
        with self.assertRaises(ValueError):
            self.client._validate_role("ADMIN")
        with self.assertRaises(ValueError):
            self.client.list_users("id-token", role="ADMIN")
        with self.assertRaises(ValueError):
            self.client.create_user("id-token", "ana@example.com", "ADMIN")
        with self.assertRaises(ValueError):
            self.client.update_user_role("id-token", "sub-1", "ADMIN")

        self.transport.get.assert_not_called()
        self.transport.post.assert_not_called()
        self.transport.patch.assert_not_called()

    def test_non_string_roles_are_rejected_before_requests(self):
        for role in ([], {}):
            with self.subTest(role=role):
                with self.assertRaises(ValueError):
                    self.client.list_users("id-token", role=role)
                with self.assertRaises(ValueError):
                    self.client.create_user("id-token", "ana@example.com", role)
                with self.assertRaises(ValueError):
                    self.client.update_user_role("id-token", "sub-1", role)

        self.transport.get.assert_not_called()
        self.transport.post.assert_not_called()
        self.transport.patch.assert_not_called()

    def test_get_user_translates_404_to_not_found(self):
        self.transport.get.side_effect = NeuroflexApiResponseError(
            "missing", status_code=404, payload={"message": "missing"}, text="missing"
        )

        with self.assertRaises(ApiGatewayUsersNotFoundError):
            self.client.get_user("id-token", "missing")

    def test_non_404_response_and_network_errors_translate_to_service_error(self):
        self.transport.get.side_effect = NeuroflexApiResponseError("bad", status_code=500)

        with self.assertRaises(ApiGatewayUsersServiceError):
            self.client.list_users("id-token")

        self.transport.get.side_effect = NeuroflexApiNetworkError("offline")

        with self.assertRaises(ApiGatewayUsersServiceError):
            self.client.list_users("id-token")

    def test_invalid_transport_response_translates_to_invalid_response(self):
        self.transport.get.side_effect = NeuroflexApiInvalidResponseError("unreadable")

        with self.assertRaises(ApiGatewayUsersInvalidResponseError):
            self.client.list_users("id-token")

    def test_partial_status_payload_without_role_is_accepted(self):
        self.transport.patch.return_value = {
            "user_id": "sub-1",
            "email": "ana@example.com",
            "is_active": False,
            "updated_at": 1787092824,
        }

        user = self.client.update_user_status("id-token", "sub-1", False)

        self.assertFalse(user["is_active"])
        self.transport.patch.assert_called_once_with(
            "/users/sub-1/status", token="id-token", json_body={"is_active": False}
        )
        self.transport.get.assert_not_called()

    def test_partial_role_payload_without_is_active_is_accepted(self):
        self.transport.patch.return_value = {
            "user_id": "sub-1",
            "email": "ana@example.com",
            "role": "Administrator",
            "updated_at": 1787092824,
        }

        user = self.client.update_user_role("id-token", "sub-1", "Administrator")

        self.assertEqual(user["role"], "Administrator")
        self.transport.patch.assert_called_once_with(
            "/users/sub-1/role",
            token="id-token",
            json_body={"role": "Administrator"},
        )
        self.transport.get.assert_not_called()

    def test_incomplete_payload_without_user_id_raises_invalid_response(self):
        self.transport.patch.return_value = {
            "email": "ana@example.com",
            "role": "Specialist",
        }

        with self.assertRaises(ApiGatewayUsersInvalidResponseError):
            self.client.update_user_status("id-token", "sub-1", False)

        self.transport.get.assert_not_called()

    def test_incomplete_payload_without_email_raises_invalid_response(self):
        self.transport.patch.return_value = {
            "user_id": "sub-1",
            "role": "Administrator",
        }

        with self.assertRaises(ApiGatewayUsersInvalidResponseError):
            self.client.update_user_role("id-token", "sub-1", "Administrator")

        self.transport.get.assert_not_called()

    def test_invalid_page_payload_never_reaches_caller(self):
        self.transport.get.return_value = {"users": [self.user], "next_token": 2}

        with self.assertRaises(ApiGatewayUsersInvalidResponseError):
            self.client.list_users("id-token")

    def test_non_hashable_remote_roles_raise_controlled_invalid_response(self):
        for role in ([], {}):
            with self.subTest(role=role):
                self.transport.get.return_value = {
                    "users": [{**self.user, "role": role}],
                    "next_token": None,
                }

                with self.assertRaises(ApiGatewayUsersInvalidResponseError):
                    self.client.list_users("id-token")

    def test_parse_user_includes_onboarding_and_cognito_status(self):
        user = self.client._parse_user(
            {
                **self.user,
                "onboarding_status": "COMPLETED",
                "cognito_status": "CONFIRMED",
            }
        )

        self.assertEqual(user["onboarding_status"], "COMPLETED")
        self.assertEqual(user["cognito_status"], "CONFIRMED")

    def test_parse_user_handles_missing_status_fields(self):
        user = self.client._parse_user(self.user)

        self.assertEqual(user["onboarding_status"], "")
        self.assertEqual(user["cognito_status"], "")

    def test_parse_user_accepts_payload_without_role_or_is_active(self):
        user = self.client._parse_user(
            {
                "user_id": "sub-1",
                "email": "ana@example.com",
                "updated_at": 1787092824,
            }
        )

        self.assertEqual(user["user_id"], "sub-1")
        self.assertEqual(user["email"], "ana@example.com")
        self.assertNotIn("role", user)
        self.assertNotIn("is_active", user)

    def test_parse_user_rejects_invalid_role_when_present(self):
        for role in ("ADMIN", [], {}):
            with self.subTest(role=role):
                with self.assertRaises(ApiGatewayUsersInvalidResponseError):
                    self.client._parse_user({**self.user, "role": role})

    def test_parse_user_rejects_null_role_when_present(self):
        with self.assertRaises(ApiGatewayUsersInvalidResponseError):
            self.client._parse_user({**self.user, "role": None})

    def test_parse_user_rejects_non_bool_is_active_when_present(self):
        for is_active in ("true", 1, "false"):
            with self.subTest(is_active=is_active):
                with self.assertRaises(ApiGatewayUsersInvalidResponseError):
                    self.client._parse_user({**self.user, "is_active": is_active})

    def test_parse_user_rejects_null_is_active_when_present(self):
        with self.assertRaises(ApiGatewayUsersInvalidResponseError):
            self.client._parse_user({**self.user, "is_active": None})
