from django.conf import settings
from django.db import models


class SpecialistSession(models.Model):
    """Ownership record: which specialist confirmed which external VR session_id.

    This does not duplicate clinical session data (metrics, patient info come
    from LocalSessionProvider/ApiSessionProvider); it only records who owns
    the session_id and the terms-acceptance snapshot returned at confirmation.
    """

    specialist = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="owned_sessions",
    )
    session_id = models.CharField(max_length=100, unique=True)
    status = models.CharField(max_length=50, blank=True)
    terms_version_id = models.CharField(max_length=100, blank=True)
    terms_language = models.CharField(max_length=10, blank=True)
    terms_content_hash = models.CharField(max_length=255, blank=True)
    terms_accepted_at = models.DateTimeField(null=True, blank=True)
    terms_acceptance_token = models.CharField(max_length=100, blank=True)
    vr_application_version = models.CharField(max_length=50, blank=True)
    metrics = models.JSONField(default=dict, blank=True)
    metrics_synced_at = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(auto_now_add=True)
    last_synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-confirmed_at"]

    def __str__(self):
        return f"{self.session_id} - {self.specialist or 'Sin especialista asociado'}"
