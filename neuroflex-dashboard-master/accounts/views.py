import json
import logging
from functools import partial
from urllib.parse import urlparse

import requests
from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth import get_user_model
from django.contrib.auth.views import LoginView, LogoutView
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views import View

from audit.models import AuditLog
from audit.services import get_client_ip, log_event
from dashboard.views import RoleRequiredMixin
from integrations.services.cognito_claims import decode_jwt_claims
from integrations.services.cognito_signup_client import (
    CognitoConfigurationError,
    CognitoInvalidParameterError,
    CognitoInvalidPasswordError,
    CognitoLimitExceededError,
    CognitoNetworkError,
    CognitoNotAuthorizedError,
    CognitoSignUpClient,
    CognitoSignUpClientError,
    CognitoUserNotConfirmedError,
    CognitoUserNotFoundError,
)
from integrations.services.api_gateway_users_client import (
    ApiGatewayUsersClient,
    ApiGatewayUsersClientError,
)
from integrations.services.api_gateway_professions_client import (
    ApiGatewayProfessionsClient,
    ApiGatewayProfessionsClientError,
    DEFAULT_PROFESSION_ID,
    DEFAULT_PROFESSION_NAME,
)
from integrations.services.runtime_config import RuntimeConfig
from offline_mode.forms import OfflineAuthenticationForm
from offline_mode.services.connectivity import (
    FORCED_OFFLINE_KEY,
    force_offline,
    force_online_retry,
    is_online,
)
from terms.services import sync_terms_versions

from .forms import (
    CognitoAuthenticationForm,
    ProfessionCreateForm,
    RemoteUserCreationForm,
    ResetPasswordConfirmForm,
    RequestPasswordResetForm,
    UserNameUpdateForm,
)
from .services import (
    REMOTE_ROLE_TO_LOCAL_ROLE,
    get_valid_cognito_token,
    reconcile_local_users_from_remote_listing,
    sync_local_user_from_remote_user,
    sync_professions_from_remote,
)
from .local_config_service import (
    LocalConfigValidationError,
    read_config,
    write_config,
)
from .models import Profession


User = get_user_model()
logger = logging.getLogger(__name__)

LOCAL_ROLE_DISPLAY_NAMES = {
    User.Role.ADMIN: "Administrador",
    User.Role.SPECIALIST: "Especialista",
}


def _sync_professions_from_remote_or_none(token):
    """Best-effort professions catalog sync; failures never block rendering."""
    try:
        return sync_professions_from_remote(token, ApiGatewayProfessionsClient())
    except (ApiGatewayProfessionsClientError, ValueError):
        logger.exception("No fue posible sincronizar el catalogo de profesiones.")
        return None


def _get_professions_for_select(token):
    from .models import Profession

    _sync_professions_from_remote_or_none(token)
    return list(Profession.objects.filter(is_active=True).order_by("name"))


def get_cognito_id_token_or_redirect(request):
    token = get_valid_cognito_token(request)
    if token:
        return token
    messages.error(request, "Tu sesion expiro. Inicia sesion nuevamente.")
    return redirect("accounts:login")


class RoleBasedLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = CognitoAuthenticationForm
    redirect_authenticated_user = True

    def _is_online(self):
        if hasattr(self, "_online"):
            return self._online
        forced = self.request.session.get(FORCED_OFFLINE_KEY)
        if forced is True:
            self._online = False
            return self._online
        if forced is False:
            # Reintento solicitado manualmente: verificar sin usar la caché.
            self.request.session.pop(FORCED_OFFLINE_KEY, None)
            self._online = is_online(force=True)
            return self._online
        self._online = is_online()
        return self._online

    def get_form_class(self):
        if not self._is_online():
            return OfflineAuthenticationForm
        return super().get_form_class()

    def get_form_kwargs(self):
        if not self._is_online():
            return {"data": self.request.POST or None}
        kwargs = super().get_form_kwargs()
        kwargs["challenge_data"] = self.request.session.get("cognito_new_password_challenge")
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["offline_mode"] = not self._is_online()
        return context

    def form_valid(self, form):
        if not self._is_online():
            # auth_login puede reemplazar la sesión previa (flush/cycle de
            # sesión): se conserva el token AWS ya presente para poder
            # sincronizar más tarde sin re-autenticar online si aún no expira.
            existing_token = self.request.session.get("cognito_id_token", "")
            existing_exp = self.request.session.get("cognito_id_token_expires_at")
            existing_refresh = self.request.session.get("cognito_refresh_token")
            auth_login(self.request, form.user_cache)
            self.request.session["offline_mode"] = True
            if existing_token:
                self.request.session["cognito_id_token"] = existing_token
            if existing_exp:
                self.request.session["cognito_id_token_expires_at"] = existing_exp
            if existing_refresh:
                self.request.session["cognito_refresh_token"] = existing_refresh
            return redirect("offline_mode:panel")

        if form.new_password_required:
            # Store the challenge session server-side so the second step does
            # not require re-entering the temporary password. Guard against a
            # malformed challenge response (missing session) before storing it.
            session = form.auth_result.get("session")
            if not session:
                form.add_error(
                    None,
                    "No fue posible iniciar el cambio de contrasena. Intenta nuevamente.",
                )
                return self.render_to_response(self.get_context_data(form=form))
            self.request.session["cognito_new_password_challenge"] = {
                "username": form.challenge_username,
                "session": session,
                "required_attributes": form.required_attributes,
            }
            return self.render_to_response(self.get_context_data(form=form))

        # Successful final login: clear any stored challenge session.
        self.request.session.pop("cognito_new_password_challenge", None)
        self.request.session.pop("offline_mode", None)

        # The form already authenticated against Cognito and resolved the local
        # profile by `sub`; super().form_valid logs that user in (Django's
        # password is never checked).
        response = super().form_valid(form)
        self.request.session["cognito_id_token"] = form.auth_result["id_token"]
        self.request.session["cognito_sub"] = form.cognito_sub
        access_token = form.auth_result.get("access_token")
        if access_token:
            self.request.session["cognito_access_token"] = access_token
        refresh_token = form.auth_result.get("refresh_token")
        if refresh_token:
            self.request.session["cognito_refresh_token"] = refresh_token
        token_claims = decode_jwt_claims(form.auth_result["id_token"])
        token_exp = token_claims.get("exp") if isinstance(token_claims, dict) else None
        if isinstance(token_exp, (int, float)):
            self.request.session["cognito_id_token_expires_at"] = int(token_exp)
        # Best-effort terms & conditions sync so offline mode can serve the
        # latest catalog; a failure must never block the login itself.
        try:
            sync_terms_versions(form.auth_result["id_token"])
        except Exception as exc:
            logger.warning(
                "No se pudieron sincronizar los términos y condiciones: %s", exc
            )
        log_event(
            actor=self.request.user,
            action="user_logged_in",
            resource_type="session",
            resource_id=self.request.session.session_key or "",
            result=AuditLog.Result.SUCCESS,
            ip_address=get_client_ip(self.request),
            metadata={"username": self.request.user.username},
        )
        return response

    def form_invalid(self, form):
        # Do not retain the submitted username or validation detail: both can
        # become personal or authentication-sensitive data.  Wazuh only needs
        # the outcome, time and source IP to detect anomalous attempts.
        log_event(
            actor=None,
            action="user_login_failed",
            resource_type="session",
            resource_id="",
            result=AuditLog.Result.FAILURE,
            ip_address=get_client_ip(self.request),
            metadata={},
        )
        return super().form_invalid(form)

    def get_success_url(self):
        user = self.request.user

        if user.role == user.Role.ADMIN:
            return reverse_lazy("dashboard:admin")

        return reverse_lazy("dashboard:specialist")


class RoleBasedLogoutView(LogoutView):
    next_page = reverse_lazy("accounts:login")

    def post(self, request, *args, **kwargs):
        user = request.user if request.user.is_authenticated else None
        session_key = request.session.session_key or ""

        if user:
            log_event(
                actor=user,
                action="user_logged_out",
                resource_type="session",
                resource_id=session_key,
                result=AuditLog.Result.SUCCESS,
                ip_address=get_client_ip(request),
                metadata={"username": user.username},
            )

        return super().post(request, *args, **kwargs)


class RequestPasswordResetView(View):
    """Public page where any user (admin or specialist) self-requests a
    Cognito forgot-password code, instead of waiting for an admin to trigger
    it on their behalf via PasswordResetView.

    Always shows the same confirmation message regardless of whether the
    email is registered or already confirmed, to avoid leaking account
    existence to an unauthenticated visitor.
    """

    def get(self, request, *args, **kwargs):
        form = RequestPasswordResetForm()
        return render(request, "accounts/request_password_reset.html", {"form": form})

    def post(self, request, *args, **kwargs):
        form = RequestPasswordResetForm(request.POST)

        if form.is_valid():
            email = form.cleaned_data["email"]

            try:
                CognitoSignUpClient().forgot_password(email)
            except (
                CognitoUserNotFoundError,
                CognitoUserNotConfirmedError,
                CognitoInvalidParameterError,
            ):
                pass
            except CognitoSignUpClientError:
                form.add_error(
                    None,
                    "No fue posible procesar tu solicitud en este momento. Intenta nuevamente.",
                )
                return render(
                    request,
                    "accounts/request_password_reset.html",
                    {"form": form},
                    status=400,
                )

            log_event(
                actor=None,
                action="password_reset_self_requested",
                resource_type="user",
                resource_id="",
                result=AuditLog.Result.SUCCESS,
                ip_address=get_client_ip(request),
                metadata={"username": email},
            )
            messages.success(
                request,
                "Revisa tu correo para continuar con la recuperacion.",
            )
            return redirect("accounts:reset-password-confirm")

        return render(
            request, "accounts/request_password_reset.html", {"form": form}, status=400
        )


class ResetPasswordConfirmView(View):
    """Public page where a specialist completes a forgot-password recovery.

    Uses Cognito's ForgotPassword/ConfirmForgotPassword pair, so no old or
    temporary password is ever needed.
    """

    def get(self, request, *args, **kwargs):
        form = ResetPasswordConfirmForm()
        return render(request, "accounts/reset_password_confirm.html", {"form": form})

    def post(self, request, *args, **kwargs):
        form = ResetPasswordConfirmForm(request.POST)

        if form.is_valid():
            email = form.cleaned_data["email"]
            confirmation_code = form.cleaned_data["confirmation_code"]
            new_password = form.cleaned_data["new_password1"]

            try:
                CognitoSignUpClient().confirm_forgot_password(
                    email, confirmation_code, new_password
                )
            except CognitoInvalidPasswordError:
                form.add_error(
                    "new_password1",
                    "La nueva contrasena no cumple los requisitos de seguridad de NeuroFlex.",
                )
                return render(
                    request,
                    "accounts/reset_password_confirm.html",
                    {"form": form},
                    status=400,
                )
            except CognitoSignUpClientError:
                form.add_error(
                    "confirmation_code",
                    "El codigo ingresado no es valido o ya expiro. Verifica tu correo e intenta nuevamente.",
                )
                return render(
                    request,
                    "accounts/reset_password_confirm.html",
                    {"form": form},
                    status=400,
                )

            target_user = get_object_or_404(User, username=email)
            target_user.set_password(new_password)
            target_user.save(update_fields=["password"])

            log_event(
                actor=None,
                action="password_reset_confirmed",
                resource_type="user",
                resource_id=target_user.pk,
                result=AuditLog.Result.SUCCESS,
                ip_address=get_client_ip(request),
                metadata={"username": email},
            )
            messages.success(
                request, "Contrasena actualizada. Inicia sesion con tu nueva contrasena."
            )
            return redirect("accounts:login")

        return render(
            request, "accounts/reset_password_confirm.html", {"form": form}, status=400
        )


class UserListView(RoleRequiredMixin, View):
    required_role = User.Role.ADMIN

    def get(self, request, *args, **kwargs):
        token = get_cognito_id_token_or_redirect(request)
        if not isinstance(token, str):
            return token
        role = request.GET.get("role")
        if role not in {"Administrator", "Specialist"}:
            role = None
        is_active = request.GET.get("is_active")
        if is_active in {"true", "false"}:
            is_active = is_active == "true"
        else:
            is_active = None
        users_client = ApiGatewayUsersClient()
        users_client.list_users = partial(
            users_client.list_users, role=role, is_active=is_active
        )
        try:
            users = reconcile_local_users_from_remote_listing(
                token, users_client
            )
        except ApiGatewayUsersClientError:
            messages.error(
                request,
                "El servicio de usuarios no esta disponible. Intenta nuevamente.",
            )
            return redirect("accounts:user-list")
        return render(
            request,
            "accounts/user_list.html",
            {
                "users": users,
                "role": role,
                "is_active": is_active,
                "professions": _get_professions_for_select(token),
            },
        )


class SpecialistProfileView(RoleRequiredMixin, View):
    required_role = User.Role.SPECIALIST

    def get(self, request, *args, **kwargs):
        token = get_cognito_id_token_or_redirect(request)
        if not isinstance(token, str):
            return token
        sub = request.user.cognito_sub
        if not sub:
            messages.error(request, "No fue posible identificar tu cuenta.")
            return redirect("dashboard:specialist")
        try:
            remote_user = ApiGatewayUsersClient().get_user(token, sub)
            sync_local_user_from_remote_user(remote_user)
        except ApiGatewayUsersClientError:
            logger.exception("No fue posible obtener el perfil del especialista.")
            messages.error(
                request,
                "No fue posible obtener tu perfil en este momento. Intenta nuevamente.",
            )
            return redirect("dashboard:specialist")
        return render(request, "accounts/specialist_profile.html", {"user": request.user})


class UserNameUpdateView(RoleRequiredMixin, View):
    required_role = User.Role.ADMIN

    def get(self, request, user_id, *args, **kwargs):
        target_user = get_object_or_404(User, pk=user_id)
        form = UserNameUpdateForm(instance=target_user)
        return render(
            request,
            "accounts/user_name_form.html",
            {"form": form, "target_user": target_user},
        )

    def post(self, request, user_id, *args, **kwargs):
        target_user = get_object_or_404(User, pk=user_id)
        form = UserNameUpdateForm(request.POST, instance=target_user)
        if form.is_valid():
            form.save()
            log_event(
                actor=request.user,
                action="user_name_updated",
                resource_type="user",
                resource_id=target_user.pk,
                result=AuditLog.Result.SUCCESS,
                ip_address=get_client_ip(request),
                metadata={
                    "username": target_user.username,
                    "first_name": target_user.first_name,
                    "last_name": target_user.last_name,
                },
            )
            messages.success(request, "Nombre y apellido actualizados correctamente.")
            return redirect("accounts:user-list")
        return render(
            request,
            "accounts/user_name_form.html",
            {"form": form, "target_user": target_user},
            status=400,
        )


class SpecialistCreateView(RoleRequiredMixin, View):
    required_role = User.Role.ADMIN

    def get(self, request, *args, **kwargs):
        token = get_cognito_id_token_or_redirect(request)
        if not isinstance(token, str):
            return token
        form = RemoteUserCreationForm(professions=_get_professions_for_select(token))
        return render(request, "accounts/user_form.html", {"form": form})

    def post(self, request, *args, **kwargs):
        token = get_cognito_id_token_or_redirect(request)
        if not isinstance(token, str):
            return token
        form = RemoteUserCreationForm(
            request.POST, professions=_get_professions_for_select(token)
        )

        if form.is_valid():
            requested_role = form.cleaned_data["role"]
            try:
                remote_user = ApiGatewayUsersClient().create_user(
                    token,
                    form.cleaned_data["email"],
                    requested_role,
                    profession_id=form.cleaned_data["profession_id"],
                )
                user = sync_local_user_from_remote_user(remote_user)
            except ApiGatewayUsersClientError:
                messages.error(
                    request,
                    "No fue posible registrar al usuario en este momento. Intenta nuevamente.",
                )
                return redirect("accounts:user-list")

            user.role = REMOTE_ROLE_TO_LOCAL_ROLE[requested_role]  # fallback/defensa
            user.first_name = form.cleaned_data["first_name"]
            user.last_name = form.cleaned_data["last_name"]
            user.save(update_fields=["first_name", "last_name", "role", "profession"])

            log_event(
                actor=request.user,
                action="user_created",
                resource_type="user",
                resource_id=remote_user["user_id"],
                result=AuditLog.Result.SUCCESS,
                ip_address=get_client_ip(request),
                metadata={
                    "role": remote_user.get("role") or requested_role,
                    "profession_id": form.cleaned_data["profession_id"],
                },
            )
            messages.success(
                request,
                f"Usuario {form.cleaned_data['email']} creado exitosamente. "
                "Se enviará una contraseña temporal a su correo.",
            )
            return redirect("accounts:user-list")

        return render(request, "accounts/user_form.html", {"form": form}, status=400)


class UserStatusUpdateView(RoleRequiredMixin, View):
    required_role = User.Role.ADMIN
    activate = True

    def post(self, request, user_id, *args, **kwargs):
        token = get_cognito_id_token_or_redirect(request)
        if not isinstance(token, str):
            return token
        target_user = get_object_or_404(User, pk=user_id)

        if request.user.pk == target_user.pk and not self.activate:
            return render(
                request,
                "errors/403.html",
                {"message": "No puedes desactivar tu propia cuenta."},
                status=403,
            )

        try:
            remote_user = ApiGatewayUsersClient().update_user_status(
                token, target_user.cognito_sub, self.activate
            )
            sync_local_user_from_remote_user(remote_user)
        except ApiGatewayUsersClientError:
            messages.error(
                request,
                "No fue posible actualizar el estado del usuario. Intenta nuevamente.",
            )
            return redirect("accounts:user-list")

        action = "user_activated" if self.activate else "user_deactivated"
        log_event(
            actor=request.user,
            action=action,
            resource_type="user",
            resource_id=remote_user["user_id"],
            result=AuditLog.Result.SUCCESS,
            ip_address=get_client_ip(request),
            metadata={"active": self.activate},
        )
        email = remote_user["email"]
        if self.activate:
            messages.success(
                request, f"La cuenta de '{email}' fue activada exitosamente."
            )
        else:
            messages.success(
                request, f"La cuenta de '{email}' fue desactivada exitosamente."
            )
        return redirect("accounts:user-list")


class UserActivateView(UserStatusUpdateView):
    activate = True


class UserDeactivateView(UserStatusUpdateView):
    activate = False


class UserRoleUpdateView(RoleRequiredMixin, View):
    required_role = User.Role.ADMIN

    def post(self, request, user_id, *args, **kwargs):
        token = get_cognito_id_token_or_redirect(request)
        if not isinstance(token, str):
            return token
        target_user = get_object_or_404(User, pk=user_id)
        role = request.POST.get("role")
        if role not in {"Administrator", "Specialist"}:
            return HttpResponseBadRequest("Rol invalido.")
        try:
            remote_user = ApiGatewayUsersClient().update_user_role(
                token, target_user.cognito_sub, role
            )
            sync_local_user_from_remote_user(remote_user)
        except ApiGatewayUsersClientError:
            messages.error(
                request,
                "No fue posible actualizar el rol del usuario. Intenta nuevamente.",
            )
            return redirect("accounts:user-list")
        log_event(
            actor=request.user,
            action="user_role_changed",
            resource_type="user",
            resource_id=remote_user["user_id"],
            result=AuditLog.Result.SUCCESS,
            ip_address=get_client_ip(request),
            metadata={"role": role},
        )
        local_role = REMOTE_ROLE_TO_LOCAL_ROLE[role]
        role_display = LOCAL_ROLE_DISPLAY_NAMES[local_role]
        messages.success(
            request,
            f"El rol de '{remote_user['email']}' fue actualizado a '{role_display}'.",
        )
        return redirect("accounts:user-list")


class UserProfessionUpdateView(RoleRequiredMixin, View):
    required_role = User.Role.ADMIN

    def post(self, request, user_id, *args, **kwargs):
        token = get_cognito_id_token_or_redirect(request)
        if not isinstance(token, str):
            return token
        target_user = get_object_or_404(User, pk=user_id)
        profession_id = request.POST.get("profession_id")
        if not isinstance(profession_id, str) or not profession_id:
            return HttpResponseBadRequest("Profesion invalida.")
        try:
            remote_user = ApiGatewayUsersClient().update_user_profession(
                token, target_user.cognito_sub, profession_id
            )
            sync_local_user_from_remote_user(remote_user)
        except (ApiGatewayUsersClientError, ApiGatewayProfessionsClientError):
            messages.error(
                request,
                "No fue posible actualizar la profesion del usuario. Intenta nuevamente.",
            )
            return redirect("accounts:user-list")
        profession_name = _resolve_profession_name(profession_id)
        log_event(
            actor=request.user,
            action="user_profession_updated",
            resource_type="user",
            resource_id=remote_user["user_id"],
            result=AuditLog.Result.SUCCESS,
            ip_address=get_client_ip(request),
            metadata={"profession_id": profession_id},
        )
        messages.success(
            request,
            f"La profesion de '{remote_user['email']}' fue actualizada a '{profession_name}'.",
        )
        return redirect("accounts:user-list")


def _resolve_profession_name(profession_id):
    from .models import Profession

    if not profession_id:
        return Profession.DEFAULT_PROFESSION_NAME
    return Profession.get_display_name(profession_id)


class ProfessionListView(RoleRequiredMixin, View):
    required_role = User.Role.ADMIN

    def get(self, request, *args, **kwargs):
        token = get_cognito_id_token_or_redirect(request)
        if not isinstance(token, str):
            return token
        _sync_professions_from_remote_or_none(token)
        professions = list(
            Profession.objects.all().order_by("is_default", "name")
        )
        return render(
            request,
            "accounts/profession_list.html",
            {
                "professions": professions,
                "form": ProfessionCreateForm(),
            },
        )


class ProfessionCreateView(RoleRequiredMixin, View):
    required_role = User.Role.ADMIN

    def post(self, request, *args, **kwargs):
        token = get_cognito_id_token_or_redirect(request)
        if not isinstance(token, str):
            return token
        form = ProfessionCreateForm(request.POST)
        if not form.is_valid():
            _sync_professions_from_remote_or_none(token)
            professions = list(Profession.objects.all().order_by("is_default", "name"))
            return render(
                request,
                "accounts/profession_list.html",
                {"professions": professions, "form": form},
                status=400,
            )
        try:
            profession = ApiGatewayProfessionsClient().create_profession(
                token, form.cleaned_data["name"]
            )
        except ApiGatewayProfessionsClientError:
            messages.error(
                request,
                "No fue posible crear la profesion en este momento. Intenta nuevamente.",
            )
            return redirect("accounts:profession-list")
        _sync_professions_from_remote_or_none(token)
        log_event(
            actor=request.user,
            action="profession_created",
            resource_type="profession",
            resource_id=profession["profession_id"],
            result=AuditLog.Result.SUCCESS,
            ip_address=get_client_ip(request),
            metadata={"name": profession["name"]},
        )
        messages.success(
            request,
            f"La profesion '{profession['name']}' fue creada exitosamente.",
        )
        return redirect("accounts:profession-list")


class ProfessionDeleteView(RoleRequiredMixin, View):
    required_role = User.Role.ADMIN

    def post(self, request, profession_id, *args, **kwargs):
        token = get_cognito_id_token_or_redirect(request)
        if not isinstance(token, str):
            return token
        if profession_id == DEFAULT_PROFESSION_ID:
            return render(
                request,
                "errors/403.html",
                {"message": "La profesion por defecto no puede ser eliminada."},
                status=403,
            )
        reassign_to = request.POST.get("reassign_to") or None
        try:
            result = ApiGatewayProfessionsClient().delete_profession(
                token, profession_id, reassign_to=reassign_to
            )
        except ApiGatewayProfessionsClientError:
            messages.error(
                request,
                "No fue posible eliminar la profesion en este momento. Intenta nuevamente.",
            )
            return redirect("accounts:profession-list")
        _sync_professions_from_remote_or_none(token)
        profession_name = _resolve_profession_name(profession_id)
        log_event(
            actor=request.user,
            action="profession_deleted",
            resource_type="profession",
            resource_id=profession_id,
            result=AuditLog.Result.SUCCESS,
            ip_address=get_client_ip(request),
            metadata={
                "reassigned_users": result["reassigned_users"],
                "reassigned_to": result["reassigned_to"],
            },
        )
        messages.success(
            request,
            f"La profesion '{profession_name}' fue eliminada. "
            f"{result['reassigned_users']} usuarios fueron reasignados.",
        )
        return redirect("accounts:profession-list")


class PdfPermissionUpdateView(RoleRequiredMixin, View):
    required_role = User.Role.ADMIN
    grant = True

    def post(self, request, user_id, *args, **kwargs):
        target_user = get_object_or_404(User, pk=user_id)

        target_user.can_generate_pdf_without_approval = self.grant
        target_user.save(update_fields=["can_generate_pdf_without_approval"])

        action = "pdf_permission_granted" if self.grant else "pdf_permission_revoked"
        log_event(
            actor=request.user,
            action=action,
            resource_type="user",
            resource_id=target_user.pk,
            result=AuditLog.Result.SUCCESS,
            ip_address=get_client_ip(request),
            metadata={"username": target_user.username},
        )
        if self.grant:
            messages.success(
                request,
                f"Se habilito la generacion de PDF sin aprobacion para '{target_user.username}'.",
            )
        else:
            messages.success(
                request,
                f"Se deshabilito la generacion de PDF sin aprobacion para '{target_user.username}'.",
            )
        return redirect("accounts:user-list")


class PdfPermissionGrantView(PdfPermissionUpdateView):
    grant = True


class PdfPermissionRevokeView(PdfPermissionUpdateView):
    grant = False


class UserDeleteView(RoleRequiredMixin, View):
    required_role = User.Role.ADMIN
    CONFIRMATION_WORD = "ELIMINAR"

    def get(self, request, user_id, *args, **kwargs):
        target_user = get_object_or_404(User, pk=user_id)
        return render(
            request,
            "accounts/user_delete_confirm.html",
            {"target_user": target_user, "confirmation_word": self.CONFIRMATION_WORD},
        )

    def post(self, request, user_id, *args, **kwargs):
        target_user = get_object_or_404(User, pk=user_id)

        if request.user.pk == target_user.pk:
            return render(
                request,
                "errors/403.html",
                {"message": "No puedes eliminar tu propia cuenta."},
                status=403,
            )

        if request.POST.get("confirmation_word") != self.CONFIRMATION_WORD:
            return render(
                request,
                "accounts/user_delete_confirm.html",
                {
                    "target_user": target_user,
                    "confirmation_word": self.CONFIRMATION_WORD,
                    "confirmation_error": (
                        f'Debes escribir exactamente "{self.CONFIRMATION_WORD}" para confirmar.'
                    ),
                },
                status=400,
            )

        username = target_user.username
        role = target_user.role

        # TODO: also delete the Cognito registration via AdminDeleteUser once
        # IAM credentials are available for this User Pool. This requires an
        # AWS-signed (SigV4) admin call, not the public app client used
        # elsewhere in this project. Currently blocked: the AWS Academy
        # sandbox does not allow creating IAM users/credentials. Until then,
        # whoever manages the Cognito User Pool must delete this account
        # manually on that side.
        target_user.delete()

        log_event(
            actor=request.user,
            action="user_deleted",
            resource_type="user",
            resource_id=user_id,
            result=AuditLog.Result.SUCCESS,
            ip_address=get_client_ip(request),
            metadata={"username": username, "role": role},
        )
        messages.success(request, f"La cuenta de '{username}' fue eliminada.")
        return redirect("accounts:user-list")


class PasswordResetView(RoleRequiredMixin, View):
    required_role = User.Role.ADMIN

    def post(self, request, user_id, *args, **kwargs):
        target_user = get_object_or_404(User, pk=user_id)
        # Cognito's user pool uses the email as the username; the local
        # ``username`` field mirrors that email (see sync_local_user_from_remote_user).
        # Prefer the stored username (the Cognito identifier) and fall back to
        # the email field only when the username is empty, so the exact
        # identifier Cognito knows reaches ForgotPassword.
        identifier = target_user.get_username()
        if not identifier:
            identifier = target_user.email

        logger.info(
            "Requesting password reset for user_id=%s identifier=%s",
            target_user.id,
            identifier,
        )

        try:
            CognitoSignUpClient().forgot_password(identifier)
        except (CognitoUserNotFoundError, CognitoUserNotConfirmedError) as exc:
            logger.error(
                "Cognito UserNotFound/UserNotConfirmed for user_id=%s identifier=%s: %s",
                target_user.id,
                identifier,
                str(exc),
            )
            logger.exception(
                "Cognito rejected admin password reset: user not found or not confirmed."
            )
            messages.error(
                request,
                "El usuario no existe o no está confirmado en Cognito.",
            )
            return redirect("accounts:user-list")
        except CognitoInvalidParameterError as exc:
            logger.error(
                "Cognito InvalidParameterException for user_id=%s identifier=%s: %s",
                target_user.id,
                identifier,
                str(exc),
            )
            logger.exception(
                "Cognito rejected admin password reset: invalid parameter."
            )
            messages.error(
                request,
                "El correo o identificador de usuario no es válido.",
            )
            return redirect("accounts:user-list")
        except CognitoLimitExceededError as exc:
            logger.error(
                "Cognito LimitExceeded for user_id=%s identifier=%s: %s",
                target_user.id,
                identifier,
                str(exc),
            )
            logger.exception(
                "Cognito rejected admin password reset: limit exceeded."
            )
            messages.error(
                request,
                "Se excedió el límite de intentos. Espera unos minutos e intenta nuevamente.",
            )
            return redirect("accounts:user-list")
        except CognitoNetworkError as exc:
            logger.error(
                "Cognito NetworkError for user_id=%s identifier=%s: %s",
                target_user.id,
                identifier,
                str(exc),
            )
            logger.exception(
                "Cognito admin password reset failed: network error."
            )
            messages.error(
                request,
                "No se pudo conectar con Cognito. Verifica la conexión e intenta nuevamente.",
            )
            return redirect("accounts:user-list")
        except CognitoConfigurationError as exc:
            logger.error(
                "Cognito ConfigurationError for user_id=%s identifier=%s: %s",
                target_user.id,
                identifier,
                str(exc),
            )
            logger.exception(
                "Cognito admin password reset failed: configuration error."
            )
            messages.error(
                request,
                "La configuración de Cognito no es válida. Contacta al administrador.",
            )
            return redirect("accounts:user-list")
        except CognitoNotAuthorizedError as exc:
            logger.error(
                "Cognito NotAuthorized for user_id=%s identifier=%s: %s",
                target_user.id,
                identifier,
                str(exc),
            )
            logger.exception(
                "Cognito rejected admin password reset: not authorized."
            )
            messages.error(
                request,
                "No tienes autorización para restablecer la contraseña de este usuario.",
            )
            return redirect("accounts:user-list")
        except CognitoSignUpClientError as exc:
            logger.error(
                "Cognito unexpected error for user_id=%s identifier=%s: %s",
                target_user.id,
                identifier,
                str(exc),
            )
            logger.exception(
                "Cognito admin password reset failed with an unexpected error."
            )
            messages.error(
                request,
                "No fue posible iniciar el restablecimiento de contrasena en NeuroFlex. Intenta nuevamente.",
            )
            return redirect("accounts:user-list")

        log_event(
            actor=request.user,
            action="password_reset_requested",
            resource_type="user",
            resource_id=target_user.pk,
            result=AuditLog.Result.SUCCESS,
            ip_address=get_client_ip(request),
            metadata={"username": target_user.username},
        )
        display_name = target_user.get_full_name() or target_user.get_username()
        messages.success(
            request,
            f"Se envió un código de recuperación al correo de {display_name}. "
            "El usuario debe usar ese código en la página de confirmación para definir su nueva contraseña.",
        )
        return redirect("accounts:user-list")


_HEALTH_TIMEOUT_SECONDS = 5
_HEALTH_MAX_REDIRECTS = 3
_LOCAL_ADDRESSES = {"127.0.0.1", "::1"}
_PROXY_HEADERS = {
    "HTTP_FORWARDED",
    "HTTP_X_FORWARDED_FOR",
    "HTTP_X_REAL_IP",
    "HTTP_X_FORWARDED_HOST",
    "HTTP_X_FORWARDED_PROTO",
}


def _is_local_request(request):
    return (
        request.META.get("REMOTE_ADDR") in _LOCAL_ADDRESSES
        and not _PROXY_HEADERS.intersection(request.META)
    )


class LocalConfigView(View):
    """Expose the editable local configuration as JSON."""

    def dispatch(self, request, *args, **kwargs):
        if not _is_local_request(request):
            return JsonResponse({"error": "Acceso denegado."}, status=403)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        return JsonResponse(read_config())

    def post(self, request, *args, **kwargs):
        try:
            payload = json.loads(request.body.decode("utf-8")) if request.body else {}
        except (ValueError, UnicodeDecodeError):
            return JsonResponse({"error": "JSON inválido."}, status=400)

        if not isinstance(payload, dict):
            return JsonResponse({"error": "JSON inválido."}, status=400)

        try:
            result = write_config(payload)
        except LocalConfigValidationError as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        except OSError:
            return JsonResponse(
                {"error": "No fue posible guardar la configuración."}, status=500
            )
        except Exception:
            return JsonResponse(
                {"error": "No fue posible guardar la configuración."}, status=500
            )
        return JsonResponse(result)


class ApiHealthCheckView(View):
    """Check the configured NeuroFlex API without blocking page rendering."""

    def dispatch(self, request, *args, **kwargs):
        if not _is_local_request(request):
            return JsonResponse({"error": "Acceso denegado."}, status=403)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        try:
            base_url = RuntimeConfig().get_neuroflex_api_base_url()
            try:
                parsed = urlparse(base_url)
            except ValueError:
                return JsonResponse({"available": False})
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                return JsonResponse({"available": False})
            health_url = parsed._replace(
                path=f"{parsed.path.rstrip('/')}/health",
                query="",
                fragment="",
            ).geturl()

            with requests.Session() as session:
                session.max_redirects = _HEALTH_MAX_REDIRECTS
                response = session.get(
                    health_url, timeout=_HEALTH_TIMEOUT_SECONDS
                )
            available = 200 <= response.status_code < 300
        except requests.RequestException:
            available = False
        return JsonResponse({"available": available})


class ForcedConnectivityModeView(View):
    """Permite forzar el modo de conexión en la pantalla de login (solo local)."""

    def dispatch(self, request, *args, **kwargs):
        if not _is_local_request(request):
            return JsonResponse({"error": "Acceso denegado."}, status=403)
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        target = request.POST.get("mode")
        if target == "offline":
            force_offline(request.session)
            action = "login_mode_forced_offline"
        elif target == "online":
            force_online_retry(request.session)
            action = "login_mode_forced_online"
        else:
            return HttpResponseBadRequest("Modo invalido.")

        log_event(
            actor=request.user if request.user.is_authenticated else None,
            action=action,
            resource_type="session",
            resource_id=request.session.session_key or "",
            result=AuditLog.Result.SUCCESS,
            ip_address=get_client_ip(request),
            metadata={},
        )
        return redirect("accounts:login")
