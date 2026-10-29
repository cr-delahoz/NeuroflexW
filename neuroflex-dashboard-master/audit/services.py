from audit.models import AuditLog
from audit.wazuh import emit_wazuh_event


SENSITIVE_KEYS = {
    "password",
    "password1",
    "password2",
    "temporary_password",
    "token",
    "access_token",
    "refresh_token",
    "secret",
}


def sanitize_metadata(value):
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            if key.lower() in SENSITIVE_KEYS:
                continue
            sanitized[key] = sanitize_metadata(item)
        return sanitized

    if isinstance(value, list):
        return [sanitize_metadata(item) for item in value]

    return value


def get_client_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def log_event(
    *,
    actor,
    action,
    resource_type,
    resource_id="",
    result,
    ip_address=None,
    metadata=None,
):
    audit_log = AuditLog.objects.create(
        actor=actor,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id),
        result=result,
        ip_address=ip_address,
        metadata=sanitize_metadata(metadata or {}),
    )
    emit_wazuh_event(audit_log)
    return audit_log
