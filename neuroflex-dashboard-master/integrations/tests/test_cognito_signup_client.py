from unittest.mock import Mock, patch

import requests
from django.test import SimpleTestCase, override_settings

from integrations.services.cognito_signup_client import (
    CognitoCodeMismatchError,
    CognitoConfigurationError,
    CognitoInvalidPasswordError,
    CognitoNetworkError,
    CognitoSignUpClient,
    CognitoUserNotFoundError,
    CognitoUsernameExistsError,
)


@override_settings(COGNITO_REGION="us-east-1")
class CognitoSignUpClientTests(SimpleTestCase):
    def setUp(self):
        runtime = Mock()
        runtime.get_cognito_client_id.return_value = "test-client-id"
        self.runtime_patcher = patch(
            "integrations.services.cognito_signup_client.RuntimeConfig",
            return_value=runtime,
        )
        self.runtime_patcher.start()
        self.addCleanup(self.runtime_patcher.stop)
        self.client = CognitoSignUpClient()

    @patch("integrations.services.cognito_signup_client.requests.post")
    def test_sign_up_success(self, mock_post):
        mock_post.return_value = Mock(
            status_code=200,
            json=Mock(return_value={"UserConfirmed": False, "UserSub": "fake-sub"}),
        )

        result = self.client.sign_up("test@example.com", "fake-password")

        self.assertFalse(result)
        called_headers = mock_post.call_args.kwargs["headers"]
        self.assertEqual(
            called_headers["X-Amz-Target"],
            "AWSCognitoIdentityProviderService.SignUp",
        )
        called_json = mock_post.call_args.kwargs["json"]
        self.assertEqual(called_json["ClientId"], "test-client-id")

    @patch("integrations.services.cognito_signup_client.requests.post")
    def test_sign_up_sends_email_user_attribute(self, mock_post):
        mock_post.return_value = Mock(
            status_code=200,
            json=Mock(return_value={"UserConfirmed": False}),
        )

        self.client.sign_up("test@example.com", "fake-password", email="test@example.com")

        called_json = mock_post.call_args.kwargs["json"]
        self.assertEqual(
            called_json["UserAttributes"],
            [{"Name": "email", "Value": "test@example.com"}],
        )

    @patch("integrations.services.cognito_signup_client.requests.post")
    def test_sign_up_username_exists(self, mock_post):
        mock_post.return_value = Mock(
            status_code=400,
            json=Mock(
                return_value={
                    "__type": "UsernameExistsException",
                    "message": "User already exists.",
                }
            ),
        )

        with self.assertRaises(CognitoUsernameExistsError):
            self.client.sign_up("test@example.com", "fake-password")

    @patch("integrations.services.cognito_signup_client.requests.post")
    def test_sign_up_invalid_password(self, mock_post):
        mock_post.return_value = Mock(
            status_code=400,
            json=Mock(
                return_value={
                    "__type": "InvalidPasswordException",
                    "message": "Password does not meet requirements.",
                }
            ),
        )

        with self.assertRaises(CognitoInvalidPasswordError):
            self.client.sign_up("test@example.com", "weak")

    @patch(
        "integrations.services.cognito_signup_client.requests.post",
        side_effect=requests.exceptions.ConnectionError,
    )
    def test_sign_up_network_error_is_wrapped(self, mock_post):
        with self.assertRaises(CognitoNetworkError):
            self.client.sign_up("test@example.com", "fake-password")

    @patch("integrations.services.cognito_signup_client.requests.post")
    def test_confirm_sign_up_success(self, mock_post):
        mock_post.return_value = Mock(status_code=200, json=Mock(return_value={}))

        self.client.confirm_sign_up("test@example.com", "123456")

        called_headers = mock_post.call_args.kwargs["headers"]
        self.assertEqual(
            called_headers["X-Amz-Target"],
            "AWSCognitoIdentityProviderService.ConfirmSignUp",
        )

    @patch("integrations.services.cognito_signup_client.requests.post")
    def test_confirm_sign_up_code_mismatch(self, mock_post):
        mock_post.return_value = Mock(
            status_code=400,
            json=Mock(
                return_value={
                    "__type": "CodeMismatchException",
                    "message": "Invalid code.",
                }
            ),
        )

        with self.assertRaises(CognitoCodeMismatchError):
            self.client.confirm_sign_up("test@example.com", "000000")

    def test_missing_client_id_raises_configuration_error(self):
        with self.assertRaises(CognitoConfigurationError):
            CognitoSignUpClient(client_id="change-me")

    @patch("integrations.services.cognito_signup_client.requests.post")
    def test_change_password_success(self, mock_post):
        mock_post.return_value = Mock(status_code=200, json=Mock(return_value={}))

        self.client.change_password("fake-access-token", "old-pass", "new-pass")

        called_headers = mock_post.call_args.kwargs["headers"]
        self.assertEqual(
            called_headers["X-Amz-Target"],
            "AWSCognitoIdentityProviderService.ChangePassword",
        )
        called_json = mock_post.call_args.kwargs["json"]
        self.assertEqual(
            called_json,
            {
                "AccessToken": "fake-access-token",
                "PreviousPassword": "old-pass",
                "ProposedPassword": "new-pass",
            },
        )
        self.assertNotIn("ClientId", called_json)

    @patch("integrations.services.cognito_signup_client.requests.post")
    def test_change_password_invalid_password(self, mock_post):
        mock_post.return_value = Mock(
            status_code=400,
            json=Mock(
                return_value={
                    "__type": "InvalidPasswordException",
                    "message": "Password does not meet requirements.",
                }
            ),
        )

        with self.assertRaises(CognitoInvalidPasswordError):
            self.client.change_password("fake-access-token", "old-pass", "weak")

    @patch("integrations.services.cognito_signup_client.requests.post")
    def test_forgot_password_success(self, mock_post):
        mock_post.return_value = Mock(status_code=200, json=Mock(return_value={}))

        self.client.forgot_password("test@example.com")

        called_headers = mock_post.call_args.kwargs["headers"]
        self.assertEqual(
            called_headers["X-Amz-Target"],
            "AWSCognitoIdentityProviderService.ForgotPassword",
        )
        called_json = mock_post.call_args.kwargs["json"]
        self.assertEqual(
            called_json, {"ClientId": "test-client-id", "Username": "test@example.com"}
        )

    @patch("integrations.services.cognito_signup_client.requests.post")
    def test_forgot_password_user_not_found(self, mock_post):
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
            self.client.forgot_password("missing@example.com")

    @patch("integrations.services.cognito_signup_client.requests.post")
    def test_confirm_forgot_password_success(self, mock_post):
        mock_post.return_value = Mock(status_code=200, json=Mock(return_value={}))

        self.client.confirm_forgot_password("test@example.com", "123456", "New-pass-1!")

        called_headers = mock_post.call_args.kwargs["headers"]
        self.assertEqual(
            called_headers["X-Amz-Target"],
            "AWSCognitoIdentityProviderService.ConfirmForgotPassword",
        )
        called_json = mock_post.call_args.kwargs["json"]
        self.assertEqual(
            called_json,
            {
                "ClientId": "test-client-id",
                "Username": "test@example.com",
                "ConfirmationCode": "123456",
                "Password": "New-pass-1!",
            },
        )

    @patch("integrations.services.cognito_signup_client.requests.post")
    def test_confirm_forgot_password_code_mismatch(self, mock_post):
        mock_post.return_value = Mock(
            status_code=400,
            json=Mock(
                return_value={
                    "__type": "CodeMismatchException",
                    "message": "Invalid code.",
                }
            ),
        )

        with self.assertRaises(CognitoCodeMismatchError):
            self.client.confirm_forgot_password("test@example.com", "000000", "New-pass-1!")
