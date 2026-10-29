from unittest.mock import Mock, patch

from django.core.cache import cache
from django.test import TestCase

from offline_mode.services.connectivity import is_online


class ConnectivityTests(TestCase):
    def setUp(self):
        cache.clear()

    @patch("offline_mode.services.connectivity.requests.get")
    def test_online_when_health_ok(self, mock_get):
        mock_get.return_value = Mock(status_code=200)
        self.assertTrue(is_online())

    @patch("offline_mode.services.connectivity.requests.get")
    def test_offline_on_connection_error(self, mock_get):
        import requests

        mock_get.side_effect = requests.ConnectionError()
        self.assertFalse(is_online())

    @patch("offline_mode.services.connectivity.requests.get")
    def test_result_is_cached(self, mock_get):
        mock_get.return_value = Mock(status_code=200)
        is_online()
        is_online()
        self.assertEqual(mock_get.call_count, 1)
