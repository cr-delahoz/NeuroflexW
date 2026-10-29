import os
import socket
from unittest import mock
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from offline_mode.discovery import _is_private_lan_ipv4, build_reply


class DiscoveryTests(SimpleTestCase):
    def test_reply_to_valid_discovery(self):
        reply = build_reply(b"NEUROFLEX_DISCOVER|v1|Quest-A4F2")
        self.assertIsNotNone(reply)
        self.assertTrue(reply.startswith(b"NEUROFLEX_HERE|v1|"))
        self.assertTrue(reply.endswith(b"|8000"))

    def test_no_reply_to_garbage(self):
        self.assertIsNone(build_reply(b"HOLA"))


class DiscoveryReplyAddressTests(SimpleTestCase):
    """La respuesta incluye la IP LAN privada real y el puerto configurado."""

    def test_reply_uses_private_ip_from_source_addr(self):
        with patch(
            "offline_mode.discovery._interface_ip_for", return_value="192.168.1.42"
        ):
            reply = build_reply(
                b"NEUROFLEX_DISCOVER|v1|Quest", ("192.168.1.42", 5555)
            )
        self.assertEqual(reply, b"NEUROFLEX_HERE|v1|192.168.1.42|8000")

    def test_reply_enumerates_private_ip_when_interface_unknown(self):
        with (
            patch("offline_mode.discovery._interface_ip_for", return_value=None),
            patch(
                "offline_mode.discovery._enumerate_private_ipv4",
                return_value="10.1.2.3",
            ),
        ):
            reply = build_reply(b"NEUROFLEX_DISCOVER|v1|Quest")
        self.assertEqual(reply, b"NEUROFLEX_HERE|v1|10.1.2.3|8000")

    def test_reply_falls_back_to_hostname_without_private_ip(self):
        with patch("offline_mode.discovery._resolve_lan_ip", return_value=None):
            reply = build_reply(b"NEUROFLEX_DISCOVER|v1|Quest")
        expected = b"NEUROFLEX_HERE|v1|" + socket.gethostname().encode() + b"|8000"
        self.assertEqual(reply, expected)

    @override_settings(LAN_HTTP_PORT=9000)
    def test_reply_uses_configured_http_port(self):
        with patch("offline_mode.discovery._resolve_lan_ip", return_value="10.0.0.7"):
            reply = build_reply(b"NEUROFLEX_DISCOVER|v1|Quest")
        self.assertEqual(reply, b"NEUROFLEX_HERE|v1|10.0.0.7|9000")

    def test_private_lan_ipv4_detection(self):
        for address in ("10.0.0.1", "172.16.5.4", "172.31.255.254", "192.168.0.10"):
            with self.subTest(address=address):
                self.assertTrue(_is_private_lan_ipv4(address))
        for address in (
            "127.0.0.1",
            "172.32.0.1",
            "192.169.0.1",
            "8.8.8.8",
            "not-an-ip",
        ):
            with self.subTest(address=address):
                self.assertFalse(_is_private_lan_ipv4(address))


class DiscoveryServeTests(SimpleTestCase):
    """El listener UDP no rompe el hilo silenciosamente ante errores de socket."""

    def test_bind_failure_logs_error_and_returns(self):
        from offline_mode import discovery

        with mock.patch("offline_mode.discovery.socket.socket") as sock_cls:
            sock_cls.return_value.bind.side_effect = OSError("address already in use")
            with self.assertLogs("offline_mode.discovery", level="ERROR"):
                discovery._serve()
            sock_cls.return_value.close.assert_called()

    def test_recvfrom_error_logs_error_and_returns(self):
        from offline_mode import discovery

        with mock.patch("offline_mode.discovery.socket.socket") as sock_cls:
            sock_cls.return_value.recvfrom.side_effect = OSError("socket down")
            with self.assertLogs("offline_mode.discovery", level="ERROR"):
                discovery._serve()
            sock_cls.return_value.close.assert_called()

    def test_sendto_error_logs_error_and_continues(self):
        from offline_mode import discovery

        with mock.patch("offline_mode.discovery.socket.socket") as sock_cls:
            sock = sock_cls.return_value
            sock.recvfrom.side_effect = [
                (b"NEUROFLEX_DISCOVER|v1|Quest", ("10.0.0.5", 5555)),
                OSError("socket down"),
            ]
            sock.sendto.side_effect = OSError("host unreachable")
            with self.assertLogs("offline_mode.discovery", level="ERROR") as logs:
                discovery._serve()
            sock.sendto.assert_called_once()
            self.assertTrue(
                any("responder" in message for message in logs.output)
            )
            sock.close.assert_called()


class DiscoveryGuardTests(SimpleTestCase):
    """LAN_DISCOVERY_FORCE debe valer exactamente "1" para activar el listener."""

    def _ready(self):
        from django.apps import apps

        apps.get_app_config("offline_mode").ready()

    @override_settings(LAN_DISCOVERY_ENABLED=True)
    def test_force_env_exact_1_starts_listener(self):
        with patch.dict(os.environ, {"LAN_DISCOVERY_FORCE": "1"}):
            with mock.patch(
                "offline_mode.discovery.start_discovery_listener"
            ) as starter:
                self._ready()
        starter.assert_called_once()

    @override_settings(LAN_DISCOVERY_ENABLED=True)
    def test_force_env_other_values_do_not_start_listener(self):
        for value in ("0", "true", "yes", ""):
            with self.subTest(value=value):
                with patch.dict(os.environ, {"LAN_DISCOVERY_FORCE": value}):
                    with mock.patch(
                        "offline_mode.discovery.start_discovery_listener"
                    ) as starter:
                        self._ready()
                starter.assert_not_called()

    @override_settings(LAN_DISCOVERY_ENABLED=True)
    def test_force_env_absent_does_not_start_listener(self):
        with patch.dict(os.environ):
            os.environ.pop("LAN_DISCOVERY_FORCE", None)
            with mock.patch(
                "offline_mode.discovery.start_discovery_listener"
            ) as starter:
                self._ready()
        starter.assert_not_called()
