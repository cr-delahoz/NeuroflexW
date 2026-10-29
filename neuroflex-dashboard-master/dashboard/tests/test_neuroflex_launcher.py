import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

import neuroflex_launcher as launcher


class ActivateExistingWindowTests(TestCase):
    def test_restores_and_foregrounds_existing_dashboard_window(self):
        user32 = MagicMock()
        user32.FindWindowW.return_value = 1234
        user32.SetForegroundWindow.return_value = True

        with patch.object(
            launcher.ctypes, "windll", SimpleNamespace(user32=user32)
        ):
            launcher.activate_existing_window()

        user32.FindWindowW.assert_called_once_with(None, "NeuroFlex Dashboard")
        user32.ShowWindow.assert_called_once_with(1234, 9)
        user32.SetForegroundWindow.assert_called_once_with(1234)

    def test_shows_message_when_foregrounding_window_fails(self):
        user32 = MagicMock()
        user32.FindWindowW.return_value = 1234
        user32.SetForegroundWindow.return_value = False

        with patch.object(
            launcher.ctypes, "windll", SimpleNamespace(user32=user32)
        ):
            launcher.activate_existing_window()

        user32.MessageBoxW.assert_called_once_with(
            None,
            "NeuroFlex Dashboard ya se esta ejecutando.",
            "NeuroFlex Dashboard",
            0x40,
        )

    def test_shows_message_when_dashboard_window_is_not_found(self):
        user32 = MagicMock()
        user32.FindWindowW.return_value = 0

        with patch.object(
            launcher.ctypes, "windll", SimpleNamespace(user32=user32)
        ):
            launcher.activate_existing_window()

        user32.MessageBoxW.assert_called_once_with(
            None,
            "NeuroFlex Dashboard ya se esta ejecutando.",
            "NeuroFlex Dashboard",
            0x40,
        )

    def test_shows_message_when_window_lookup_fails(self):
        user32 = MagicMock()
        user32.FindWindowW.side_effect = OSError("Windows API failure")

        with patch.object(
            launcher.ctypes, "windll", SimpleNamespace(user32=user32)
        ):
            launcher.activate_existing_window()

        user32.MessageBoxW.assert_called_once_with(
            None,
            "NeuroFlex Dashboard ya se esta ejecutando.",
            "NeuroFlex Dashboard",
            0x40,
        )


class WaitForServerTests(TestCase):
    @patch("neuroflex_launcher.requests.get")
    @patch("builtins.print")
    def test_rejects_http_service_without_neuroflex_marker(self, mock_print, mock_get):
        mock_get.return_value = SimpleNamespace(
            status_code=200,
            text="<title>Another service</title>",
        )

        self.assertFalse(launcher.wait_for_server())

        mock_print.assert_called_once_with(
            "[launcher] El servicio en 127.0.0.1:8000 no es NeuroFlex Dashboard.",
            file=launcher.sys.stderr,
        )


class WebView2RuntimeTests(TestCase):
    @patch.object(launcher.sys, "platform", "win32")
    def test_accepts_webview2_runtime_installed_for_current_user(self):
        winreg = MagicMock()
        winreg.HKEY_LOCAL_MACHINE = "HKLM"
        winreg.HKEY_CURRENT_USER = "HKCU"
        winreg.OpenKey.side_effect = [OSError("not installed system-wide"), MagicMock()]

        with patch.dict("sys.modules", {"winreg": winreg}):
            self.assertTrue(launcher.is_webview2_runtime_available())

        self.assertEqual(
            winreg.OpenKey.call_args_list[1].args,
            (
                "HKCU",
                r"SOFTWARE\Microsoft\EdgeUpdate\Clients"
                r"\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
            ),
        )


class ServerPortTests(TestCase):
    @patch("neuroflex_launcher.socket.socket")
    def test_reports_port_unavailable_when_temporary_bind_fails(self, mock_socket):
        mock_socket.return_value.__enter__.return_value.bind.side_effect = OSError("in use")

        self.assertFalse(launcher.is_server_port_available())


class EnsureSecretKeyTests(TestCase):
    def test_does_not_overwrite_existing_cognito_and_api_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            env_file.write_text(
                "DJANGO_SECRET_KEY=change-me\r\n"
                "COGNITO_CLIENT_ID=existing-client-id\r\n"
                "NEUROFLEX_API_BASE_URL=https://api.example.com\r\n",
                encoding="utf-8",
                newline="",
            )

            launcher.ensure_secret_key(Path(tmpdir))

            content = env_file.read_text(encoding="utf-8", newline="")
            self.assertIn("COGNITO_CLIENT_ID=existing-client-id", content)
            self.assertIn("NEUROFLEX_API_BASE_URL=https://api.example.com", content)
            self.assertNotIn("DJANGO_SECRET_KEY=change-me", content)
            self.assertIn("DJANGO_SECRET_KEY=", content)

    def test_leaves_file_untouched_when_secret_key_is_not_change_me(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            original = (
                "DJANGO_SECRET_KEY=already-generated\r\n"
                "COGNITO_CLIENT_ID=existing-client-id\r\n"
            )
            env_file.write_text(original, encoding="utf-8", newline="")

            launcher.ensure_secret_key(Path(tmpdir))

            self.assertEqual(
                env_file.read_text(encoding="utf-8", newline=""), original
            )


class ValidateCriticalEnvTests(TestCase):
    def _patch_runtime_config(self, **values):
        defaults = {
            "COGNITO_CLIENT_ID": "client-id",
            "NEUROFLEX_API_BASE_URL": "https://api.example.com",
            "GITHUB_TOKEN": "token",
        }
        defaults.update(values)
        runtime = MagicMock()
        runtime.get_cognito_client_id.return_value = defaults["COGNITO_CLIENT_ID"]
        runtime.get_neuroflex_api_base_url.return_value = defaults[
            "NEUROFLEX_API_BASE_URL"
        ]
        runtime.get_github_token.return_value = defaults["GITHUB_TOKEN"]
        return patch.object(launcher, "RuntimeConfig", return_value=runtime)

    def _patch_windll(self):
        return patch.object(
            launcher.ctypes, "windll", SimpleNamespace(user32=MagicMock())
        )

    def test_exits_when_cognito_client_id_is_missing(self):
        user32 = MagicMock()
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch.object(launcher, "get_data_dir", return_value=Path(tmpdir)),
            self._patch_runtime_config(COGNITO_CLIENT_ID=""),
            patch.object(launcher.sys, "exit") as mock_exit,
            patch.object(launcher.ctypes, "windll", SimpleNamespace(user32=user32)),
        ):
            launcher.validate_critical_env()

        mock_exit.assert_called_once_with(1)
        user32.MessageBoxW.assert_called_once()
        message = user32.MessageBoxW.call_args.args[1]
        self.assertIn("reinstalar", message)
        self.assertIn("COGNITO_CLIENT_ID", message)

    def test_exits_when_api_base_url_is_change_me(self):
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch.object(launcher, "get_data_dir", return_value=Path(tmpdir)),
            self._patch_runtime_config(NEUROFLEX_API_BASE_URL="change-me"),
            patch.object(launcher.sys, "exit") as mock_exit,
            self._patch_windll(),
        ):
            launcher.validate_critical_env()

        mock_exit.assert_called_once_with(1)

    def test_does_not_exit_when_critical_values_are_present(self):
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch.object(launcher, "get_data_dir", return_value=Path(tmpdir)),
            self._patch_runtime_config(),
            patch.object(launcher.sys, "exit") as mock_exit,
        ):
            launcher.validate_critical_env()

        mock_exit.assert_not_called()

    def test_warns_but_does_not_block_when_github_token_is_empty(self):
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch.object(launcher, "get_data_dir", return_value=Path(tmpdir)),
            self._patch_runtime_config(GITHUB_TOKEN=""),
            patch.object(launcher.sys, "exit") as mock_exit,
            patch("builtins.print") as mock_print,
        ):
            launcher.validate_critical_env()

        mock_exit.assert_not_called()
        mock_print.assert_called_once()
        self.assertIn("GITHUB_TOKEN", mock_print.call_args.args[0])


class LauncherMainTests(TestCase):
    def test_does_not_expose_initial_admin_provisioning(self):
        self.assertFalse(hasattr(launcher, "create_initial_admin_if_needed"))

    @patch("neuroflex_launcher.webview.start")
    @patch("neuroflex_launcher.webview.create_window")
    @patch("neuroflex_launcher.threading.Thread")
    @patch("neuroflex_launcher.wait_for_server", return_value=True)
    @patch("neuroflex_launcher.is_server_port_available", return_value=True)
    @patch("neuroflex_launcher.is_webview2_runtime_available", return_value=True)
    @patch("neuroflex_launcher.validate_critical_env")
    @patch("neuroflex_launcher.ensure_secret_key")
    @patch("neuroflex_launcher.setup_environment")
    @patch("neuroflex_launcher.is_already_running", return_value=False)
    @patch("django.core.management.call_command")
    @patch("django.setup")
    def test_starts_daemon_server_and_configures_maximized_window(
        self,
        mock_django_setup,
        mock_call_command,
        mock_is_running,
        mock_setup_environment,
        mock_ensure_secret_key,
        mock_validate_critical_env,
        mock_webview2_available,
        mock_port_available,
        mock_wait_for_server,
        mock_thread,
        mock_create_window,
        mock_webview_start,
    ):
        window = MagicMock()
        mock_create_window.return_value = window

        with patch.object(launcher.sys, "exit") as mock_exit:
            launcher.main()

        mock_thread.assert_called_once()
        self.assertTrue(mock_thread.call_args.kwargs["daemon"])
        mock_thread.return_value.start.assert_called_once_with()
        mock_create_window.assert_called_once_with(
            "NeuroFlex Dashboard",
            launcher.SERVER_URL,
            maximized=True,
            resizable=True,
            menu=[],
        )
        mock_webview_start.assert_called_once_with()
        mock_validate_critical_env.assert_called_once_with()
        mock_exit.assert_called_once_with(0)

    def test_on_window_close_stops_server_without_exiting_callback_thread(self):
        stop_event = MagicMock()
        with patch.object(launcher.sys, "exit") as mock_exit:
            launcher.on_window_close(stop_event)

        stop_event.set.assert_called_once_with()
        mock_exit.assert_not_called()
