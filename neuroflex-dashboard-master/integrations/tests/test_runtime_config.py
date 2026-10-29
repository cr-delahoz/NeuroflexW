import os
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

from dotenv import dotenv_values
from django.test import SimpleTestCase

from integrations.services.runtime_config import RuntimeConfig, resolve_dotenv_path


VALID_GITHUB_TOKEN = "g" * 70


class RuntimeConfigTests(SimpleTestCase):
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

    def test_resolve_dotenv_path_uses_data_dir_when_set(self):
        self.assertEqual(resolve_dotenv_path(), self.env_dir / ".env")

    def test_initializes_from_resolved_dotenv(self):
        self._write_dotenv(
            {
                "NEUROFLEX_API_BASE_URL": "https://api.example.com",
                "COGNITO_CLIENT_ID": "client-123",
                "GITHUB_TOKEN": "secret-token",
            }
        )
        config = RuntimeConfig()
        self.assertEqual(config.get_neuroflex_api_base_url(), "https://api.example.com")
        self.assertEqual(config.get_cognito_client_id(), "client-123")
        self.assertEqual(config.get_github_token(), "secret-token")

    def test_environment_values_take_precedence_over_dotenv(self):
        self._write_dotenv(
            {
                "NEUROFLEX_API_BASE_URL": "https://file.example.com",
                "COGNITO_CLIENT_ID": "file-client",
                "GITHUB_TOKEN": "file-token",
            }
        )
        with patch.dict(
            os.environ,
            {
                "NEUROFLEX_API_BASE_URL": "https://environment.example.com",
                "COGNITO_CLIENT_ID": "environment-client",
                "GITHUB_TOKEN": "environment-token",
            },
        ):
            config = RuntimeConfig()

        self.assertEqual(
            config.get_neuroflex_api_base_url(), "https://environment.example.com"
        )
        self.assertEqual(config.get_cognito_client_id(), "environment-client")
        self.assertEqual(config.get_github_token(), "environment-token")

    def test_empty_environment_values_fall_back_to_dotenv(self):
        self._write_dotenv(
            {
                "NEUROFLEX_API_BASE_URL": "https://file.example.com",
                "COGNITO_CLIENT_ID": "file-client",
                "GITHUB_TOKEN": "file-token",
            }
        )
        with patch.dict(
            os.environ,
            {
                "NEUROFLEX_API_BASE_URL": "",
                "COGNITO_CLIENT_ID": "",
                "GITHUB_TOKEN": "",
            },
        ):
            config = RuntimeConfig()

        self.assertEqual(config.get_neuroflex_api_base_url(), "https://file.example.com")
        self.assertEqual(config.get_cognito_client_id(), "file-client")
        self.assertEqual(config.get_github_token(), "file-token")

    def test_defaults_when_dotenv_missing(self):
        config = RuntimeConfig()
        self.assertEqual(config.get_neuroflex_api_base_url(), "change-me")
        self.assertEqual(config.get_cognito_client_id(), "change-me")
        self.assertEqual(config.get_github_token(), "")

    def test_singleton_returns_same_instance(self):
        self.assertIs(RuntimeConfig(), RuntimeConfig())

    def test_singleton_does_not_publish_before_initialization_finishes(self):
        initialization_started = threading.Event()
        allow_initialization = threading.Event()
        second_call_finished = threading.Event()
        original_initialize = RuntimeConfig._initialize

        def blocked_initialize(config):
            initialization_started.set()
            self.assertTrue(allow_initialization.wait(timeout=1))
            original_initialize(config)

        first_call = threading.Thread(
            target=RuntimeConfig,
            kwargs={},
        )
        with patch.object(RuntimeConfig, "_initialize", blocked_initialize):
            first_call.start()
            self.assertTrue(initialization_started.wait(timeout=1))

            def call_singleton():
                RuntimeConfig()
                second_call_finished.set()

            second_call = threading.Thread(target=call_singleton)
            second_call.start()
            time.sleep(0.05)
            self.assertFalse(second_call_finished.is_set())

            allow_initialization.set()
            first_call.join(timeout=1)
            second_call.join(timeout=1)

        self.assertFalse(first_call.is_alive())
        self.assertFalse(second_call.is_alive())
        self.assertIsNotNone(RuntimeConfig()._values)
        self.assertIsNotNone(RuntimeConfig()._update_lock)

    def test_update_writes_dotenv_then_updates_memory(self):
        config = RuntimeConfig()
        result = config.update({"NEUROFLEX_API_BASE_URL": "https://new.example.com"})
        self.assertEqual(result["NEUROFLEX_API_BASE_URL"], "https://new.example.com")
        self.assertEqual(config.get_neuroflex_api_base_url(), "https://new.example.com")
        self.assertEqual(
            dotenv_values(self.env_dir / ".env")["NEUROFLEX_API_BASE_URL"],
            "https://new.example.com",
        )

    def test_update_replaces_environment_value_in_memory(self):
        with patch.dict(
            os.environ,
            {"COGNITO_CLIENT_ID": "environment-client"},
        ):
            config = RuntimeConfig()
            result = config.update({"COGNITO_CLIENT_ID": "file-client"})

        self.assertEqual(
            dotenv_values(self.env_dir / ".env")["COGNITO_CLIENT_ID"],
            "file-client",
        )
        self.assertEqual(result["COGNITO_CLIENT_ID"], "file-client")
        self.assertEqual(config.get_cognito_client_id(), "file-client")

    def test_update_refreshes_environment_values_for_all_editable_keys(self):
        with patch.dict(
            os.environ,
            {
                "NEUROFLEX_API_BASE_URL": "old-url",
                "COGNITO_CLIENT_ID": "old-client",
                "GITHUB_TOKEN": "old-token",
            },
        ):
            config = RuntimeConfig()
            config.update(
                {
                    "NEUROFLEX_API_BASE_URL": "new-url",
                    "COGNITO_CLIENT_ID": "new-client",
                    "GITHUB_TOKEN": VALID_GITHUB_TOKEN,
                }
            )

            self.assertEqual(config._values["NEUROFLEX_API_BASE_URL"], "new-url")
            self.assertEqual(config._values["COGNITO_CLIENT_ID"], "new-client")
            self.assertEqual(config._values["GITHUB_TOKEN"], VALID_GITHUB_TOKEN)
            self.assertEqual(os.environ["NEUROFLEX_API_BASE_URL"], "old-url")
            self.assertEqual(os.environ["COGNITO_CLIENT_ID"], "old-client")
            self.assertEqual(os.environ["GITHUB_TOKEN"], "old-token")

    def test_update_rejects_github_token_shorter_than_70_characters(self):
        config = RuntimeConfig()

        with self.assertRaises(ValueError):
            config.update({"GITHUB_TOKEN": "g" * 69})

        self.assertEqual(config.get_github_token(), "")
        self.assertFalse((self.env_dir / ".env").exists())

    def test_update_waits_for_update_lock_and_keeps_memory_consistent(self):
        config = RuntimeConfig()
        update_started = threading.Event()
        update_finished = threading.Event()

        config._update_lock.acquire()

        def update_config():
            update_started.set()
            config.update({"COGNITO_CLIENT_ID": "client-123"})
            update_finished.set()

        worker = threading.Thread(target=update_config)
        worker.start()
        self.assertTrue(update_started.wait(timeout=1))
        time.sleep(0.05)
        self.assertFalse(update_finished.is_set())

        config._update_lock.release()
        worker.join(timeout=1)

        self.assertTrue(update_finished.is_set())
        self.assertEqual(config.get_cognito_client_id(), "client-123")
        self.assertEqual(
            dotenv_values(self.env_dir / ".env")["COGNITO_CLIENT_ID"], "client-123"
        )

    def test_update_preserves_other_dotenv_variables(self):
        self._write_dotenv({"DJANGO_SECRET_KEY": "keep-me"})
        RuntimeConfig().update({"COGNITO_CLIENT_ID": "client-123"})
        self.assertEqual(
            dotenv_values(self.env_dir / ".env")["DJANGO_SECRET_KEY"], "keep-me"
        )

    def test_update_preserves_formatting_of_unrelated_special_value(self):
        original = (
            '# Keep this comment\n'
            'DJANGO_SECRET_KEY="value with spaces # and \\"quotes\\""\n'
            'DJANGO_DEBUG=True\n'
        )
        (self.env_dir / ".env").write_text(original, encoding="utf-8")

        RuntimeConfig().update({"COGNITO_CLIENT_ID": "client-123"})

        content = (self.env_dir / ".env").read_text(encoding="utf-8")
        self.assertIn('# Keep this comment\n', content)
        self.assertIn(
            'DJANGO_SECRET_KEY="value with spaces # and \\"quotes\\""\n',
            content,
        )
        self.assertEqual(
            dotenv_values(self.env_dir / ".env")["DJANGO_SECRET_KEY"],
            'value with spaces # and "quotes"',
        )

    def test_read_config_waits_for_update_and_returns_snapshot(self):
        config = RuntimeConfig()
        config._lock.acquire()
        read_finished = threading.Event()
        result = {}

        def read_config():
            result.update(config.read_config())
            read_finished.set()

        worker = threading.Thread(target=read_config)
        worker.start()
        time.sleep(0.05)
        self.assertFalse(read_finished.is_set())

        config._lock.release()
        worker.join(timeout=1)

        self.assertTrue(read_finished.is_set())
        self.assertEqual(result["COGNITO_CLIENT_ID"], "change-me")

    def test_update_ignores_unknown_keys(self):
        config = RuntimeConfig()
        result = config.update({"SOMETHING_ELSE": "x"})
        self.assertEqual(
            result,
            {
                "NEUROFLEX_API_BASE_URL": "change-me",
                "COGNITO_CLIENT_ID": "change-me",
                "GITHUB_TOKEN": "",
            },
        )

    def test_update_creates_dotenv_when_missing(self):
        config = RuntimeConfig()
        config.update({"GITHUB_TOKEN": VALID_GITHUB_TOKEN})
        self.assertTrue((self.env_dir / ".env").exists())

    def test_update_keeps_memory_unchanged_when_write_fails(self):
        config = RuntimeConfig()
        original = (
            "# Keep this file intact\n"
            "COGNITO_CLIENT_ID=old-client\n"
            "GITHUB_TOKEN=old-token\n"
        )
        (self.env_dir / ".env").write_text(original, encoding="utf-8")
        with patch.object(os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                config.update({"COGNITO_CLIENT_ID": "client-123"})
        self.assertEqual(config.get_cognito_client_id(), "change-me")
        self.assertEqual((self.env_dir / ".env").read_text(encoding="utf-8"), original)

    def test_update_preserves_comments_and_order(self):
        original = (
            "# first comment\n"
            "GITHUB_TOKEN=old-token\n"
            "\n"
            "COGNITO_CLIENT_ID=old-client\n"
            "# last comment\n"
            "NEUROFLEX_API_BASE_URL=https://old.example.com\n"
        )
        (self.env_dir / ".env").write_text(original, encoding="utf-8")

        RuntimeConfig().update(
            {
                "GITHUB_TOKEN": f"{VALID_GITHUB_TOKEN} token",
                "COGNITO_CLIENT_ID": "new-client",
                "NEUROFLEX_API_BASE_URL": "https://new.example.com",
            }
        )

        content = (self.env_dir / ".env").read_text(encoding="utf-8")
        self.assertEqual(
            content,
            "# first comment\n"
            f'GITHUB_TOKEN="{VALID_GITHUB_TOKEN} token"\n'
            "\n"
            "COGNITO_CLIENT_ID=new-client\n"
            "# last comment\n"
            "NEUROFLEX_API_BASE_URL=https://new.example.com\n",
        )

    def test_update_quotes_values_with_spaces(self):
        RuntimeConfig().update({"COGNITO_CLIENT_ID": "client with spaces"})

        content = (self.env_dir / ".env").read_text(encoding="utf-8")
        self.assertIn('COGNITO_CLIENT_ID="client with spaces"\n', content)
        self.assertEqual(
            dotenv_values(self.env_dir / ".env")["COGNITO_CLIENT_ID"],
            "client with spaces",
        )

    def test_update_preserves_inline_comment_on_allowed_key(self):
        original = "COGNITO_CLIENT_ID=old-client  # deployment note\n"
        (self.env_dir / ".env").write_text(original, encoding="utf-8")

        RuntimeConfig().update({"COGNITO_CLIENT_ID": "new-client"})

        self.assertEqual(
            (self.env_dir / ".env").read_text(encoding="utf-8"),
            "COGNITO_CLIENT_ID=new-client  # deployment note\n",
        )

    def test_update_preserves_mixed_dotenv_line_endings(self):
        original = (
            "# first\r\n"
            "COGNITO_CLIENT_ID=old-client\r\n"
            "GITHUB_TOKEN=old-token\n"
            "DJANGO_DEBUG=True\r\n"
        )
        (self.env_dir / ".env").write_bytes(original.encode("utf-8"))

        RuntimeConfig().update({"COGNITO_CLIENT_ID": "new-client"})

        self.assertEqual(
            (self.env_dir / ".env").read_bytes(),
            (
                "# first\r\n"
                "COGNITO_CLIENT_ID=new-client\r\n"
                "GITHUB_TOKEN=old-token\n"
                "DJANGO_DEBUG=True\r\n"
            ).encode("utf-8"),
        )

    def test_update_preserves_crlf_when_appending_missing_key(self):
        original = "COGNITO_CLIENT_ID=old-client\r\nGITHUB_TOKEN=old-token\r\n"
        (self.env_dir / ".env").write_bytes(original.encode("utf-8"))

        RuntimeConfig().update({"NEUROFLEX_API_BASE_URL": "https://new.example.com"})

        self.assertEqual(
            (self.env_dir / ".env").read_bytes(),
            (
                original
                + "NEUROFLEX_API_BASE_URL=https://new.example.com\r\n"
            ).encode("utf-8"),
        )

    def test_falls_back_to_base_dir_dotenv_for_missing_keys(self):
        base_dir = self.env_dir / "base"
        base_dir.mkdir()
        (base_dir / ".env").write_text(
            "NEUROFLEX_API_BASE_URL=https://fallback.example.com\n",
            encoding="utf-8",
        )
        config = RuntimeConfig()
        self.assertEqual(config.get_neuroflex_api_base_url(), "https://fallback.example.com")
        self.assertEqual(config.get_cognito_client_id(), "change-me")

    def test_data_dir_dotenv_takes_precedence_over_base_dir(self):
        base_dir = self.env_dir / "base"
        base_dir.mkdir()
        (base_dir / ".env").write_text(
            "NEUROFLEX_API_BASE_URL=https://fallback.example.com\n",
            encoding="utf-8",
        )
        self._write_dotenv({"NEUROFLEX_API_BASE_URL": "https://data.example.com"})
        config = RuntimeConfig()
        self.assertEqual(config.get_neuroflex_api_base_url(), "https://data.example.com")

    def test_writes_to_base_dir_dotenv_when_data_dir_unset(self):
        base_dir = self.env_dir / "base"
        base_dir.mkdir()
        with patch.dict(os.environ, {}, clear=True):
            RuntimeConfig._instance = None
            config = RuntimeConfig()
            config.update({"COGNITO_CLIENT_ID": "client-123"})
        self.assertTrue((base_dir / ".env").exists())
