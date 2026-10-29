import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class OfflineDevice(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device_id = models.UUIDField(unique=True)
    name = models.CharField(max_length=100)
    device_token_hash = models.CharField(max_length=64)
    paired_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL
    )
    paired_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    revoked = models.BooleanField(default=False)


class PairingRequest(models.Model):
    pairing_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device_id = models.UUIDField()
    device_name = models.CharField(max_length=100)
    pin_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    confirm_attempts = models.PositiveIntegerField(default=0)
    confirmed = models.BooleanField(default=False)
    device_token = models.CharField(max_length=128, null=True, blank=True)
    delivered = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["device_id"],
                condition=models.Q(is_active=True),
                name="unique_active_pairing_per_device",
            )
        ]

    def is_expired(self):
        return timezone.now() >= self.expires_at


class OfflineTermsAcceptance(models.Model):
    token = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device = models.ForeignKey(OfflineDevice, on_delete=models.PROTECT)
    terms_version_id = models.CharField(max_length=100)
    content_hash = models.CharField(max_length=64)
    application_version = models.CharField(max_length=20, blank=True, default="")
    accepted_at = models.DateTimeField(auto_now_add=True)
    consumed = models.BooleanField(default=False)


class OfflineSession(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING"
        CONFIRMED = "CONFIRMED"
        COMPLETED = "COMPLETED"
        SYNCING = "SYNCING"
        SYNCED = "SYNCED"
        ERROR = "ERROR"

    session_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device = models.ForeignKey(OfflineDevice, on_delete=models.PROTECT)
    specialist = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    terms_version_id = models.CharField(max_length=100)
    terms_content_hash = models.CharField(max_length=64)
    terms_accepted_at = models.DateTimeField()
    acceptance_token = models.UUIDField()
    vr_application_version = models.CharField(max_length=20, blank=True, default="")
    metrics_token_hash = models.CharField(max_length=64)
    metrics = models.JSONField(null=True, blank=True)
    metrics_checksum = models.CharField(max_length=64, blank=True, default="")
    patient_info = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    sync_attempts = models.PositiveIntegerField(default=0)
    last_sync_error = models.TextField(blank=True, default="")
    sync_started_at = models.DateTimeField(null=True, blank=True)
    aws_session_id = models.UUIDField(null=True, blank=True)


class OfflineAccessGrant(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    offline_expires_at = models.DateTimeField()
    failed_attempts = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    last_online_validation = models.DateTimeField(auto_now=True)
