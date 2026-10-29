"""Session ownership: which specialist owns which external session_id."""

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from ..models import SpecialistSession
from .external_session_client import confirm_display_code
from .session_status import is_session_active


class SessionAlreadyAssociatedError(Exception):
    """Raised when a display code confirms a session already owned by someone else."""


def list_owned_session_ids(user):
    return list(
        SpecialistSession.objects.filter(specialist=user).values_list(
            "session_id", flat=True
        )
    )


def is_session_owned_by(user, session_id):
    return SpecialistSession.objects.filter(
        specialist=user, session_id=session_id
    ).exists()


def cache_session_metrics(session_id, metrics):
    """Persist a completed session's metrics on its local SpecialistSession row.

    This keeps a local copy so an admin can still generate a PDF after the
    owning specialist is deleted (the external API filters by the deleted
    specialist's sub and would no longer return it). Only updates existing
    rows; never creates one. Safe to call opportunistically.
    """
    if not metrics:
        return
    SpecialistSession.objects.filter(session_id=session_id).update(
        metrics=metrics, metrics_synced_at=timezone.now()
    )


def list_active_sessions_for_specialist(user):
    return [
        session
        for session in SpecialistSession.objects.filter(specialist=user)
        if is_session_active(session.status)
    ]


def confirm_and_associate_session(user, display_code, id_token, *, api_client=None):
    """Confirm a display code and associate the resulting session to `user`.

    `id_token` is the specialist's own Cognito IdToken obtained at login time.

    Raises SessionAlreadyAssociatedError if the session_id already belongs to
    a different specialist (a VR session belongs to exactly one specialist).
    """
    detail = confirm_display_code(display_code, id_token, api_client=api_client)
    session_id = detail["session_id"]

    existing = SpecialistSession.objects.filter(session_id=session_id).first()
    if existing is not None and existing.specialist_id != user.id:
        raise SessionAlreadyAssociatedError(
            "This session is already associated with another specialist."
        )

    terms_accepted_at = None
    if detail.get("terms_accepted_at"):
        terms_accepted_at = parse_datetime(detail["terms_accepted_at"])

    session, _created = SpecialistSession.objects.update_or_create(
        session_id=session_id,
        defaults={
            "specialist": user,
            "status": detail.get("status", ""),
            "terms_version_id": detail.get("terms_version_id", ""),
            "terms_language": detail.get("terms_language", ""),
            "terms_content_hash": detail.get("terms_content_hash", ""),
            "terms_accepted_at": terms_accepted_at,
            "terms_acceptance_token": detail.get("terms_acceptance_token", ""),
            "vr_application_version": detail.get("vr_application_version", ""),
        },
    )
    return session
