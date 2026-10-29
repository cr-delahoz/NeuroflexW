from django.contrib.auth.models import AbstractUser
from django.db import models


class Profession(models.Model):
    """Mirror of the remote professions catalog (DynamoDB via the API).

    It is an identification label only: it never affects permissions. The
    remote API is the source of truth; this table keeps names available
    locally (listing rendering, PDF) even when the API is unreachable.
    """

    DEFAULT_PROFESSION_ID = "sin-profesion"
    DEFAULT_PROFESSION_NAME = "Sin profesion asignada"

    id = models.CharField(primary_key=True, max_length=100)
    name = models.CharField(max_length=100)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @classmethod
    def get_default(cls):
        return cls.objects.filter(pk=cls.DEFAULT_PROFESSION_ID).first()

    @classmethod
    def get_display_name(cls, profession_id):
        if not profession_id:
            return cls.DEFAULT_PROFESSION_NAME
        return (
            cls.objects.filter(pk=profession_id)
            .values_list("name", flat=True)
            .first()
        ) or cls.DEFAULT_PROFESSION_NAME


class CustomUser(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Admin"
        SPECIALIST = "SPECIALIST", "Specialist"

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.SPECIALIST,
    )
    can_generate_pdf_without_approval = models.BooleanField(default=False)
    profession = models.ForeignKey(
        Profession,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="users",
    )

    # Links this local profile to its AWS Cognito identity. Cognito is the sole
    # authentication authority (the Django password is no longer checked at
    # login); this account is matched by its Cognito `sub` after a successful
    # Cognito authentication. Backfilled by username/email on first login for
    # accounts created before this field existed.
    cognito_sub = models.CharField(max_length=255, blank=True, null=True, unique=True)
    onboarding_status = models.CharField(max_length=50, blank=True, default="")
    cognito_status = models.CharField(max_length=50, blank=True, default="")

