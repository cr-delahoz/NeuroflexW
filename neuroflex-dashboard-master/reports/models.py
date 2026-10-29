from django.conf import settings
from django.db import models
from django.db.models import Q


class ReportRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        GENERATING = "GENERATING", "Generating"
        GENERATED = "GENERATED", "Generated"
        ERROR = "ERROR", "Error"

    session_id = models.CharField(max_length=100)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="report_requests",
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_report_requests",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    generated_at = models.DateTimeField(null=True, blank=True)
    specialist_observation = models.TextField(blank=True)
    technical_error_message = models.TextField(blank=True)
    file = models.FileField(upload_to="reports/", blank=True)
    session_snapshot = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-requested_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["session_id", "requested_by"],
                condition=Q(
                    status__in=["PENDING", "APPROVED", "GENERATING", "GENERATED"]
                ),
                name="unique_active_request_per_session_and_specialist",
            ),
        ]

    def __str__(self):
        return f"{self.session_id} - {self.status}"
