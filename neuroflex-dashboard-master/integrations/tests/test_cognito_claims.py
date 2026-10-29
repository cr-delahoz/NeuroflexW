import base64
import json

from django.test import SimpleTestCase

from integrations.services.cognito_claims import decode_jwt_claims


def _build_fake_jwt(claims):
    def _b64(segment):
        return base64.urlsafe_b64encode(json.dumps(segment).encode()).rstrip(b"=").decode()

    header = _b64({"alg": "RS256", "typ": "JWT"})
    payload = _b64(claims)
    return f"{header}.{payload}.fake-signature"


class DecodeJwtClaimsTests(SimpleTestCase):
    def test_extracts_sub_claim_from_valid_jwt(self):
        token = _build_fake_jwt({"sub": "abc-123-sub", "email": "user@example.com"})

        claims = decode_jwt_claims(token)

        self.assertEqual(claims["sub"], "abc-123-sub")
        self.assertEqual(claims["email"], "user@example.com")

    def test_returns_empty_dict_for_malformed_token(self):
        self.assertEqual(decode_jwt_claims("not-a-jwt"), {})

    def test_returns_empty_dict_for_empty_string(self):
        self.assertEqual(decode_jwt_claims(""), {})
