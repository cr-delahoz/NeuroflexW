"""Small helpers for account provisioning that don't belong in views/forms."""

import logging
import secrets
import string
import time

from django.contrib.auth import get_user_model
from django.db import IntegrityError, models, transaction

from audit.models import AuditLog
from audit.services import get_client_ip, log_event
from accounts.models import Profession
from integrations.services.api_gateway_users_client import (
    ApiGatewayUsersInvalidResponseError,
    ApiGatewayUsersNotFoundError,
    ApiGatewayUsersServiceError,
)
from integrations.services.cognito_auth_client import (
    CognitoAuthClient,
    CognitoAuthClientError,
)
from integrations.services.cognito_claims import decode_jwt_claims

_LENGTH = 14
_SYMBOLS = "!@#$%^&*()-_=+"

User = get_user_model()
logger = logging.getLogger(__name__)
REMOTE_ROLE_TO_LOCAL_ROLE = {
    "Administrator": User.Role.ADMIN,
    "Specialist": User.Role.SPECIALIST,
}


def sync_professions_from_remote(token, professions_client):
    """Mirror the remote professions catalog into the local Profession table.

    The remote API is the source of truth: professions removed remotely are
    deleted locally (users keep SET_NULL so they fall back to the default
    label). Returns the list of local Profession objects.
    """
    from accounts.models import Profession

    remote_professions = professions_client.list_professions(token)
    required = {"profession_id", "name"}
    for profession in remote_professions:
        if (
            not isinstance(profession, dict)
            or not required.issubset(set(profession))
            or not profession["profession_id"]
            or not profession["name"]
        ):
            raise ValueError("Remote profession payload is incomplete or invalid.")

    remote_ids = {profession["profession_id"] for profession in remote_professions}
    with transaction.atomic():
        Profession.objects.exclude(pk__in=remote_ids).delete()
        local_professions = []
        for profession in remote_professions:
            local_professions.append(
                Profession.objects.update_or_create(
                    pk=profession["profession_id"],
                    defaults={
                        "name": profession["name"],
                        "is_default": bool(profession.get("is_default", False)),
                        "is_active": bool(profession.get("is_active", True)),
                        "created_at": _epoch_to_datetime(profession.get("created_at")),
                    },
                )[0]
            )
    return local_professions


def _epoch_to_datetime(value):
    if not value:
        return None
    from datetime import datetime, timezone as dt_timezone

    try:
        return datetime.fromtimestamp(int(value), tz=dt_timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def generate_temporary_password():
    """Return a random password meeting Cognito's default password policy.

    Cognito's default policy requires at least 8 characters with an
    uppercase letter, a lowercase letter, a digit and a symbol. Plain
    `get_random_string(12)` only produces lowercase letters/digits and gets
    rejected with InvalidPasswordException, so this builds the password from
    explicit character pools and shuffles the result.
    """
    required = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice(_SYMBOLS),
    ]
    remaining_pool = string.ascii_letters + string.digits + _SYMBOLS
    required += [secrets.choice(remaining_pool) for _ in range(_LENGTH - len(required))]

    password_chars = required[:]
    secrets.SystemRandom().shuffle(password_chars)
    return "".join(password_chars)


def get_or_create_user_from_cognito_claims(username_input, claims, request=None):
    """Resolve or provision a local Django user from verified Cognito claims.

    Returns a tuple (user, created). If the user cannot be resolved or created
    safely (e.g. missing `sub` or unresolvable username collision), returns
    (None, False).
    """
    sub = claims.get("sub")
    if not sub:
        return None, False

    email = claims.get("email", "")
    cognito_username = claims.get("cognito:username")
    final_username = email if email else (cognito_username if cognito_username else username_input)

    # 1. Find by Cognito sub (already linked).
    user = User.objects.filter(cognito_sub=sub).first()
    if user is not None:
        return user, False

    # 2. Find by username and backfill sub if the local account is unlinked.
    user = User.objects.filter(username=final_username).first()
    if user is not None:
        if not user.cognito_sub:
            user.cognito_sub = sub
            user.save(update_fields=["cognito_sub"])
            return user, False
        # Existing account is linked to a different sub: treat as collision.
        return None, False

    # 3. Username collision fallback: try alternative username.
    if final_username == email:
        alt_username = cognito_username if cognito_username else username_input
    else:
        alt_username = username_input
    if alt_username and alt_username != final_username:
        user = User.objects.filter(username=alt_username).first()
        if user is not None:
            if not user.cognito_sub:
                user.cognito_sub = sub
                user.save(update_fields=["cognito_sub"])
                return user, False
            # Existing account is linked to a different sub: treat as collision.
            return None, False

    # 4. Create new local user automatically.
    try:
        new_user = User.objects.create(
            username=final_username,
            email=email,
            cognito_sub=sub,
            role=User.Role.SPECIALIST,
            is_active=True,
        )
        new_user.set_unusable_password()
        new_user.save(update_fields=["password"])
    except Exception:
        # Any creation failure (e.g. race condition) is treated as unresolved.
        return None, False

    _log_auto_created_user(new_user, request)
    return new_user, True


def _log_auto_created_user(user, request):
    """Record audit trail for automatically provisioned users."""
    log_event(
        actor=None,
        action="user_created",
        resource_type="user",
        resource_id=str(user.pk),
        result=AuditLog.Result.SUCCESS,
        ip_address=get_client_ip(request) if request else None,
        metadata={
            "username": user.username,
            "role": user.role,
            "auto_created": True,
        },
    )


def sync_local_user_from_remote_user(remote_user):
    required = {"user_id", "email"}
    if (
        not isinstance(remote_user, dict)
        or not required.issubset(set(remote_user))
        or not remote_user["user_id"]
        or not remote_user["email"]
    ):
        raise ValueError("Remote user payload is incomplete or invalid.")

    if "role" in remote_user:
        remote_role = remote_user["role"]
        if not isinstance(remote_role, str) or remote_role not in REMOTE_ROLE_TO_LOCAL_ROLE:
            raise ValueError("Remote role is invalid.")
    if "is_active" in remote_user:
        remote_is_active = remote_user["is_active"]
        if not isinstance(remote_is_active, bool):
            raise ValueError("Remote is_active must be a boolean.")

    user = User.objects.filter(cognito_sub=remote_user["user_id"]).first()
    if user is None:
        user = User.objects.filter(
            models.Q(email__iexact=remote_user["email"])
            | models.Q(username__iexact=remote_user["email"])
        ).first()
        if user is not None and user.cognito_sub not in (None, "", remote_user["user_id"]):
            logger.warning(
                "User %s had mismatched cognito_sub; updated from %s to %s",
                remote_user["email"],
                user.cognito_sub,
                remote_user["user_id"],
            )
    if user is None:
        try:
            user = User.objects.create(username=remote_user["email"])
        except IntegrityError:
            user = User.objects.get(username=remote_user["email"])
        else:
            user.set_unusable_password()
            user.save(update_fields=["password"])
    user.cognito_sub = remote_user["user_id"]
    user.email = remote_user["email"]
    if user.username != remote_user["email"]:
        if User.objects.filter(username__iexact=remote_user["email"]).exclude(pk=user.pk).exists():
            logger.warning(
                "Cannot update username for user %s to %s because another user already has that username",
                user.email,
                remote_user["email"],
            )
        else:
            user.username = remote_user["email"]
    if "role" in remote_user:
        user.role = REMOTE_ROLE_TO_LOCAL_ROLE[remote_user["role"]]

    if "profession_id" in remote_user:
        profession_id = remote_user.get("profession_id")
        if isinstance(profession_id, str) and profession_id:
            user.profession = Profession.objects.filter(pk=profession_id).first()
        else:
            user.profession = None

    if "is_active" in remote_user:
        user.is_active = remote_user["is_active"]
    if remote_user.get("onboarding_status"):
        user.onboarding_status = remote_user["onboarding_status"]
    if remote_user.get("cognito_status"):
        user.cognito_status = remote_user["cognito_status"]
    if remote_user.get("first_name"):
        user.first_name = remote_user["first_name"]
    if remote_user.get("last_name"):
        user.last_name = remote_user["last_name"]
    user.save()
    return user


def reconcile_local_users_from_remote_listing(token, users_client):
    remote_users = []
    next_token = None
    seen_tokens = set()
    while True:
        page_users, next_token = users_client.list_users(
            token, limit=50, next_token=next_token
        )
        remote_users.extend(page_users)
        if next_token is None:
            break
        if next_token in seen_tokens:
            raise ApiGatewayUsersServiceError("Remote user pagination token repeated.")
        seen_tokens.add(next_token)
    required = {"user_id", "email"}
    for remote_user in remote_users:
        if (
            not isinstance(remote_user, dict)
            or not required.issubset(set(remote_user))
            or not remote_user["user_id"]
            or not remote_user["email"]
        ):
            raise ValueError("Remote user payload is incomplete or invalid.")
    remote_ids = {remote_user["user_id"] for remote_user in remote_users}
    confirmations = []
    local_users_to_confirm = list(
        User.objects.exclude(cognito_sub__isnull=True)
        .exclude(cognito_sub="")
        .exclude(cognito_sub__in=remote_ids)
    )
    for local_user in local_users_to_confirm:
        try:
            confirmed_remote_user = users_client.get_user(token, local_user.cognito_sub)
        except ApiGatewayUsersNotFoundError:
            confirmations.append((local_user, None))
        except (ApiGatewayUsersServiceError, ApiGatewayUsersInvalidResponseError):
            continue
        else:
            confirmations.append((local_user, confirmed_remote_user))
    for _, remote_user in confirmations:
        if remote_user is None:
            continue
        if (
            not isinstance(remote_user, dict)
            or not required.issubset(set(remote_user))
            or not remote_user["user_id"]
            or not remote_user["email"]
        ):
            raise ValueError("Remote user payload is incomplete or invalid.")
    with transaction.atomic():
        local_users = [
            sync_local_user_from_remote_user(remote_user) for remote_user in remote_users
        ]
        for local_user, confirmed_remote_user in confirmations:
            if confirmed_remote_user is None:
                local_user.delete()
            else:
                local_users.append(sync_local_user_from_remote_user(confirmed_remote_user))
    return local_users


# Refresh the ID token this many seconds before it actually expires, so an
# in-flight request never hits API Gateway with a token that just lapsed.
_TOKEN_REFRESH_MARGIN_SECONDS = 120


def get_valid_cognito_token(request):
    """Return a usable Cognito ID token from the request session.

    Tokens issued by Cognito live about one hour. When the stored token is
    expired (or about to expire), it is renewed with the refresh token kept
    in the session instead of failing the request. The refresh outcome is
    audited for traceability. Returns None when no usable token can be
    produced; the caller must then redirect to the login page.
    """
    session = request.session
    token = session.get("cognito_id_token")
    if not token:
        return None
    if not _token_expires_soon(token, session.get("cognito_id_token_expires_at")):
        return token
    return _refresh_cognito_token(request)


def _token_expires_soon(token, stored_expires_at):
    expires_at = stored_expires_at
    if expires_at is None:
        claims = decode_jwt_claims(token)
        expires_at = claims.get("exp") if isinstance(claims, dict) else None
    try:
        expires_at = float(expires_at)
    except (TypeError, ValueError):
        # No reliable expiry information: keep using the token and let the
        # backend API decide whether it is still accepted.
        return False
    return expires_at - time.time() <= _TOKEN_REFRESH_MARGIN_SECONDS


def _refresh_cognito_token(request):
    session = request.session
    refresh_token = session.get("cognito_refresh_token")
    actor = request.user if getattr(request, "user", None) and request.user.is_authenticated else None
    try:
        auth_result = CognitoAuthClient().refresh_tokens(refresh_token)
    except CognitoAuthClientError:
        log_event(
            actor=actor,
            action="cognito_token_refresh_failed",
            resource_type="session",
            resource_id=session.session_key or "",
            result=AuditLog.Result.FAILURE,
            ip_address=get_client_ip(request),
            metadata={"username": actor.username if actor else ""},
        )
        # Clear the unusable token so callers redirect to login instead of
        # repeating a doomed refresh on every request.
        session.pop("cognito_id_token", None)
        session.pop("cognito_refresh_token", None)
        session.pop("cognito_access_token", None)
        session.pop("cognito_id_token_expires_at", None)
        return None

    new_token = auth_result["id_token"]
    session["cognito_id_token"] = new_token
    access_token = auth_result.get("access_token")
    if access_token:
        session["cognito_access_token"] = access_token
    claims = decode_jwt_claims(new_token)
    exp = claims.get("exp") if isinstance(claims, dict) else None
    if isinstance(exp, (int, float)):
        session["cognito_id_token_expires_at"] = int(exp)

    log_event(
        actor=actor,
        action="cognito_token_refreshed",
        resource_type="session",
        resource_id=session.session_key or "",
        result=AuditLog.Result.SUCCESS,
        ip_address=get_client_ip(request),
        metadata={"username": actor.username if actor else ""},
    )
    return new_token
