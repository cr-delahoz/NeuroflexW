"""Raw HTTPS client for AWS Cognito SignUp / ConfirmSignUp (self-service registration).

Uses the public App Client (COGNITO_CLIENT_ID) only - no AWS IAM credentials
and no AdminCreateUser/AdminConfirmSignUp administrative APIs are involved.
"""

from __future__ import annotations

import requests
from django.conf import settings

from integrations.services.runtime_config import RuntimeConfig


class CognitoSignUpClientError(Exception):
    """Base exception for Cognito self-service registration errors."""


class CognitoConfigurationError(CognitoSignUpClientError):
    """Raised when required Cognito settings are missing or invalid."""


class CognitoNetworkError(CognitoSignUpClientError):
    """Raised when the request to Cognito fails at the network/transport level."""


class CognitoUsernameExistsError(CognitoSignUpClientError):
    """Raised when the username is already registered in the Cognito user pool."""


class CognitoInvalidPasswordError(CognitoSignUpClientError):
    """Raised when the password does not meet the user pool's password policy."""


class CognitoInvalidParameterError(CognitoSignUpClientError):
    """Raised when Cognito rejects the request shape itself."""


class CognitoCodeMismatchError(CognitoSignUpClientError):
    """Raised when the confirmation code does not match."""


class CognitoExpiredCodeError(CognitoSignUpClientError):
    """Raised when the confirmation code has expired."""


class CognitoUserNotFoundError(CognitoSignUpClientError):
    """Raised when Cognito reports the user does not exist."""


class CognitoUserNotConfirmedError(CognitoSignUpClientError):
    """Raised when the account exists in Cognito but was never confirmed."""


class CognitoNotAuthorizedError(CognitoSignUpClientError):
    """Raised when Cognito rejects the provided credentials/token."""


class CognitoLimitExceededError(CognitoSignUpClientError):
    """Raised when Cognito's attempt/request rate limit has been exceeded."""


class CognitoServiceError(CognitoSignUpClientError):
    """Raised when Cognito returns an unexpected or unmapped error response."""


class CognitoInvalidResponseError(CognitoSignUpClientError):
    """Raised when a successful Cognito response cannot be parsed as expected."""


_TIMEOUT_SECONDS = 10

_SIGN_UP_ERROR_TYPE_MAP = {
    "UsernameExistsException": CognitoUsernameExistsError,
    "InvalidPasswordException": CognitoInvalidPasswordError,
    "InvalidParameterException": CognitoInvalidParameterError,
}

_CONFIRM_SIGN_UP_ERROR_TYPE_MAP = {
    "CodeMismatchException": CognitoCodeMismatchError,
    "ExpiredCodeException": CognitoExpiredCodeError,
    "UserNotFoundException": CognitoUserNotFoundError,
    "InvalidParameterException": CognitoInvalidParameterError,
}

_CHANGE_PASSWORD_ERROR_TYPE_MAP = {
    "InvalidPasswordException": CognitoInvalidPasswordError,
    "NotAuthorizedException": CognitoNotAuthorizedError,
    "LimitExceededException": CognitoLimitExceededError,
}

_FORGOT_PASSWORD_ERROR_TYPE_MAP = {
    "UserNotFoundException": CognitoUserNotFoundError,
    "UserNotConfirmedException": CognitoUserNotConfirmedError,
    "InvalidParameterException": CognitoInvalidParameterError,
    "NotAuthorizedException": CognitoNotAuthorizedError,
    "LimitExceededException": CognitoLimitExceededError,
}

_CONFIRM_FORGOT_PASSWORD_ERROR_TYPE_MAP = {
    "CodeMismatchException": CognitoCodeMismatchError,
    "ExpiredCodeException": CognitoExpiredCodeError,
    "UserNotFoundException": CognitoUserNotFoundError,
    "InvalidPasswordException": CognitoInvalidPasswordError,
    "InvalidParameterException": CognitoInvalidParameterError,
    "LimitExceededException": CognitoLimitExceededError,
}


class CognitoSignUpClient:
    """Register and confirm NeuroFlex users in Cognito via the public App Client."""

    def __init__(self, region=None, client_id=None):
        self.region = region or settings.COGNITO_REGION
        self.client_id = client_id or RuntimeConfig().get_cognito_client_id()
        if not self.client_id or self.client_id == "change-me":
            raise CognitoConfigurationError("COGNITO_CLIENT_ID is not configured.")

    def _endpoint(self):
        return f"https://cognito-idp.{self.region}.amazonaws.com/"

    def _post(self, target, payload):
        try:
            response = requests.post(
                self._endpoint(),
                json=payload,
                headers={
                    "Content-Type": "application/x-amz-json-1.1",
                    "X-Amz-Target": f"AWSCognitoIdentityProviderService.{target}",
                },
                timeout=_TIMEOUT_SECONDS,
            )
        except requests.exceptions.RequestException as exc:
            raise CognitoNetworkError(
                "Could not reach the Cognito registration service."
            ) from exc

        try:
            body = response.json()
        except ValueError as exc:
            raise CognitoInvalidResponseError(
                "Cognito returned an unreadable response."
            ) from exc

        return response.status_code, body

    def sign_up(self, username, password, email=None):
        """Register a new user in Cognito. Returns True if already confirmed.

        `email` is sent as a UserAttribute so Cognito emails the confirmation
        code to it; defaults to `username` since usernames are email
        addresses in this project.
        """
        status_code, body = self._post(
            "SignUp",
            {
                "ClientId": self.client_id,
                "Username": username,
                "Password": password,
                "UserAttributes": [{"Name": "email", "Value": email or username}],
            },
        )

        if status_code >= 400:
            self._raise_for_error_body(body, _SIGN_UP_ERROR_TYPE_MAP)

        return bool(body.get("UserConfirmed"))

    def confirm_sign_up(self, username, confirmation_code):
        """Confirm a previously registered user with the code sent by Cognito."""
        status_code, body = self._post(
            "ConfirmSignUp",
            {
                "ClientId": self.client_id,
                "Username": username,
                "ConfirmationCode": confirmation_code,
            },
        )

        if status_code >= 400:
            self._raise_for_error_body(body, _CONFIRM_SIGN_UP_ERROR_TYPE_MAP)

    def change_password(self, access_token, previous_password, proposed_password):
        """Change a signed-in user's password. Does not take a ClientId."""
        status_code, body = self._post(
            "ChangePassword",
            {
                "AccessToken": access_token,
                "PreviousPassword": previous_password,
                "ProposedPassword": proposed_password,
            },
        )

        if status_code >= 400:
            self._raise_for_error_body(body, _CHANGE_PASSWORD_ERROR_TYPE_MAP)

    def forgot_password(self, username):
        """Trigger Cognito to email a password-recovery code to `username`.

        Used when an already-confirmed specialist forgot their password.
        Unlike sign_up, this never needs a bootstrap password - Cognito lets
        the user set their next password directly via confirm_forgot_password.
        """
        status_code, body = self._post(
            "ForgotPassword",
            {
                "ClientId": self.client_id,
                "Username": username,
            },
        )

        if status_code >= 400:
            self._raise_for_error_body(body, _FORGOT_PASSWORD_ERROR_TYPE_MAP)

    def confirm_forgot_password(self, username, confirmation_code, new_password):
        """Set a new password directly using the code sent by forgot_password.

        No previous/temporary password is required, unlike change_password.
        """
        status_code, body = self._post(
            "ConfirmForgotPassword",
            {
                "ClientId": self.client_id,
                "Username": username,
                "ConfirmationCode": confirmation_code,
                "Password": new_password,
            },
        )

        if status_code >= 400:
            self._raise_for_error_body(body, _CONFIRM_FORGOT_PASSWORD_ERROR_TYPE_MAP)

    def _raise_for_error_body(self, body, error_type_map):
        error_type = (body.get("__type") or "").rsplit("#", 1)[-1]
        message = body.get("message") or "Cognito rejected the request."
        exception_class = error_type_map.get(error_type, CognitoServiceError)
        raise exception_class(message)
