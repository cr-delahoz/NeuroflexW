import logging

from django import forms
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from integrations.services.cognito_auth_client import (
    CognitoAuthClient,
    CognitoAuthClientError,
)
from integrations.services.cognito_claims import decode_jwt_claims
from integrations.services.api_gateway_users_client import (
    ApiGatewayUsersClient,
    ApiGatewayUsersClientError,
)

from accounts.services import sync_local_user_from_remote_user
from integrations.services.runtime_config import RuntimeConfig
from offline_mode.services.offline_auth_service import capture_credentials_on_online_login


User = get_user_model()
logger = logging.getLogger(__name__)


class CognitoAuthenticationForm(forms.Form):
    """Login form that authenticates ONLY against AWS Cognito.

    Django's password is never checked. After Cognito validates the
    credentials, the matching local profile is resolved (or auto-created)
    by the Cognito `sub` so roles and permissions keep working. Mirrors
    the parts of django.contrib.auth.forms.AuthenticationForm that
    LoginView relies on (get_user()/user_cache).
    """

    username = forms.CharField(label="Usuario")
    password = forms.CharField(
        label="Contrasena", required=False, strip=False, widget=forms.PasswordInput
    )
    temporary_password = forms.CharField(
        label="Contrasena temporal",
        required=False,
        strip=False,
        widget=forms.PasswordInput,
    )
    new_password1 = forms.CharField(
        label="Nueva contrasena",
        required=False,
        strip=False,
        widget=forms.PasswordInput,
    )
    new_password2 = forms.CharField(
        label="Confirmar nueva contrasena",
        required=False,
        strip=False,
        widget=forms.PasswordInput,
    )

    def __init__(self, request=None, *args, **kwargs):
        self.request = request
        self.challenge_data = kwargs.pop("challenge_data", None)
        self.user_cache = None
        self.auth_result = None
        self.cognito_sub = ""
        self.new_password_required = False
        self.required_attributes = []
        self.challenge_username = ""
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            existing_classes = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing_classes} nf-input".strip()
        # When continuing a new-password challenge, the challenge session is
        # stored server-side and the username is carried by ``challenge_data``;
        # the posted username is only echoed back via a hidden input, so it must
        # not be required by field-level validation.
        if self.challenge_data:
            self.fields["username"].required = False

    def clean(self):
        cleaned_data = super().clean()
        username = cleaned_data.get("username")
        password = cleaned_data.get("password")
        new_password1 = cleaned_data.get("new_password1")
        new_password2 = cleaned_data.get("new_password2")

        if self.challenge_data:
            # Second step of the new-password challenge: the challenge session
            # is stored server-side, so the temporary password is NOT required.
            if not new_password1:
                self.add_error("new_password1", "Este campo es obligatorio.")
            if not new_password2:
                self.add_error("new_password2", "Este campo es obligatorio.")
            if self._errors:
                return cleaned_data
            if new_password1 != new_password2:
                self.add_error("new_password2", "Las contrasenas no coinciden.")
                return cleaned_data

            session = self.challenge_data.get("session")
            challenge_username = self.challenge_data.get("username")
            required_attributes = self.challenge_data.get("required_attributes")
            if (
                not isinstance(session, str)
                or not session
                or not isinstance(challenge_username, str)
                or not challenge_username
                or not isinstance(required_attributes, list)
                or not all(isinstance(attribute, str) for attribute in required_attributes)
                or any(attribute != "email" for attribute in required_attributes)
            ):
                raise forms.ValidationError(
                    "No fue posible completar el cambio de contrasena."
                )

            # Use the stored username for the rest of clean() so the shared
            # new_password_required branch records the correct challenge_username.
            username = challenge_username

            try:
                auth_result = CognitoAuthClient(
                    client_id=RuntimeConfig().get_cognito_client_id()
                ).respond_to_new_password_challenge(
                    challenge_username, new_password1, session, required_attributes
                )
            except CognitoAuthClientError:
                raise forms.ValidationError(
                    "No fue posible completar el cambio de contrasena."
                )
        elif new_password1 or new_password2:
            # New passwords were posted but no challenge session is stored
            # server-side. The challenge expired or the user navigated back to
            # the login page; require a fresh login with the temporary password
            # instead of silently re-running initiate_auth with a possibly-stale
            # temporary password.
            raise forms.ValidationError(
                "La sesión de cambio de contraseña expiró. Inicia sesión nuevamente con tu contraseña temporal.",
                code="challenge_expired",
            )
        elif not username:
            return cleaned_data
        else:
            if not password:
                self.add_error("password", "Este campo es obligatorio.")
                return cleaned_data

            try:
                auth_result = CognitoAuthClient(
                    client_id=RuntimeConfig().get_cognito_client_id()
                ).initiate_auth(username, password)
            except CognitoAuthClientError:
                raise forms.ValidationError(
                    "No fue posible validar tus credenciales con NeuroFlex. "
                    "Verifica tu usuario y contrasena."
                )

        if not isinstance(auth_result, dict):
            raise forms.ValidationError("No fue posible validar tus credenciales.")

        if auth_result.get("status") == "new_password_required":
            self.auth_result = {
                "status": "new_password_required",
                "session": auth_result.get("session"),
            }
            required_attributes = auth_result.get("required_attributes", [])
            if (
                not isinstance(required_attributes, list)
                or not all(isinstance(attribute, str) for attribute in required_attributes)
            ):
                raise forms.ValidationError("No fue posible validar tus credenciales.")
            self.new_password_required = True
            self.required_attributes = required_attributes
            self.challenge_username = username
            return cleaned_data

        if auth_result.get("status") != "authenticated":
            raise forms.ValidationError("No fue posible validar tus credenciales.")

        id_token = auth_result.get("id_token")
        if not isinstance(id_token, str) or not id_token:
            raise forms.ValidationError("No fue posible validar tus credenciales.")

        try:
            claims = decode_jwt_claims(id_token)
        except Exception:
            raise forms.ValidationError("No fue posible validar tus credenciales.")

        sub = claims.get("sub", "") if isinstance(claims, dict) else ""
        if not isinstance(sub, str) or not sub.strip():
            raise forms.ValidationError("No fue posible validar tus credenciales.")

        try:
            remote_user = ApiGatewayUsersClient().get_user(id_token, sub)
        except ApiGatewayUsersClientError:
            raise forms.ValidationError(
                "No fue posible verificar tu cuenta con NeuroFlex. "
                "Contacta al administrador."
            )

        if (
            not isinstance(remote_user, dict)
            or remote_user.get("user_id") != sub
            or not remote_user.get("is_active")
        ):
            raise forms.ValidationError("Esta cuenta esta desactivada.")

        try:
            with transaction.atomic():
                user = sync_local_user_from_remote_user(remote_user)
        except (TypeError, ValueError, KeyError, IntegrityError):
            raise forms.ValidationError(
                "No fue posible verificar tu cuenta con NeuroFlex. "
                "Contacta al administrador."
            )

        if user is None or not user.is_active:
            raise forms.ValidationError("Esta cuenta esta desactivada.")

        # LoginView -> auth_login needs a backend on the user, since we are not
        # going through django's authenticate().
        user.backend = "django.contrib.auth.backends.ModelBackend"
        self.user_cache = user
        self.auth_result = auth_result
        self.cognito_sub = sub
        if self.challenge_data:
            raw_password = self.cleaned_data.get("new_password1")
            if raw_password and hasattr(self.user_cache, "set_password"):
                try:
                    capture_credentials_on_online_login(self.user_cache, raw_password)
                except Exception:
                    logger.exception(
                        "No se pudo capturar la credencial offline; el login continúa."
                    )
        else:
            raw_password = self.cleaned_data.get("password")
            if raw_password and hasattr(self.user_cache, "set_password"):
                try:
                    capture_credentials_on_online_login(self.user_cache, raw_password)
                except Exception:
                    logger.exception(
                        "No se pudo capturar la credencial offline; el login continúa."
                    )
        return cleaned_data

    def get_user(self):
        return self.user_cache


class RemoteUserCreationForm(forms.Form):
    email = forms.EmailField(label="Correo electronico")
    first_name = forms.CharField(label="Nombre", max_length=150)
    last_name = forms.CharField(label="Apellido", max_length=150)
    role = forms.ChoiceField(
        label="Rol",
        choices=[("Administrator", "Administrador"), ("Specialist", "Especialista")],
    )
    profession_id = forms.ChoiceField(label="Profesion", choices=[], required=False)
    profession_name_map = {}

    def __init__(self, *args, professions=None, **kwargs):
        super().__init__(*args, **kwargs)
        professions = professions or []
        self.profession_name_map = {
            profession.id: profession.name for profession in professions
        }
        choices = [
            (profession.id, profession.name) for profession in professions
        ] or [("", "Sin profesion asignada")]
        self.fields["profession_id"].choices = choices
        for field in self.fields.values():
            existing_classes = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing_classes} nf-input".strip()

    def clean_profession_id(self):
        profession_id = self.cleaned_data.get("profession_id")
        return profession_id or "sin-profesion"


class ProfessionCreateForm(forms.Form):
    name = forms.CharField(
        label="Nombre de la profesion",
        max_length=100,
    )

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if not name:
            raise forms.ValidationError("El nombre no puede estar vacio.")
        return name

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            existing_classes = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing_classes} nf-input".strip()


class NewPasswordRequiredForm(forms.Form):
    username = forms.CharField(label="Usuario")
    temporary_password = forms.CharField(
        label="Contrasena temporal", strip=False, widget=forms.PasswordInput
    )
    new_password1 = forms.CharField(
        label="Nueva contrasena", required=False, strip=False, widget=forms.PasswordInput
    )
    new_password2 = forms.CharField(
        label="Confirmar nueva contrasena",
        required=False,
        strip=False,
        widget=forms.PasswordInput,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            existing_classes = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing_classes} nf-input".strip()

    def clean(self):
        cleaned_data = super().clean()
        if (
            cleaned_data.get("new_password1")
            and cleaned_data.get("new_password2")
            and cleaned_data["new_password1"] != cleaned_data["new_password2"]
        ):
            self.add_error("new_password2", "Las contrasenas no coinciden.")
        return cleaned_data


class UserNameUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name"]
        labels = {
            "first_name": "Nombre",
            "last_name": "Apellido",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            existing_classes = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing_classes} nf-input".strip()


class RequestPasswordResetForm(forms.Form):
    email = forms.EmailField(label="Correo")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            existing_classes = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing_classes} nf-input".strip()


class ResetPasswordConfirmForm(forms.Form):
    email = forms.EmailField(label="Correo")
    confirmation_code = forms.CharField(label="Codigo de confirmacion")
    new_password1 = forms.CharField(
        label="Nueva contrasena",
        strip=False,
        widget=forms.PasswordInput,
    )
    new_password2 = forms.CharField(
        label="Confirmar nueva contrasena",
        strip=False,
        widget=forms.PasswordInput,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            existing_classes = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing_classes} nf-input".strip()

    def clean(self):
        cleaned_data = super().clean()
        new_password1 = cleaned_data.get("new_password1")
        new_password2 = cleaned_data.get("new_password2")

        if new_password1 and new_password2 and new_password1 != new_password2:
            self.add_error("new_password2", "Las contrasenas no coinciden.")

        return cleaned_data
