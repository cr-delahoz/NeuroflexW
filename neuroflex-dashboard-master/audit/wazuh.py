"""Privacy-preserving JSONL export of audit events for Wazuh.

Wazuh reads this local file with ``log_format=json``.  The payload deliberately
does not include audit metadata, user names, session identifiers, clinical
metrics, report contents, or authentication tokens.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from pathlib import Path

from django.conf import settings


logger = logging.getLogger(__name__)


def _fingerprint(value: str) -> str:
    """Return a stable, non-reversible correlation value for a resource."""
    secret = settings.WAZUH_AUDIT_HASH_KEY or settings.SECRET_KEY
    return hmac.new(
        secret.encode("utf-8"), value.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def build_wazuh_event(audit_log: object) -> dict:
    """Map an AuditLog instance to the minimal event schema sent to Wazuh."""
    actor = audit_log.actor
    return {
        "@timestamp": audit_log.created_at.isoformat(),
        "event": {
            "kind": "event",
            "action": audit_log.action,
            "outcome": "success" if audit_log.result == "SUCCESS" else "failure",
        },
        "observer": {"product": "NeuroFlex Dashboard"},
        "user": {
            "id": str(actor.pk) if actor else None,
            "roles": [actor.role] if actor and actor.role else [],
        },
        "source": {"ip": audit_log.ip_address} if audit_log.ip_address else {},
        "resource": {
            "type": audit_log.resource_type,
            "fingerprint": _fingerprint(
                f"{audit_log.resource_type}:{audit_log.resource_id}"
            ),
        },
        "neuroflex": {"schema_version": "1.0"},
    }


def emit_wazuh_event(audit_log: object) -> None:
    """Append one JSON event when a Wazuh log path is configured.

    Wazuh delivery failures must never interrupt a clinical or administrative
    action; the primary database audit remains the system of record.
    """
    configured_path = settings.WAZUH_AUDIT_LOG_PATH
    if not configured_path:
        return

    try:
        path = Path(configured_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(build_wazuh_event(audit_log), separators=(",", ":")))
            log_file.write("\n")
    except (OSError, TypeError, ValueError):
        logger.exception("Unable to emit NeuroFlex audit event to Wazuh.")
