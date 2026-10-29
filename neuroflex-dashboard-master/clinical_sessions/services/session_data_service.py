from django.conf import settings

from clinical_sessions.services.local_session_provider import LocalSessionProvider


class UnsupportedSessionDataSourceError(Exception):
    pass


class SessionDataService:
    def __init__(self, source=None):
        self.source = source

    def _get_provider(self):
        source = self.source or settings.SESSION_DATA_SOURCE

        if source == "local":
            return LocalSessionProvider()

        raise UnsupportedSessionDataSourceError(
            f"Unsupported session data source '{source}'."
        )

    def list_sessions(self):
        return self._get_provider().list_sessions()

    def get_session(self, session_id):
        return self._get_provider().get_session_by_id(session_id)
