from django.test import SimpleTestCase

from clinical_sessions.services.session_status import is_session_active


class IsSessionActiveTests(SimpleTestCase):
    def test_confirmed_is_active(self):
        self.assertTrue(is_session_active("confirmed"))

    def test_in_progress_is_active(self):
        self.assertTrue(is_session_active("in_progress"))

    def test_completed_is_not_active(self):
        self.assertFalse(is_session_active("completed"))

    def test_is_case_insensitive(self):
        self.assertFalse(is_session_active("COMPLETED"))

    def test_empty_status_is_active(self):
        self.assertTrue(is_session_active(""))
        self.assertTrue(is_session_active(None))
