from audit.models import AuditLog


ALLOWED_METADATA_KEYS = frozenset({"name", "reason", "on_behalf_of", "duplicate"})
_SCALAR_TYPES = (str, int, float, bool, type(None))


def log_offline_event(*, actor, action, resource_type, resource_id="",
                      result="SUCCESS", ip_address=None, metadata=None):
    """Registra eventos del modo offline. NUNCA incluir datos clínicos en metadata."""
    safe_metadata = {
        k: v for k, v in (metadata or {}).items()
        if k in ALLOWED_METADATA_KEYS and isinstance(v, _SCALAR_TYPES)
    }
    return AuditLog.objects.create(
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id),
        result=result,
        ip_address=ip_address,
        metadata=safe_metadata,
    )
