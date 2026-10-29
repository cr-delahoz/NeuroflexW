import os
import tempfile
from importlib import reload
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from integrations.services.runtime_config import RuntimeConfig


class DataDirSettingTest(SimpleTestCase):
    def test_data_dir_defaults_to_base_dir(self):
        from django.conf import settings

        self.assertEqual(settings.DATA_DIR, settings.BASE_DIR)

    def test_data_dir_uses_env_var_when_set(self):
        import django.conf
        from importlib import import_module, reload
        from config import settings as base_settings_module

        active_settings_name = django.conf.settings.SETTINGS_MODULE
        active_settings_module = import_module(active_settings_name)

        with patch.dict(os.environ, {"NEUROFLEX_DATA_DIR": "/tmp/neuroflex_test_data"}):
            reload(base_settings_module)
            if active_settings_module is not base_settings_module:
                reload(active_settings_module)
            django.conf.settings._setup()
            self.assertEqual(
                Path(django.conf.settings.DATA_DIR).as_posix(),
                "/tmp/neuroflex_test_data",
            )

        reload(base_settings_module)
        if active_settings_module is not base_settings_module:
            reload(active_settings_module)
        django.conf.settings._setup()


class EmptyEnvValuesSettingTest(SimpleTestCase):
    """Empty editable values fall back to RuntimeConfig defaults."""

    def test_empty_env_values_use_runtime_config_defaults(self):
        import django.conf
        from importlib import import_module, reload
        from config import settings as base_settings_module

        active_settings_name = django.conf.settings.SETTINGS_MODULE
        active_settings_module = import_module(active_settings_name)

        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            env_file.write_text(
                "COGNITO_CLIENT_ID=\nNEUROFLEX_API_BASE_URL=\n",
                encoding="utf-8",
            )
            saved = {
                key: os.environ.pop(key)
                for key in ("COGNITO_CLIENT_ID", "NEUROFLEX_API_BASE_URL")
                if key in os.environ
            }
            try:
                with patch.object(RuntimeConfig, "_instance", None), patch.dict(
                    os.environ, {"NEUROFLEX_DATA_DIR": tmpdir}, clear=False
                ):
                    reload(base_settings_module)
                    if active_settings_module is not base_settings_module:
                        reload(active_settings_module)
                    django.conf.settings._setup()
                    self.assertEqual(django.conf.settings.COGNITO_CLIENT_ID, "change-me")
                    self.assertEqual(
                        django.conf.settings.NEUROFLEX_API_BASE_URL,
                        "change-me",
                    )
            finally:
                for key in ("COGNITO_CLIENT_ID", "NEUROFLEX_API_BASE_URL"):
                    if key in saved:
                        os.environ[key] = saved[key]
                    else:
                        os.environ.pop(key, None)

        reload(base_settings_module)
        if active_settings_module is not base_settings_module:
            reload(active_settings_module)
        django.conf.settings._setup()
