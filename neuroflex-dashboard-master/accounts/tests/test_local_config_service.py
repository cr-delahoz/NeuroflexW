import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from dotenv import dotenv_values
from django.test import SimpleTestCase

from accounts.local_config_service import (
    LocalConfigValidationError,
    mask_token,
    read_config,
    write_config,
)
from integrations.services.runtime_config import RuntimeConfig


VALID_GITHUB_TOKEN = "github" + "a" * 64


class MaskTokenTests(SimpleTestCase):
    def test_masks_all_but_last_four(self):
        token = "github" + "b" * 64
        self.assertEqual(mask_token(token), "•" * 66 + "bbbb")

    def test_masks_valid_length_token(self):
        self.assertEqual(mask_token(VALID_GITHUB_TOKEN), "•" * 66 + "aaaa")

    def test_empty_token_returns_empty(self):
        self.assertEqual(mask_token(""), "")

    def test_single_character_token_shows_last_character(self):
        self.assertEqual(mask_token("a"), "a")


class LocalConfigServiceTests(SimpleTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env_dir = Path(self.tmp.name)
        self.env_patcher = patch.dict(
            os.environ, {"NEUROFLEX_DATA_DIR": str(self.env_dir)}, clear=True
        )
        self.env_patcher.start()
        self.addCleanup(self.env_patcher.stop)
        self.base_dir_patcher = patch(
            "integrations.services.runtime_config.BASE_DIR",
            self.env_dir / "base",
        )
        self.base_dir_patcher.start()
        self.addCleanup(self.base_dir_patcher.stop)
        RuntimeConfig._instance = None
        self.addCleanup(setattr, RuntimeConfig, "_instance", None)

    def _write_dotenv(self, values):
        (self.env_dir / ".env").write_text(
            "\n".join(f"{key}={value}" for key, value in values.items()) + "\n",
            encoding="utf-8",
        )

    def test_read_config_masks_token(self):
        self._write_dotenv(
            {
                "NEUROFLEX_API_BASE_URL": "https://api.example.com",
                "COGNITO_CLIENT_ID": "client-123",
                "GITHUB_TOKEN": VALID_GITHUB_TOKEN,
            }
        )
        self.assertEqual(
            read_config(),
            {
                "NEUROFLEX_API_BASE_URL": "https://api.example.com",
                "COGNITO_CLIENT_ID": "client-123",
                "GITHUB_TOKEN": "•" * 66 + "aaaa",
            },
        )

    def test_write_config_persists_and_returns_masked(self):
        result = write_config(
            {
                "NEUROFLEX_API_BASE_URL": "https://api.example.com",
                "COGNITO_CLIENT_ID": "client-123",
                "GITHUB_TOKEN": VALID_GITHUB_TOKEN,
            }
        )
        self.assertEqual(
            result,
            {
                "NEUROFLEX_API_BASE_URL": "https://api.example.com",
                "COGNITO_CLIENT_ID": "client-123",
                "GITHUB_TOKEN": "•" * 66 + "aaaa",
            },
        )
        self.assertEqual(
            dotenv_values(self.env_dir / ".env")["GITHUB_TOKEN"], VALID_GITHUB_TOKEN
        )

    def test_write_config_preserves_other_variables(self):
        self._write_dotenv({"DJANGO_SECRET_KEY": "keep-me", "COGNITO_CLIENT_ID": "old"})
        write_config(
            {
                "NEUROFLEX_API_BASE_URL": "https://api.example.com",
                "COGNITO_CLIENT_ID": "client-123",
                "GITHUB_TOKEN": VALID_GITHUB_TOKEN,
            }
        )
        self.assertEqual(dotenv_values(self.env_dir / ".env")["DJANGO_SECRET_KEY"], "keep-me")

    def test_write_config_rejects_unknown_keys(self):
        with self.assertRaises(LocalConfigValidationError):
            write_config({"SECRET_EXTRA": "x"})

    def test_write_config_rejects_values_with_newline(self):
        values = {
            "NEUROFLEX_API_BASE_URL": "https://api.example.com",
            "COGNITO_CLIENT_ID": "client-123",
            "GITHUB_TOKEN": VALID_GITHUB_TOKEN,
        }
        for key in values:
            with self.subTest(key=key):
                invalid_values = values.copy()
                invalid_values[key] += "\nextra"
                with self.assertRaisesMessage(
                    LocalConfigValidationError,
                    "El valor no puede contener saltos de línea.",
                ):
                    write_config(invalid_values)

    def test_write_config_rejects_values_with_carriage_return(self):
        values = {
            "NEUROFLEX_API_BASE_URL": "https://api.example.com",
            "COGNITO_CLIENT_ID": "client-123",
            "GITHUB_TOKEN": VALID_GITHUB_TOKEN,
        }
        for key in values:
            with self.subTest(key=key):
                invalid_values = values.copy()
                invalid_values[key] += "\rextra"
                with self.assertRaisesMessage(
                    LocalConfigValidationError,
                    "El valor no puede contener saltos de línea.",
                ):
                    write_config(invalid_values)

    def test_write_config_rejects_non_string_keys(self):
        with self.assertRaisesMessage(
            LocalConfigValidationError,
            "Las claves deben ser cadenas de texto.",
        ):
            write_config({1: "unexpected"})

    def test_write_config_rejects_empty_values(self):
        with self.assertRaises(LocalConfigValidationError):
            write_config(
                {
                    "NEUROFLEX_API_BASE_URL": "",
                    "COGNITO_CLIENT_ID": "client-123",
                    "GITHUB_TOKEN": VALID_GITHUB_TOKEN,
                }
            )

    def test_write_config_rejects_masked_token(self):
        with self.assertRaises(LocalConfigValidationError):
            write_config(
                {
                    "NEUROFLEX_API_BASE_URL": "https://api.example.com",
                    "COGNITO_CLIENT_ID": "client-123",
                    "GITHUB_TOKEN": "•" * 66 + "aaaa",
                }
            )

    def test_write_config_rejects_invalid_url(self):
        with self.assertRaises(LocalConfigValidationError):
            write_config(
                {
                    "NEUROFLEX_API_BASE_URL": "not-a-url",
                    "COGNITO_CLIENT_ID": "client-123",
                    "GITHUB_TOKEN": VALID_GITHUB_TOKEN,
                }
            )

    def test_write_config_rejects_url_without_hostname(self):
        with self.assertRaises(LocalConfigValidationError):
            write_config(
                {
                    "NEUROFLEX_API_BASE_URL": "http://:80",
                    "COGNITO_CLIENT_ID": "client-123",
                    "GITHUB_TOKEN": VALID_GITHUB_TOKEN,
                }
            )

    def test_write_config_rejects_url_with_invalid_port(self):
        with self.assertRaises(LocalConfigValidationError):
            write_config(
                {
                    "NEUROFLEX_API_BASE_URL": "https://api.example.com:invalid",
                    "COGNITO_CLIENT_ID": "client-123",
                    "GITHUB_TOKEN": VALID_GITHUB_TOKEN,
                }
            )

    def test_write_config_rejects_non_http_scheme(self):
        with self.assertRaises(LocalConfigValidationError):
            write_config(
                {
                    "NEUROFLEX_API_BASE_URL": "ftp://api.example.com",
                    "COGNITO_CLIENT_ID": "client-123",
                    "GITHUB_TOKEN": VALID_GITHUB_TOKEN,
                }
            )

    def test_write_config_rejects_missing_required_key(self):
        with self.assertRaises(LocalConfigValidationError):
            write_config(
                {
                    "COGNITO_CLIENT_ID": "client-123",
                    "GITHUB_TOKEN": VALID_GITHUB_TOKEN,
                }
            )

    def test_write_config_omitted_token_preserves_existing(self):
        write_config(
            {
                "NEUROFLEX_API_BASE_URL": "https://api.example.com",
                "COGNITO_CLIENT_ID": "client-123",
                "GITHUB_TOKEN": VALID_GITHUB_TOKEN,
            }
        )
        result = write_config(
            {
                "NEUROFLEX_API_BASE_URL": "https://api.example.com",
                "COGNITO_CLIENT_ID": "client-123",
            }
        )
        self.assertEqual(result["GITHUB_TOKEN"], "•" * 66 + "aaaa")
        self.assertEqual(dotenv_values(self.env_dir / ".env")["GITHUB_TOKEN"], VALID_GITHUB_TOKEN)

    def test_write_config_rejects_omitted_token_when_none_exists(self):
        with self.assertRaisesMessage(LocalConfigValidationError, "Este campo es obligatorio."):
            write_config(
                {
                    "NEUROFLEX_API_BASE_URL": "https://api.example.com",
                    "COGNITO_CLIENT_ID": "client-123",
                }
            )

    def test_write_config_rejects_69_character_token(self):
        with self.assertRaisesMessage(
            LocalConfigValidationError,
            "El token debe tener al menos 70 caracteres.",
        ):
            write_config(
                {
                    "NEUROFLEX_API_BASE_URL": "https://api.example.com",
                    "COGNITO_CLIENT_ID": "client-123",
                    "GITHUB_TOKEN": "github" + "a" * 63,
                }
            )

    def test_write_config_rejects_existing_69_character_token(self):
        self._write_dotenv(
            {
                "NEUROFLEX_API_BASE_URL": "https://api.example.com",
                "COGNITO_CLIENT_ID": "client-123",
                "GITHUB_TOKEN": "github" + "a" * 63,
            }
        )
        with self.assertRaisesMessage(
            LocalConfigValidationError,
            "El token debe tener al menos 70 caracteres.",
        ):
            write_config(
                {
                    "NEUROFLEX_API_BASE_URL": "https://api.example.com",
                    "COGNITO_CLIENT_ID": "client-123",
                }
            )
