import os

from django.apps import AppConfig
from django.conf import settings


class OfflineModeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "offline_mode"

    def ready(self):
        if not getattr(settings, "LAN_DISCOVERY_ENABLED", True):
            return
        if os.environ.get("LAN_DISCOVERY_FORCE") == "1":
            from offline_mode.discovery import start_discovery_listener

            start_discovery_listener()
