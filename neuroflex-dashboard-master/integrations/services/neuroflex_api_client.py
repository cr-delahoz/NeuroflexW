"""Generic thin REST client for the future NeuroFlex API."""

from __future__ import annotations

import requests

from integrations.services.runtime_config import RuntimeConfig


class NeuroflexApiClientError(Exception):
    """Base exception for NeuroFlex API client errors."""


class NeuroflexApiConfigurationError(NeuroflexApiClientError):
    """Raised when required API client settings are missing or invalid."""


class NeuroflexApiNetworkError(NeuroflexApiClientError):
    """Raised when a request to the NeuroFlex API fails at the transport level."""


class NeuroflexApiResponseError(NeuroflexApiClientError):
    """Raised when the NeuroFlex API returns a non-2xx status code."""

    def __init__(self, message, *, status_code=None, payload=None, text=None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload
        self.text = text


class NeuroflexApiInvalidResponseError(NeuroflexApiClientError):
    """Raised when a successful response body cannot be parsed as JSON."""


_TIMEOUT_SECONDS = 10


class NeuroflexApiClient:
    """Endpoint-agnostic REST wrapper shared by future session/terms integrations."""

    def __init__(self, base_url=None):
        self.base_url = base_url or RuntimeConfig().get_neuroflex_api_base_url()
        if not self.base_url or self.base_url == "change-me":
            raise NeuroflexApiConfigurationError(
                "NEUROFLEX_API_BASE_URL is not configured."
            )

    def get(self, path, token=None, params=None):
        return self._request("GET", path, token=token, params=params)

    def post(self, path, token=None, json_body=None):
        return self._request("POST", path, token=token, json_body=json_body)

    def post_with_response(self, path, token=None, json_body=None):
        """Return the raw successful response, including its HTTP status."""
        return self._request(
            "POST", path, token=token, json_body=json_body, return_response=True
        )

    def patch(self, path, token=None, json_body=None):
        return self._request("PATCH", path, token=token, json_body=json_body)

    def delete(self, path, token=None, params=None):
        return self._request("DELETE", path, token=token, params=params)

    def _url(self, path):
        return f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"

    def _headers(self, token):
        return {"Authorization": f"Bearer {token}"} if token else {}

    def _request(
        self,
        method,
        path,
        token=None,
        params=None,
        json_body=None,
        return_response=False,
    ):
        try:
            response = requests.request(
                method,
                self._url(path),
                headers=self._headers(token),
                params=params,
                json=json_body,
                timeout=_TIMEOUT_SECONDS,
            )
        except requests.exceptions.RequestException as exc:
            raise NeuroflexApiNetworkError(
                f"Could not reach the NeuroFlex API at '{path}'."
            ) from exc

        if response.status_code >= 400:
            try:
                payload = response.json()
            except ValueError:
                payload = None
            raise NeuroflexApiResponseError(
                f"NeuroFlex API returned status {response.status_code} for '{path}'.",
                status_code=response.status_code,
                payload=payload,
                text=response.text,
            )

        if return_response:
            return response

        if not response.content:
            return None

        try:
            return response.json()
        except ValueError as exc:
            raise NeuroflexApiInvalidResponseError(
                f"NeuroFlex API returned an unreadable response for '{path}'."
            ) from exc
