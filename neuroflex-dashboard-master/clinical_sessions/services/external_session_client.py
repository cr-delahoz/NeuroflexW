"""Client for confirming NeuroFlex VR sessions via display code against the external API."""

from __future__ import annotations

import os

from integrations.services.neuroflex_api_client import (
    NeuroflexApiClient,
    NeuroflexApiClientError,
    NeuroflexApiResponseError,
)

# TEMPORARY: local testing fixture. Set FAKE_SESSIONS=1 in the environment to
# make list_sessions_confirmed_by()/get_session_confirmed_by() return these
# hardcoded sessions instead of calling the real NeuroFlex API. Remove this
# block once the real API integration is available for testing.
_FAKE_SESSIONS = [
    {
        "session_id": "SESSION-DEMO-001",
        "display_code": "DEMO01",
        "created_at": "2026-07-08T14:30:00",
        "vr_user_email": "refipi2891@dysonc.com",
        "status": "completed",
        "metrics": {
            "TiempoRespuestaPararse": 2.1,
            "TiempoRespuestaPregunta1": 3.4,
            "TiempoRespuestaPregunta2": 2.9,
            "TiempoRespuestaPregunta3": 4.0,
            "TiempoReaccionVisual": 0.85,
            "TiempoCapturarNumero": 2.6,
        },
    },
    {
        "session_id": "SESSION-DEMO-002",
        "display_code": "DEMO02",
        "created_at": "2026-07-09T09:15:00",
        "vr_user_email": "refipi2891@dysonc.com",
        "status": "completed",
        "metrics": {
            "TiempoRespuestaPararse": 1.2,
            "TiempoRespuestaPregunta1": 1.5,
            "TiempoRespuestaPregunta2": 1.1,
            "TiempoRespuestaPregunta3": 1.8,
            "TiempoReaccionVisual": 0.4,
            "TiempoCapturarNumero": 1.3,
        },
    },
    {
        "session_id": "SESSION-DEMO-003",
        "display_code": "DEMO03",
        "created_at": "2026-07-09T16:45:00",
        "vr_user_email": "refipi2891@dysonc.com",
        "status": "confirmed",
        "metrics": {},
    },
    {
        "session_id": "SESSION-DEMO-004",
        "display_code": "DEMO04",
        "created_at": "2026-07-10T11:00:00",
        "vr_user_email": "refipi2891@dysonc.com",
        "status": "completed",
        "metrics": {
            "TiempoRespuestaPararse": 3.6,
            "TiempoRespuestaPregunta1": 4.2,
            "TiempoRespuestaPregunta2": 3.9,
            "TiempoRespuestaPregunta3": 4.5,
            "TiempoReaccionVisual": 3.1,
            "TiempoCapturarNumero": 3.8,
        },
    },
]


def _fake_sessions_enabled():
    return os.getenv("FAKE_SESSIONS") == "1"


class ExternalSessionClientError(Exception):
    """Base exception for external session confirmation errors."""


class InvalidDisplayCodeError(ExternalSessionClientError):
    """Raised when the API rejects the display code (unknown, expired or malformed)."""


class ExternalSessionServiceUnavailableError(ExternalSessionClientError):
    """Raised when the NeuroFlex API cannot be reached."""


def confirm_display_code(display_code, id_token, *, api_client=None):
    """Confirm a display code against POST /sessions/confirm and return the session detail.

    `id_token` is the specialist's own Cognito IdToken obtained at login time
    (not a shared service-account token), since the API attributes the
    confirmation to whichever operator's token made the call.

    NOTE: NeuroflexApiClient does not yet distinguish 400/404/422 responses
    (it is a generic shared client), so any NeuroflexApiResponseError is
    treated here as an invalid display code. Revisit this mapping once the
    real API documents distinguishable error bodies/status codes.
    """
    client = api_client or NeuroflexApiClient()

    try:
        response = client.post(
            "/sessions/confirm",
            token=id_token,
            json_body={"display_code": display_code},
        )
    except NeuroflexApiClientError as exc:
        if isinstance(exc, NeuroflexApiResponseError):
            raise InvalidDisplayCodeError(
                "The display code was rejected by the NeuroFlex API."
            ) from exc
        raise ExternalSessionServiceUnavailableError(
            "Could not reach the NeuroFlex API to confirm the session."
        ) from exc

    if not response or not response.get("session_id"):
        raise InvalidDisplayCodeError(
            "The NeuroFlex API did not return a confirmed session."
        )

    return response


_MAX_PAGES = 20


def list_sessions_confirmed_by(sub, id_token, *, api_client=None):
    """Return every session confirmed by `sub` via GET /sessions.

    Follows `next_cursor` until it is null, capped at `_MAX_PAGES` pages as a
    safety net against an unexpected pagination loop.
    """
    if _fake_sessions_enabled():
        return [dict(session) for session in _FAKE_SESSIONS]

    client = api_client or NeuroflexApiClient()

    sessions = []
    cursor = None
    for _ in range(_MAX_PAGES):
        params = {"confirmed_by_sub": sub}
        if cursor:
            # NOTE: the query param name for the pagination cursor is assumed
            # to be "cursor" - confirm the exact name with the API once
            # documented.
            params["cursor"] = cursor

        try:
            response = client.get("/sessions", token=id_token, params=params)
        except NeuroflexApiClientError as exc:
            raise ExternalSessionServiceUnavailableError(
                "Could not reach the NeuroFlex API to list sessions."
            ) from exc

        response = response or {}
        sessions.extend(response.get("sessions") or [])

        cursor = response.get("next_cursor")
        if not cursor:
            break

    return sessions


def get_session_confirmed_by(sub, id_token, session_id, *, api_client=None):
    """Return the session dict for `session_id` among those confirmed by `sub`.

    Returns None if no such session exists (either it does not belong to
    `sub` or it does not exist at all). Reuses list_sessions_confirmed_by;
    switch to a dedicated GET /sessions/{id} call once the API offers one.
    """
    sessions = list_sessions_confirmed_by(sub, id_token, api_client=api_client)
    return next((s for s in sessions if s.get("session_id") == session_id), None)
