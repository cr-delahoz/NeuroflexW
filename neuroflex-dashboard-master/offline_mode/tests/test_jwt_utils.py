import base64
import json
import sys
import time

from django.test import SimpleTestCase

from offline_mode.services.jwt_utils import is_id_token_valid


def _jwt(payload):
    encoded = (
        base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    )
    return f"header.{encoded}.signature"


class IsIdTokenValidTests(SimpleTestCase):
    def test_valid_token_with_future_exp(self):
        self.assertTrue(is_id_token_valid(_jwt({"exp": int(time.time()) + 3600})))

    def test_token_expiring_within_30s_margin_is_rejected(self):
        self.assertFalse(is_id_token_valid(_jwt({"exp": int(time.time()) + 10})))

    def test_expired_token_is_rejected(self):
        self.assertFalse(is_id_token_valid(_jwt({"exp": int(time.time()) - 60})))

    def test_token_without_exp_is_rejected(self):
        self.assertFalse(is_id_token_valid(_jwt({"sub": "s"})))

    def test_malformed_token_is_rejected(self):
        self.assertFalse(is_id_token_valid("no-es-un-jwt"))

    def test_empty_token_is_rejected(self):
        self.assertFalse(is_id_token_valid(""))

    def test_non_numeric_exp_is_rejected(self):
        self.assertFalse(is_id_token_valid(_jwt({"exp": "abc"})))

    def test_numeric_string_exp_is_rejected(self):
        self.assertFalse(
            is_id_token_valid(_jwt({"exp": str(int(time.time()) + 3600)}))
        )

    def test_non_finite_exp_is_rejected(self):
        # json.loads acepta NaN/Infinity: no deben romper int()
        self.assertFalse(is_id_token_valid(_jwt({"exp": float("nan")})))
        self.assertFalse(is_id_token_valid(_jwt({"exp": float("inf")})))

    def test_huge_exp_is_rejected_without_raising(self):
        # exp absurdo: 1e308, enteros > sys.maxsize y 10**400 no deben
        # lanzar OverflowError (math.isfinite/int desbordan) ni ser vigentes
        self.assertFalse(is_id_token_valid(_jwt({"exp": 1e308})))
        self.assertFalse(is_id_token_valid(_jwt({"exp": sys.maxsize + 1})))
        self.assertFalse(is_id_token_valid(_jwt({"exp": 10**400})))

    def test_non_string_token_is_rejected(self):
        self.assertFalse(is_id_token_valid(None))
        self.assertFalse(is_id_token_valid(b"header.payload.signature"))

    def test_non_dict_payload_is_rejected(self):
        encoded = (
            base64.urlsafe_b64encode(json.dumps(["not", "a", "dict"]).encode())
            .decode()
            .rstrip("=")
        )
        self.assertFalse(is_id_token_valid(f"header.{encoded}.signature"))

    def test_garbage_payload_is_rejected(self):
        self.assertFalse(is_id_token_valid("header.%%%.signature"))
