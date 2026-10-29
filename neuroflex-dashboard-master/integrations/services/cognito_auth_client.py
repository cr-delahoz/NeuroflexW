"""Raw HTTPS client for AWS Cognito InitiateAuth (USER_PASSWORD_AUTH)."""

from __future__ import annotations

import json

import requests
from django.conf import settings

from integrations.services.runtime_config import RuntimeConfig


class CognitoAuthClientError(Exception):
    """Base exception for Cognito authentication errors."""


class CognitoConfigurationError(CognitoAuthClientError):
    """Raised when required Cognito settings are missing or invalid."""


class CognitoNetworkError(CognitoAuthClientError):
    """Raised when the request to Cognito fails at the network/transport level."""


class CognitoInvalidCredentialsError(CognitoAuthClientError):
    """Raised when Cognito rejects the provided username/password."""


class CognitoUserNotFoundError(CognitoAuthClientError):
    """Raised when Cognito reports the user does not exist."""


class CognitoInvalidParameterError(CognitoAuthClientError):
    """Raised when Cognito rejects the request shape itself."""


class CognitoServiceError(CognitoAuthClientError):
    """Raised when Cognito returns an unexpected or unmapped error response."""


class CognitoInvalidResponseError(CognitoAuthClientError):
    """Raised when a successful Cognito response cannot be parsed as expected."""


_TIMEOUT_SECONDS = 10

_ERROR_TYPE_MAP = {
    "NotAuthorizedException": CognitoInvalidCredentialsError,
    "UserNotFoundException": CognitoUserNotFoundError,
    "InvalidParameterException": CognitoInvalidParameterError,
}


class CognitoAuthClient:
    """Authenticate NeuroFlex users against AWS Cognito with USER_PASSWORD_AUTH."""

    def __init__(self, region=None, client_id=None):
        self.region = region or settings.COGNITO_REGION
        self.client_id = client_id or RuntimeConfig().get_cognito_client_id()
        if not self.client_id or self.client_id == "change-me":
            raise CognitoConfigurationError("COGNITO_CLIENT_ID is not configured.")

    def _endpoint(self):
        return f"https://cognito-idp.{self.region}.amazonaws.com/"

    def initiate_auth(self, username, password):
        """Exchange a username/password for Cognito tokens.

        Returns a dict with id_token, access_token, refresh_token and
        expires_in. Raises a CognitoAuthClientError subclass otherwise.
        """
        payload = {
            "AuthFlow": "USER_PASSWORD_AUTH",
            "AuthParameters": {
                "USERNAME": username,
                "PASSWORD": password,
            },
            "ClientId": self.client_id,
        }

        return self._post_auth(
            payload,
            "AWSCognitoIdentityProviderService.InitiateAuth",
            username,
        )

    def refresh_tokens(self, refresh_token):
        """Exchange a Cognito refresh token for fresh id/access tokens.

        Cognito does not return a new refresh token in this flow; the
        original refresh token remains valid until it expires.
        """
        if not isinstance(refresh_token, str) or not refresh_token:
            raise CognitoInvalidParameterError("A refresh token is required.")

        payload = {
            "AuthFlow": "REFRESH_TOKEN_AUTH",
            "AuthParameters": {
                "REFRESH_TOKEN": refresh_token,
            },
            "ClientId": self.client_id,
        }

        result = self._post_auth(
            payload,
            "AWSCognitoIdentityProviderService.InitiateAuth",
        )
        if result.get("status") != "authenticated" or not result.get("id_token"):
            raise CognitoInvalidResponseError(
                "Cognito refresh response did not include tokens."
            )
        return result

    def respond_to_new_password_challenge(
        self, username, new_password, session, required_attributes
    ):
        responses = {"USERNAME": username, "NEW_PASSWORD": new_password}
        for attribute in required_attributes:
            if attribute != "email":
                raise CognitoInvalidResponseError(
                    "Cognito requires an unsupported attribute."
                )
        if "email" in required_attributes:
            responses["userAttributes.email"] = username
        return self._post_auth(
            {
                "ChallengeName": "NEW_PASSWORD_REQUIRED",
                "ChallengeResponses": responses,
                "ClientId": self.client_id,
                "Session": session,
            },
            "AWSCognitoIdentityProviderService.RespondToAuthChallenge",
        )

    def _post_auth(self, payload, target, username=None):
        try:
            response = requests.post(
                self._endpoint(),
                json=payload,
                headers={
                    "Content-Type": "application/x-amz-json-1.1",
                    "X-Amz-Target": target,
                },
                timeout=_TIMEOUT_SECONDS,
            )
        except requests.exceptions.RequestException as exc:
            raise CognitoNetworkError(
                "Could not reach the Cognito authentication service."
            ) from exc

        try:
            body = response.json()
        except ValueError as exc:
            raise CognitoInvalidResponseError(
                "Cognito returned an unreadable response."
            ) from exc

        if response.status_code >= 400:
            self._raise_for_error_body(body)

        return self._parse_success_body(body, username)

    def _raise_for_error_body(self, body):
        error_type = (body.get("__type") or "").rsplit("#", 1)[-1]
        message = body.get("message") or "Cognito rejected the authentication request."
        exception_class = _ERROR_TYPE_MAP.get(error_type, CognitoServiceError)
        raise exception_class(message)

    def _parse_success_body(self, body, username=None):
        if body.get("ChallengeName") == "NEW_PASSWORD_REQUIRED":
            session = body.get("Session")
            if not session or not username:
                raise CognitoInvalidResponseError(
                    "Cognito challenge response is incomplete."
                )
            required_attributes = body.get("ChallengeParameters", {}).get(
                "requiredAttributes", "[]"
            )
            try:
                required_attributes = json.loads(required_attributes)
            except (TypeError, ValueError) as exc:
                raise CognitoInvalidResponseError(
                    "Cognito challenge attributes are invalid."
                ) from exc
            if not isinstance(required_attributes, list) or not all(
                isinstance(attribute, str) for attribute in required_attributes
            ):
                raise CognitoInvalidResponseError(
                    "Cognito challenge attributes are invalid."
                )
            return {
                "status": "new_password_required",
                "session": session,
                "username": username,
                "required_attributes": required_attributes,
            }

        result = body.get("AuthenticationResult")
        if not isinstance(result, dict) or not result.get("IdToken"):
            raise CognitoInvalidResponseError(
                "Cognito response did not include a valid AuthenticationResult."
            )

        return {
            "status": "authenticated",
            "id_token": result.get("IdToken"),
            "access_token": result.get("AccessToken"),
            "refresh_token": result.get("RefreshToken"),
            "expires_in": result.get("ExpiresIn"),
        }
