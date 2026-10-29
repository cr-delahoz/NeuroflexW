import base64
import json
from unittest.mock import patch

from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase
from django.urls import reverse

from audit.models import AuditLog
from integrations.services.cognito_auth_client import (
    CognitoAuthClientError,
    CognitoInvalidParameterError,
)

from accounts.models import CustomUser
from accounts.services import get_valid_cognito_token
from accounts.views import get_cognito_id_token_or_redirect


def _encode_segment(data):
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


def _make_id_token(exp):
    header = _encode_segment({"alg": "RS256", "typ": "JWT"})
    payload = _encode_segment({"sub": "sub-123", "exp": exp})
    return f"{header}.{payload}.signature"


_NOW = 1_700_000_000.0


class TokenRefreshTestBase(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = CustomUser.objects.create_user(
            username="specialist@example.com",
            role=CustomUser.Role.SPECIALIST,
            cognito_sub="sub-123",
        )
        time_patcher = patch("accounts.services.time.time", return_value=_NOW)
        time_patcher.start()
        self.addCleanup(time_patcher.stop)

    def _request(self, *, token=None, expires_at=None, refresh_token=None):
        request = self.factory.get("/")
        SessionMiddleware(lambda req: None).process_request(request)
        request.session.save()
        request.user = self.user
        if token:
            request.session["cognito_id_token"] = token
        if expires_at is not None:
            request.session["cognito_id_token_expires_at"] = expires_at
        if refresh_token:
            request.session["cognito_refresh_token"] = refresh_token
        return request


class GetValidCognitoTokenTests(TokenRefreshTestBase):
    def test_returns_token_when_still_valid(self):
        valid_exp = _NOW + 3600
        token = _make_id_token(valid_exp)
        request = self._request(token=token, expires_at=valid_exp)

        self.assertEqual(get_valid_cognito_token(request), token)

    def test_returns_token_when_expiry_cannot_be_determined(self):
        request = self._request(token="opaque-token")

        self.assertEqual(get_valid_cognito_token(request), "opaque-token")

    def test_returns_none_when_session_has_no_token(self):
        request = self._request()

        self.assertIsNone(get_valid_cognito_token(request))

    @patch(
        "accounts.services.CognitoAuthClient.refresh_tokens",
        return_value={
            "status": "authenticated",
            "id_token": _make_id_token(_NOW + 3600),
        },
    )
    def test_expired_token_is_refreshed(self, mock_refresh):
        expired_token = _make_id_token(_NOW - 10)
        request = self._request(
            token=expired_token, expires_at=_NOW - 10, refresh_token="stored-refresh"
        )

        result = get_valid_cognito_token(request)

        self.assertEqual(result, _make_id_token(_NOW + 3600))
        self.assertEqual(request.session["cognito_id_token"], _make_id_token(_NOW + 3600))
        self.assertIn("cognito_refresh_token", request.session)
        exp = request.session["cognito_id_token_expires_at"]
        self.assertIsInstance(exp, int)
        self.assertTrue(
            AuditLog.objects.filter(
                actor=self.user,
                action="cognito_token_refreshed",
                result=AuditLog.Result.SUCCESS,
            ).exists()
        )
        self.assertEqual(mock_refresh.call_args.args, ("stored-refresh",))

    @patch(
        "accounts.services.CognitoAuthClient.refresh_tokens",
        return_value={
            "status": "authenticated",
            "id_token": _make_id_token(_NOW + 3600),
            "access_token": "new-access-token",
        },
    )
    def test_refresh_updates_access_token_and_expiry(self, mock_refresh):
        request = self._request(
            token=_make_id_token(_NOW - 10), expires_at=_NOW - 10, refresh_token="r"
        )

        get_valid_cognito_token(request)

        self.assertEqual(request.session["cognito_access_token"], "new-access-token")
        self.assertEqual(
            request.session["cognito_id_token_expires_at"], _NOW + 3600
        )

    @patch(
        "accounts.services.CognitoAuthClient.refresh_tokens",
        side_effect=CognitoAuthClientError("cognito rejected"),
    )
    def test_refresh_failure_clears_tokens_and_audits(self, mock_refresh):
        request = self._request(
            token=_make_id_token(_NOW - 10), expires_at=_NOW - 10, refresh_token="r"
        )

        self.assertIsNone(get_valid_cognito_token(request))
        self.assertNotIn("cognito_id_token", request.session)
        self.assertNotIn("cognito_refresh_token", request.session)
        self.assertNotIn("cognito_access_token", request.session)
        self.assertNotIn("cognito_id_token_expires_at", request.session)
        self.assertTrue(
            AuditLog.objects.filter(
                actor=self.user,
                action="cognito_token_refresh_failed",
                result=AuditLog.Result.FAILURE,
            ).exists()
        )

    @patch(
        "accounts.services.CognitoAuthClient.refresh_tokens",
        side_effect=CognitoInvalidParameterError("no refresh token"),
    )
    def test_expired_token_without_refresh_token_fails_cleanly(self, mock_refresh):
        request = self._request(
            token=_make_id_token(_NOW - 10), expires_at=_NOW - 10
        )

        self.assertIsNone(get_valid_cognito_token(request))
        self.assertTrue(
            AuditLog.objects.filter(
                action="cognito_token_refresh_failed",
                result=AuditLog.Result.FAILURE,
            ).exists()
        )

    def test_anonymous_actor_is_still_audited(self):
        from django.contrib.auth.models import AnonymousUser

        request = self._request(token=_make_id_token(_NOW - 10), expires_at=_NOW - 10)
        request.session["cognito_refresh_token"] = "r"
        request.user = AnonymousUser()

        with patch(
            "accounts.services.CognitoAuthClient.refresh_tokens",
            return_value={"status": "authenticated", "id_token": "new-id-token"},
        ):
            self.assertEqual(get_valid_cognito_token(request), "new-id-token")
        logged = AuditLog.objects.filter(action="cognito_token_refreshed").get()
        self.assertIsNone(logged.actor)


class CognitoIdTokenOrRedirectTests(TokenRefreshTestBase):
    def _with_messages(self, request):
        setattr(request, "session", request.session)
        messages_storage = FallbackStorage(request)
        setattr(request, "_messages", messages_storage)
        return request

    @patch(
        "accounts.services.CognitoAuthClient.refresh_tokens",
        return_value={"status": "authenticated", "id_token": "fresh-token"},
    )
    def test_expired_token_is_refreshed_instead_of_redirecting(self, mock_refresh):
        request = self._request(
            token=_make_id_token(_NOW - 10), expires_at=_NOW - 10, refresh_token="r"
        )
        request = self._with_messages(request)

        result = get_cognito_id_token_or_redirect(request)

        self.assertEqual(result, "fresh-token")

    @patch(
        "accounts.services.CognitoAuthClient.refresh_tokens",
        side_effect=CognitoAuthClientError("cognito down"),
    )
    def test_unrefreshable_token_redirects_to_login(self, mock_refresh):
        request = self._request(
            token=_make_id_token(_NOW - 10), expires_at=_NOW - 10, refresh_token="r"
        )
        request = self._with_messages(request)

        response = get_cognito_id_token_or_redirect(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("accounts:login"))
