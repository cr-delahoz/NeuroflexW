from django.db import models


class TermsVersion(models.Model):
    """Local mirror of a terms-and-conditions version managed by the external API.

    Content is never authored here; it is only synced via terms/services.py.
    """

    version_id = models.CharField(max_length=100)
    title = models.CharField(max_length=255)
    content = models.TextField()
    language = models.CharField(max_length=10)
    content_hash = models.CharField(max_length=255)
    published = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["version_id", "language"],
                name="unique_terms_version_per_language",
            ),
        ]

    def __str__(self):
        return f"{self.version_id} ({self.language})"
