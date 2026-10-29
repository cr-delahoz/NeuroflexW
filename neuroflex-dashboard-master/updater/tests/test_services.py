import hashlib
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests
from django.test import SimpleTestCase

from updater.services import (
    UpdaterError,
    _get_auth_headers,
    download_installer,
    download_installer_with_progress,
    get_current_version,
    get_latest_release_info,
    has_update_available,
)


class GetAuthHeadersTest(SimpleTestCase):
    def test_omits_authorization_when_token_is_empty(self):
        runtime = MagicMock()
        runtime.get_github_token.return_value = ""
        with patch("updater.services.RuntimeConfig", return_value=runtime):
            self.assertEqual(_get_auth_headers(), {})

    def test_omits_authorization_when_token_is_unset(self):
        runtime = MagicMock()
        runtime.get_github_token.return_value = ""
        with patch("updater.services.RuntimeConfig", return_value=runtime):
            self.assertEqual(_get_auth_headers(), {})

    def test_includes_authorization_when_token_is_set(self):
        runtime = MagicMock()
        runtime.get_github_token.return_value = "secret-token"
        with patch("updater.services.RuntimeConfig", return_value=runtime):
            self.assertEqual(
                _get_auth_headers(), {"Authorization": "Bearer secret-token"}
            )


class GetCurrentVersionTest(SimpleTestCase):
    def test_reads_version_file(self):
        with patch("updater.services.Path") as mock_path_cls:
            mock_install_dir = MagicMock()
            mock_version_file = MagicMock()
            mock_version_file.read_text.return_value = "1.0.0\n"
            mock_version_file.exists.return_value = True
            mock_install_dir.__truediv__ = lambda self, other: mock_version_file
            mock_path_cls.return_value = mock_install_dir
            result = get_current_version()
            self.assertEqual(result, "1.0.0")

    def test_returns_unknown_if_no_version_file(self):
        with patch("updater.services.Path") as mock_path_cls:
            mock_install_dir = MagicMock()
            mock_install_dir.__truediv__ = lambda self, other: MagicMock(
                exists=lambda: False
            )
            mock_path_cls.return_value = mock_install_dir
            result = get_current_version()
            self.assertEqual(result, "unknown")


class GetLatestReleaseInfoTest(SimpleTestCase):
    def _api_response(self, tag="v1.2.0", body="Bug fixes", assets=None):
        if assets is None:
            assets = [
                {
                    "name": "NeuroFlex-Setup-1.2.0.exe",
                    "url": "https://api.github.com/repos/basstiago/neuroflex-dashboard/releases/assets/1",
                    "browser_download_url": "https://github.com/basstiago/neuroflex-dashboard/releases/download/v1.2.0/NeuroFlex-Setup-1.2.0.exe",
                },
                {
                    "name": "latest.json",
                    "url": "https://api.github.com/repos/basstiago/neuroflex-dashboard/releases/assets/2",
                    "browser_download_url": "https://github.com/basstiago/neuroflex-dashboard/releases/download/v1.2.0/latest.json",
                },
            ]
        return {
            "tag_name": tag,
            "body": body,
            "assets": assets,
        }

    def _latest_json_response(self, sha256="abc123"):
        mock = MagicMock()
        mock.status_code = 200
        mock.json.return_value = {
            "version": "1.2.0",
            "url": "https://example.com/setup.exe",
            "sha256": sha256,
            "changelog": "",
        }
        return mock

    def test_returns_parsed_info_on_success(self):
        api_response = MagicMock()
        api_response.status_code = 200
        api_response.json.return_value = self._api_response()

        json_response = self._latest_json_response("abc123")

        with patch(
            "updater.services.requests.get",
            side_effect=[api_response, json_response],
        ):
            result = get_latest_release_info()
            self.assertEqual(result["version"], "1.2.0")
            self.assertEqual(result["changelog"], "Bug fixes")
            self.assertEqual(result["sha256"], "abc123")
            self.assertIn("releases/assets/1", result["url"])
            self.assertEqual(result["filename"], "NeuroFlex-Setup-1.2.0.exe")

    def test_strips_v_prefix_from_tag_name(self):
        api_response = MagicMock()
        api_response.status_code = 200
        api_response.json.return_value = self._api_response(tag="v2.0.0")

        json_response = self._latest_json_response("def456")

        with patch(
            "updater.services.requests.get",
            side_effect=[api_response, json_response],
        ):
            result = get_latest_release_info()
            self.assertEqual(result["version"], "2.0.0")

    def test_returns_none_on_connection_error(self):
        with patch(
            "updater.services.requests.get",
            side_effect=requests.exceptions.ConnectionError(),
        ):
            result = get_latest_release_info()
            self.assertIsNone(result)

    def test_returns_none_on_non_200(self):
        mock_response = MagicMock()
        mock_response.status_code = 404
        with patch("updater.services.requests.get", return_value=mock_response):
            result = get_latest_release_info()
            self.assertIsNone(result)

    def test_returns_none_when_no_exe_asset(self):
        api_response = MagicMock()
        api_response.status_code = 200
        api_response.json.return_value = self._api_response(
            assets=[
                {
                    "name": "latest.json",
                    "url": "https://api.github.com/repos/basstiago/neuroflex-dashboard/releases/assets/2",
                    "browser_download_url": "https://example.com/latest.json",
                }
            ]
        )

        with patch("updater.services.requests.get", return_value=api_response):
            result = get_latest_release_info()
            self.assertIsNone(result)

    def test_returns_none_when_no_latest_json_asset(self):
        api_response = MagicMock()
        api_response.status_code = 200
        api_response.json.return_value = self._api_response(
            assets=[
                {
                    "name": "NeuroFlex-Setup-1.2.0.exe",
                    "url": "https://api.github.com/repos/basstiago/neuroflex-dashboard/releases/assets/1",
                    "browser_download_url": "https://example.com/setup.exe",
                }
            ]
        )

        with patch("updater.services.requests.get", return_value=api_response):
            result = get_latest_release_info()
            self.assertIsNone(result)

    def test_returns_none_when_sha256_download_fails(self):
        api_response = MagicMock()
        api_response.status_code = 200
        api_response.json.return_value = self._api_response()

        json_response = MagicMock()
        json_response.status_code = 404

        with patch(
            "updater.services.requests.get",
            side_effect=[api_response, json_response],
        ):
            result = get_latest_release_info()
            self.assertIsNone(result)

    def test_returns_empty_changelog_when_body_is_none(self):
        api_response = MagicMock()
        api_response.status_code = 200
        api_response.json.return_value = self._api_response(body=None)

        json_response = self._latest_json_response()

        with patch(
            "updater.services.requests.get",
            side_effect=[api_response, json_response],
        ):
            result = get_latest_release_info()
            self.assertEqual(result["changelog"], "")


class HasUpdateAvailableTest(SimpleTestCase):
    def test_returns_info_when_remote_is_newer(self):
        with (
            patch("updater.services.get_current_version", return_value="1.0.0"),
            patch(
                "updater.services.get_latest_release_info",
                return_value={
                    "version": "1.2.0",
                    "changelog": "Bug fixes",
                    "url": "https://api.github.com/repos/basstiago/neuroflex-dashboard/releases/assets/1",
                    "filename": "NeuroFlex-Setup-1.2.0.exe",
                    "sha256": "abc123",
                },
            ),
        ):
            result = has_update_available()
            self.assertEqual(result["version"], "1.2.0")
            self.assertEqual(result["changelog"], "Bug fixes")
            self.assertEqual(result["filename"], "NeuroFlex-Setup-1.2.0.exe")

    def test_returns_none_when_same_version(self):
        with (
            patch("updater.services.get_current_version", return_value="1.2.0"),
            patch(
                "updater.services.get_latest_release_info",
                return_value={
                    "version": "1.2.0",
                    "changelog": "",
                    "url": "https://api.github.com/repos/basstiago/neuroflex-dashboard/releases/assets/1",
                    "filename": "NeuroFlex-Setup-1.2.0.exe",
                    "sha256": "abc123",
                },
            ),
        ):
            result = has_update_available()
            self.assertIsNone(result)

    def test_returns_none_when_no_remote_info(self):
        with (
            patch("updater.services.get_current_version", return_value="1.0.0"),
            patch("updater.services.get_latest_release_info", return_value=None),
        ):
            result = has_update_available()
            self.assertIsNone(result)


class DownloadInstallerTest(SimpleTestCase):
    def test_downloads_and_verifies_sha256(self):
        content = b"fake_installer_content"
        expected_hash = hashlib.sha256(content).hexdigest()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_content = lambda chunk_size: [content]
        mock_response.__enter__ = lambda self: self
        mock_response.__exit__ = lambda *args: None

        import tempfile

        with (
            patch("updater.services.requests.get", return_value=mock_response),
            tempfile.TemporaryDirectory() as tmpdir,
        ):
            result = download_installer(
                "https://example.com/setup.exe",
                expected_hash,
                dest_dir=Path(tmpdir),
            )
            self.assertTrue(result.exists())
            self.assertEqual(result.read_bytes(), content)

    def test_uses_filename_when_provided(self):
        content = b"fake_installer_content"
        expected_hash = hashlib.sha256(content).hexdigest()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_content = lambda chunk_size: [content]
        mock_response.__enter__ = lambda self: self
        mock_response.__exit__ = lambda *args: None

        import tempfile

        with (
            patch("updater.services.requests.get", return_value=mock_response),
            tempfile.TemporaryDirectory() as tmpdir,
        ):
            result = download_installer(
                "https://api.github.com/repos/basstiago/neuroflex-dashboard/releases/assets/1",
                expected_hash,
                dest_dir=Path(tmpdir),
                filename="NeuroFlex-Setup-1.2.0.exe",
            )
            self.assertTrue(result.exists())
            self.assertEqual(result.name, "NeuroFlex-Setup-1.2.0.exe")
            self.assertEqual(result.read_bytes(), content)

    def test_raises_on_hash_mismatch(self):
        content = b"tampered_content"
        expected_hash = hashlib.sha256(b"original_content").hexdigest()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_content = lambda chunk_size: [content]
        mock_response.__enter__ = lambda self: self
        mock_response.__exit__ = lambda *args: None

        import tempfile

        with (
            patch("updater.services.requests.get", return_value=mock_response),
            tempfile.TemporaryDirectory() as tmpdir,
            self.assertRaises(UpdaterError),
        ):
            download_installer(
                "https://example.com/setup.exe",
                expected_hash,
                dest_dir=Path(tmpdir),
            )

    def test_reports_calculable_progress_from_content_length(self):
        content = b"abcdefgh"
        response = MagicMock(headers={"Content-Length": "8"})
        response.iter_content.return_value = [content[:4], content[4:]]
        response.raise_for_status.return_value = None
        seen = []
        with patch("updater.services.requests.get", return_value=response), tempfile.TemporaryDirectory() as tmpdir:
            download_installer_with_progress("job", lambda value, message: seen.append((value, message)), "https://example.com/setup.exe", hashlib.sha256(content).hexdigest(), Path(tmpdir))
        self.assertEqual([value for value, _ in seen], [50, 100])

    def test_reports_indeterminate_progress_without_content_length(self):
        content = b"installer"
        response = MagicMock(headers={})
        response.iter_content.return_value = [content]
        response.raise_for_status.return_value = None
        seen = []
        with patch("updater.services.requests.get", return_value=response), tempfile.TemporaryDirectory() as tmpdir:
            download_installer_with_progress("job", lambda value, message: seen.append((value, message)), "https://example.com/setup.exe", hashlib.sha256(content).hexdigest(), Path(tmpdir))
        self.assertEqual(seen, [(None, "Descargando instalador…")])
