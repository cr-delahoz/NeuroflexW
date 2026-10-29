import requests
from django.core.cache import cache


CACHE_KEY = "offline_connectivity"
CACHE_TTL = 30
TIMEOUT = 2

FORCED_OFFLINE_KEY = "forced_offline"


def force_offline(session) -> None:
    """Marca la sesión para forzar el modo sin conexión en el login."""
    session[FORCED_OFFLINE_KEY] = True


def force_online_retry(session) -> None:
    """Marca la sesión para reintentar el modo en línea en el login."""
    session[FORCED_OFFLINE_KEY] = False


def _health_url() -> str:
    from integrations.services.runtime_config import RuntimeConfig

    base = RuntimeConfig().get_neuroflex_api_base_url().rstrip("/")
    return f"{base}/health"


def is_online(force: bool = False) -> bool:
    if not force:
        cached = cache.get(CACHE_KEY)
        if cached is not None:
            return cached
    try:
        response = requests.get(_health_url(), timeout=TIMEOUT)
        online = response.status_code == 200
    except requests.RequestException:
        online = False
    cache.set(CACHE_KEY, online, CACHE_TTL)
    return online
