import ipaddress
import logging
import socket
import threading

from django.conf import settings


logger = logging.getLogger(__name__)

MAGIC = b"NEUROFLEX_DISCOVER"
REPLY_PREFIX = b"NEUROFLEX_HERE|v1|"
_PRIVATE_LAN_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
)
_started = False


def _is_private_lan_ipv4(address: str) -> bool:
    if not isinstance(address, str):
        return False
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return ip.version == 4 and any(ip in network for network in _PRIVATE_LAN_NETWORKS)


def _interface_ip_for(source_addr):
    """Return the local IPv4 of the interface that reaches ``source_addr``.

    Connecting a UDP socket does not send any packet; it only makes the OS
    pick the outgoing interface, whose address is then read back locally.
    """
    if not source_addr:
        return None
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect((source_addr[0], 9))
            return probe.getsockname()[0]
    except (OSError, IndexError):
        return None


def _enumerate_private_ipv4():
    """Return the first private LAN IPv4 found on this machine, if any."""
    candidates = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            candidates.append(info[4][0])
    except OSError:
        pass
    try:
        # No packet is sent: UDP connect only resolves the outgoing interface.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            candidates.append(probe.getsockname()[0])
    except OSError:
        pass
    for candidate in candidates:
        if _is_private_lan_ipv4(candidate):
            return candidate
    return None


def _resolve_lan_ip(source_addr=None):
    """Resolve the best private LAN IPv4, or None to fall back to hostname."""
    interface_ip = _interface_ip_for(source_addr)
    if _is_private_lan_ipv4(interface_ip):
        return interface_ip
    return _enumerate_private_ipv4()


def build_reply(payload: bytes, source_addr=None):
    if not payload.startswith(MAGIC):
        return None
    host = _resolve_lan_ip(source_addr) or socket.gethostname()
    port = str(settings.LAN_HTTP_PORT)
    return REPLY_PREFIX + host.encode() + f"|{port}".encode()


def _serve():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("0.0.0.0", settings.LAN_DISCOVERY_PORT))
    except OSError as exc:
        logger.error(
            "No se pudo enlazar el listener UDP de descubrimiento en el puerto %s: %s",
            settings.LAN_DISCOVERY_PORT,
            exc,
        )
        sock.close()
        return
    try:
        while True:
            try:
                payload, addr = sock.recvfrom(1024)
            except OSError as exc:
                logger.error("Error en socket UDP de descubrimiento: %s", exc)
                return
            reply = build_reply(payload, addr)
            if reply:
                try:
                    sock.sendto(reply, addr)
                except OSError as exc:
                    logger.error(
                        "Error al responder descubrimiento UDP a %s: %s", addr, exc
                    )
    finally:
        sock.close()


def start_discovery_listener():
    global _started
    if _started or not settings.LAN_DISCOVERY_ENABLED:
        return
    _started = True
    threading.Thread(target=_serve, daemon=True, name="lan-discovery").start()
