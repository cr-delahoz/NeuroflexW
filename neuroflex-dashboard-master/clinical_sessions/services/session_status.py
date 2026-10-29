"""Isolated, easily-adjustable rule for what counts as an active VR session.

ASSUMPTION: the external API's session status lifecycle is not finalized yet.
Known candidate values so far: "confirmed", "in_progress", "completed". Until
the API documents a definitive list, treat everything except a known
"finished" set as active. Adjust `_FINISHED_STATUSES` here only.
"""

_FINISHED_STATUSES = {"completed"}


def is_session_active(status):
    return (status or "").strip().lower() not in _FINISHED_STATUSES
