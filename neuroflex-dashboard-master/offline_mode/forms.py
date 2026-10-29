from datetime import timedelta

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import F
from django.utils import timezone

from offline_mode.models import OfflineAccessGrant
from offline_mode.services.audit_service import log_offline_event


class OfflineAuthenticationForm(forms.Form):
    username = forms.CharField(label="Usuario")
    password = forms.CharField(label="Contraseña", widget=forms.PasswordInput)

    def clean(self):
        cleaned = super().clean()
        username = cleaned.get("username")
        password = cleaned.get("password")
        if not username or not password:
            log_offline_event(actor=None, action="OFFLINE_LOGIN_FAILURE",
                              resource_type="user", resource_id=username or "", result="FAILURE",
                              metadata={"reason": "missing_credentials"})
            return cleaned
        User = get_user_model()
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            log_offline_event(actor=None, action="OFFLINE_LOGIN_FAILURE",
                              resource_type="user", resource_id=username, result="FAILURE",
                              metadata={"reason": "user_not_found"})
            raise forms.ValidationError("Credenciales inválidas.")
        if not user.is_active:
            log_offline_event(actor=user, action="OFFLINE_LOGIN_FAILURE",
                              resource_type="user", resource_id=user.pk, result="FAILURE",
                              metadata={"reason": "inactive"})
            raise forms.ValidationError("Credenciales inválidas.")
        try:
            grant = user.offlineaccessgrant
        except OfflineAccessGrant.DoesNotExist:
            grant = None
        now = timezone.now()
        if grant and grant.locked_until and grant.locked_until > now:
            log_offline_event(actor=user, action="OFFLINE_LOGIN_FAILURE",
                              resource_type="user", resource_id=user.pk, result="FAILURE",
                              metadata={"reason": "locked"})
            raise forms.ValidationError("Cuenta bloqueada temporalmente. Intente más tarde.")
        if not user.check_password(password):
            if grant:
                OfflineAccessGrant.objects.filter(pk=grant.pk).update(
                    failed_attempts=F("failed_attempts") + 1)
                grant.refresh_from_db()
                if grant.failed_attempts >= settings.OFFLINE_LOGIN_MAX_ATTEMPTS:
                    grant.locked_until = now + timedelta(minutes=settings.OFFLINE_LOGIN_LOCKOUT_MINUTES)
                    grant.failed_attempts = 0
                grant.save(update_fields=["failed_attempts", "locked_until"])
            log_offline_event(actor=user, action="OFFLINE_LOGIN_FAILURE",
                              resource_type="user", resource_id=user.pk, result="FAILURE",
                              metadata={"reason": "bad_password"})
            raise forms.ValidationError("Credenciales inválidas.")
        if getattr(user, "role", None) != "SPECIALIST":
            log_offline_event(actor=user, action="OFFLINE_LOGIN_FAILURE",
                              resource_type="user", resource_id=user.pk, result="FAILURE",
                              metadata={"reason": "admin_role"})
            raise forms.ValidationError(
                "Este rol requiere conexión a internet para iniciar sesión.")
        if not grant or grant.offline_expires_at <= now:
            log_offline_event(actor=user, action="OFFLINE_LOGIN_FAILURE",
                              resource_type="user", resource_id=user.pk, result="FAILURE",
                              metadata={"reason": "grant_expired"})
            raise forms.ValidationError(
                "El acceso sin conexión expiró. Inicie sesión con internet al menos una vez.")
        grant.failed_attempts = 0
        grant.locked_until = None
        grant.save(update_fields=["failed_attempts", "locked_until"])
        self.user_cache = user
        log_offline_event(actor=user, action="OFFLINE_LOGIN_SUCCESS",
                          resource_type="user", resource_id=user.pk)
        return cleaned
