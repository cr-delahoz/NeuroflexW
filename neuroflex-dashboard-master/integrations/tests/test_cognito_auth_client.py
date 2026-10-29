from unittest.mock import Mock, patch

import requests
from django.test import SimpleTestCase, override_settings

from integrations.services.cognito_auth_client import (
    CognitoAuthClient,
    CognitoConfigurationError,
    CognitoInvalidCredentialsError,
    CognitoInvalidResponseError,
    CognitoNetworkError,
    CognitoServiceError,
    CognitoUserNotFoundError,
)


@override_settings(COGNITO_REGION="us-east-1")
class CognitoAuthClientTests(SimpleTestCase):
    def setUp(self):
        runtime = Mock()
        runtime.get_cognito_client_id.return_value = "test-client-id"
        self.runtime_patcher = patch(
            "integrations.services.cognito_auth_client.RuntimeConfig",
            return_value=runtime,
        )
        self.runtime_patcher.start()
        self.addCleanup(self.runtime_patcher.stop)
        self.client = CognitoAuthClient()

    @patch("integrations.services.cognito_auth_client.requests.post")
    def test_initiate_auth_success_parses_tokens(self, mock_post):
        mock_post.return_value = Mock(
            status_code=200,
            json=Mock(
                return_value={
                    "AuthenticationResult": {
                        "IdToken": "id-token",
                        "AccessToken": "access-token",
                        "RefreshToken": "refresh-token",
                        "ExpiresIn": 3600,
                    }
                }
            ),
        )

        result = self.client.initiate_auth("test@example.com", "fake-password")

        self.assertEqual(
            result,
            {
                "status": "authenticated",
                "id_token": "id-token",
                "access_token": "access-token",
                "refresh_token": "refresh-token",
                "expires_in": 3600,
            },
        )
        called_url = mock_post.call_args.args[0]
        self.assertEqual(called_url, "https://cognito-idp.us-east-1.amazonaws.com/")
        called_headers = mock_post.call_args.kwargs["headers"]
        self.assertEqual(
            called_headers["X-Amz-Target"],
            "AWSCognitoIdentityProviderService.InitiateAuth",
        )

    @patch("integrations.services.cognito_auth_client.requests.post")
    def test_initiate_auth_returns_structured_new_password_required_challenge(
        self, mock_post
    ):
        mock_post.return_value = Mock(
            status_code=200,
            json=Mock(
                return_value={
                    "ChallengeName": "NEW_PASSWORD_REQUIRED",
                    "Session": "cognito-session",
                    "ChallengeParameters": {"requiredAttributes": '["email"]'},
                }
            ),
        )

        result = self.client.initiate_auth("ana@example.com", "Temp-pass-123!")

        self.assertEqual(result["status"], "new_password_required")
        self.assertEqual(result["session"], "cognito-session")
        self.assertEqual(result["username"], "ana@example.com")
        self.assertEqual(result["required_attributes"], ["email"])
        self.assertNotIn("id_token", result)

    @patch("integrations.services.cognito_auth_client.requests.post")
    def test_respond_to_new_password_challenge_sends_email_attribute(self, mock_post):
        mock_post.return_value = Mock(
            status_code=200,
            json=Mock(
                return_value={
                    "AuthenticationResult": {
                        "IdToken": "id",
                        "AccessToken": "access",
                        "RefreshToken": "refresh",
                        "ExpiresIn": 3600,
                    }
                }
            ),
        )

        result = self.client.respond_to_new_password_challenge(
            "ana@example.com", "New-pass-456!", "cognito-session", ["email"]
        )

        self.assertEqual(result["status"], "authenticated")
        self.assertEqual(
            mock_post.call_args.kwargs["json"]["ChallengeResponses"],
            {
                "USERNAME": "ana@example.com",
                "NEW_PASSWORD": "New-pass-456!",
                "userAttributes.email": "ana@example.com",
            },
        )
        self.assertEqual(
            mock_post.call_args.kwargs["json"]["Session"], "cognito-session"
        )

    @patch("integrations.services.cognito_auth_client.requests.post")
    def test_respond_to_new_password_challenge_omits_email_when_not_required(
        self, mock_post
    ):
        mock_post.return_value = Mock(
            status_code=200,
            json=Mock(
                return_value={
                    "AuthenticationResult": {
                        "IdToken": "id",
                        "AccessToken": "access",
                        "RefreshToken": "refresh",
                        "ExpiresIn": 3600,
                    }
                }
            ),
        )

        self.client.respond_to_new_password_challenge(
            "ana@example.com", "New-pass-456!", "cognito-session", []
        )

        self.assertEqual(
            mock_post.call_args.kwargs["json"]["ChallengeResponses"],
            {"USERNAME": "ana@example.com", "NEW_PASSWORD": "New-pass-456!"},
        )

    @patch("integrations.services.cognito_auth_client.requests.post")
    def test_respond_to_new_password_challenge_rejects_unknown_attribute(
        self, mock_post
    ):
        with self.assertRaises(CognitoInvalidResponseError):
            self.client.respond_to_new_password_challenge(
                "ana@example.com", "New-pass-456!", "cognito-session", ["phone_number"]
            )

        mock_post.assert_not_called()

    @patch("integrations.services.cognito_auth_client.requests.post")
    def test_new_password_required_errors_do_not_expose_session(self, mock_post):
        mock_post.return_value = Mock(
            status_code=200,
            json=Mock(
                return_value={
                    "ChallengeName": "NEW_PASSWORD_REQUIRED",
                    "Session": "sensitive-cognito-session",
                    "ChallengeParameters": {"requiredAttributes": "not-json"},
                }
            ),
        )

        with self.assertRaises(CognitoInvalidResponseError) as raised:
            self.client.initiate_auth("ana@example.com", "Temp-pass-123!")

        self.assertNotIn("sensitive-cognito-session", str(raised.exception))

    @patch("integrations.services.cognito_auth_client.requests.post")
    def test_initiate_auth_not_authorized_raises_invalid_credentials(self, mock_post):
        mock_post.return_value = Mock(
            status_code=400,
            json=Mock(
                return_value={
                    "__type": "NotAuthorizedException",
                    "message": "Incorrect username or password.",
                }
            ),
        )

        with self.assertRaises(CognitoInvalidCredentialsError):
            self.client.initiate_auth("test@example.com", "wrong-password")

    @patch("integrations.services.cognito_auth_client.requests.post")
    def test_initiate_auth_user_not_found_raises_user_not_found(self, mock_post):
        mock_post.return_value = Mock(
            status_code=400,
            json=Mock(
                return_value={
                    "__type": "UserNotFoundException",
                    "message": "User does not exist.",
                }
            ),
        )

        with self.assertRaises(CognitoUserNotFoundError):
            self.client.initiate_auth("missing@example.com", "fake-password")

    @patch("integrations.services.cognito_auth_client.requests.post")
    def test_initiate_auth_unmapped_error_raises_service_error(self, mock_post):
        mock_post.return_value = Mock(
            status_code=500,
            json=Mock(
                return_value={
                    "__type": "InternalErrorException",
                    "message": "Something went wrong.",
                }
            ),
        )

        with self.assertRaises(CognitoServiceError):
            self.client.initiate_auth("test@example.com", "fake-password")

    @patch(
        "integrations.services.cognito_auth_client.requests.post",
        side_effect=requests.exceptions.ConnectionError,
    )
    def test_initiate_auth_network_error_is_wrapped(self, mock_post):
        with self.assertRaises(CognitoNetworkError):
            self.client.initiate_auth("test@example.com", "fake-password")

    @patch(
        "integrations.services.cognito_auth_client.requests.post",
        side_effect=requests.exceptions.Timeout,
    )
    def test_initiate_auth_timeout_is_wrapped(self, mock_post):
        with self.assertRaises(CognitoNetworkError):
            self.client.initiate_auth("test@example.com", "fake-password")

    @patch("integrations.services.cognito_auth_client.requests.post")
    def test_initiate_auth_malformed_json_raises_invalid_response(self, mock_post):
        mock_post.return_value = Mock(status_code=200, json=Mock(side_effect=ValueError))

        with self.assertRaises(CognitoInvalidResponseError):
            self.client.initiate_auth("test@example.com", "fake-password")

    @patch("integrations.services.cognito_auth_client.requests.post")
    def test_initiate_auth_missing_authentication_result_raises_invalid_response(
        self, mock_post
    ):
        mock_post.return_value = Mock(status_code=200, json=Mock(return_value={}))

        with self.assertRaises(CognitoInvalidResponseError):
            self.client.initiate_auth("test@example.com", "fake-password")

    @patch("integrations.services.cognito_auth_client.requests.post")
    def test_refresh_tokens_success_parses_tokens_without_refresh_token(self, mock_post):
        mock_post.return_value = Mock(
            status_code=200,
            json=Mock(
                return_value={
                    "AuthenticationResult": {
                        "IdToken": "new-id-token",
                        "AccessToken": "new-access-token",
                        "ExpiresIn": 3600,
                    }
                }
            ),
        )

        result = self.client.refresh_tokens("stored-refresh-token")

        self.assertEqual(
            result,
            {
                "status": "authenticated",
                "id_token": "new-id-token",
                "access_token": "new-access-token",
                "refresh_token": None,
                "expires_in": 3600,
            },
        )
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["AuthFlow"], "REFRESH_TOKEN_AUTH")
        self.assertEqual(payload["AuthParameters"]["REFRESH_TOKEN"], "stored-refresh-token")
        self.assertEqual(payload["ClientId"], "test-client-id")

    @patch("integrations.services.cognito_auth_client.requests.post")
    def test_refresh_tokens_rejects_missing_refresh_token_without_request(self, mock_post):
        with self.assertRaises(Exception):
            self.client.refresh_tokens("")
        mock_post.assert_not_called()

    @patch("integrations.services.cognito_auth_client.requests.post")
    def test_refresh_tokens_invalid_refresh_token_raises(self, mock_post):
        mock_post.return_value = Mock(
            status_code=400,
            json=Mock(
                return_value={
                    "__type": "NotAuthorizedException",
                    "message": "Invalid refresh token.",
                }
            ),
        )

        with self.assertRaises(Exception):
            self.client.refresh_tokens("revoked-refresh-token")

    def test_missing_client_id_raises_configuration_error(self):
        with self.assertRaises(CognitoConfigurationError):
            CognitoAuthClient(client_id="change-me")
