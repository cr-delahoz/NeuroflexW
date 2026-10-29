from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from offline_mode.models import OfflineAccessGrant


def capture_credentials_on_online_login(user, raw_password: str) -> None:
    """Tras un login Cognito exitoso: actualiza el hash local y renueva el acceso offline."""
    user.set_password(raw_password)
    user.save(update_fields=["password"])
    OfflineAccessGrant.objects.update_or_create(
        user=user,
        defaults={
            "offline_expires_at": timezone.now()
            + timedelta(days=settings.OFFLINE_ACCESS_DAYS),
            "failed_attempts": 0,
            "locked_until": None,
        },
    )
