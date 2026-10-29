"""Human-readable translations for AuditLog.action codes and metadata keys.

Used by the PDF export (audit/pdf_builder.py) and available for the on-screen
log table too. Both humanize_* helpers are deliberately fail-soft: a new
action or metadata key added in the future without updating this file must
degrade to a readable fallback, never raise.
"""

ACTION_LABELS = {
    # accounts
    "user_logged_in": "Inicio de sesion",
    "user_login_failed": "Intento de inicio de sesion fallido",
    "user_logged_out": "Cierre de sesion",
    "authorization_denied": "Acceso denegado por permisos insuficientes",
    "specialist_account_confirmed": "Cuenta de especialista confirmada",
    "password_reset_self_requested": "Solicitud de restablecimiento de contrasena (propia)",
    "password_reset_confirmed": "Contrasena restablecida",
    "user_name_updated": "Nombre de usuario actualizado",
    "user_created": "Usuario creado",
    "user_activated": "Usuario activado",
    "user_deactivated": "Usuario desactivado",
    "pdf_permission_granted": "Permiso de generacion de PDF sin aprobacion otorgado",
    "pdf_permission_revoked": "Permiso de generacion de PDF sin aprobacion revocado",
    "user_deleted": "Usuario eliminado",
    "password_reset_requested": "Restablecimiento de contrasena solicitado por un administrador",
    # reports
    "report_request_duplicate": "Solicitud de informe duplicada (rechazada)",
    "report_requested": "Informe solicitado",
    "report_approved": "Informe aprobado",
    "report_rejected": "Informe rechazado",
    "report_downloaded": "Informe descargado",
    "unassociated_report_downloaded": "Informe sin especialista descargado por un administrador",
    "unassociated_report_generated": "Informe sin especialista generado por un administrador",
    "pdf_auto_generated": "PDF generado automaticamente (sin aprobacion)",
    "report_generation_started": "Generacion de informe iniciada",
    "report_generated": "Informe generado",
    "report_generation_failed": "Fallo en la generacion del informe",
    # clinical_sessions
    "session_list_viewed": "Listado de sesiones consultado",
    "session_detail_viewed": "Detalle de sesion consultado",
    "session_confirmed": "Sesion confirmada y asociada",
    "inference_executed": "Inferencia automatizada ejecutada",
    "unassociated_sessions_viewed": "Listado de sesiones sin especialista consultado",
    # audit
    "audit_exported": "Registro de auditoria exportado (CSV)",
    "audit_exported_pdf": "Registro de auditoria exportado (PDF)",
}

METADATA_KEY_LABELS = {
    "username": "Usuario",
    "role": "Rol",
    "active": "Estado",
    "session_id": "ID de sesion",
    "first_name": "Nombre",
    "last_name": "Apellido",
    "filters": "Filtros aplicados",
    "exported_rows": "Filas exportadas",
    "status": "Estado",
    "active_sessions": "Sesiones activas",
    "completed_sessions": "Sesiones completadas",
    "orphaned_sessions": "Sesiones sin especialista",
    "start_date": "Desde",
    "end_date": "Hasta",
    "actor": "Usuario (ID)",
    "action": "Accion",
    "result": "Resultado",
}

ROLE_LABELS = {
    "ADMIN": "Administrador",
    "SPECIALIST": "Especialista",
}


def humanize_action(action):
    """Translate an AuditLog.action code to a Spanish phrase.

    Never raises: unmapped codes degrade to the raw code with underscores
    turned into spaces, so a future action added without updating
    ACTION_LABELS still reads as something reasonable instead of a KeyError.
    """
    if not action:
        return "Accion no especificada"

    label = ACTION_LABELS.get(action)
    if label:
        return label

    return str(action).replace("_", " ").strip().capitalize()


def _humanize_value(value):
    if isinstance(value, bool):
        return "Si" if value else "No"
    if value in (None, ""):
        return "No disponible"
    if isinstance(value, dict):
        if not value:
            return "Sin datos"
        return ", ".join(
            f"{METADATA_KEY_LABELS.get(key, key)}: {_humanize_value(item)}"
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value) if value else "Sin datos"
    if value in ROLE_LABELS:
        return ROLE_LABELS[value]
    return str(value)


def humanize_metadata(metadata):
    """Turn a raw AuditLog.metadata dict into a readable summary string.

    Handles the audit_exported/audit_exported_pdf shape specially: its
    "filters" key is itself a flat dict, which gets flattened the same way
    as the top level instead of dumped as a raw dict repr.
    """
    if not metadata:
        return "Sin detalles adicionales."

    parts = []
    for key, value in metadata.items():
        label = METADATA_KEY_LABELS.get(key, key)
        if key == "filters" and isinstance(value, dict):
            if not value:
                continue
            sub_parts = [
                f"{METADATA_KEY_LABELS.get(sub_key, sub_key)}: {_humanize_value(sub_value)}"
                for sub_key, sub_value in value.items()
            ]
            parts.append(f"{label}: " + ", ".join(sub_parts))
            continue
        parts.append(f"{label}: {_humanize_value(value)}")

    return " · ".join(parts) if parts else "Sin detalles adicionales."
