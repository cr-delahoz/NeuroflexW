from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from clinical_sessions.models import SpecialistSession
from clinical_sessions.services.specialist_session_service import (
    SessionAlreadyAssociatedError,
    confirm_and_associate_session,
    is_session_owned_by,
    list_active_sessions_for_specialist,
    list_owned_session_ids,
)

User = get_user_model()


class SpecialistSessionServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.specialist = User.objects.create_user(
            username="specialist_one",
            password="test-pass-123",
            role=User.Role.SPECIALIST,
        )
        cls.other_specialist = User.objects.create_user(
            username="specialist_two",
            password="test-pass-123",
            role=User.Role.SPECIALIST,
        )

    def _confirm_response(self, **overrides):
        response = {
            "session_id": "abc123",
            "status": "confirmed",
            "terms_version_id": "v1.0.0",
            "terms_language": "es",
            "terms_content_hash": "sha256-fake",
            "terms_accepted_at": "2026-07-06T12:05:00Z",
            "terms_acceptance_token": "uuid-fake",
            "vr_application_version": "1.2.3",
        }
        response.update(overrides)
        return response

    @patch("clinical_sessions.services.specialist_session_service.confirm_display_code")
    def test_confirm_and_associate_creates_session(self, mock_confirm):
        mock_confirm.return_value = self._confirm_response()

        session = confirm_and_associate_session(
            self.specialist, "123456", "fake-id-token", api_client=Mock()
        )

        self.assertEqual(session.session_id, "abc123")
        self.assertEqual(session.specialist, self.specialist)
        self.assertEqual(session.terms_version_id, "v1.0.0")
        self.assertIsNotNone(session.terms_accepted_at)
        self.assertTrue(
            is_session_owned_by(self.specialist, "abc123")
        )
        self.assertIn("abc123", list_owned_session_ids(self.specialist))
        self.assertEqual(mock_confirm.call_args.args, ("123456", "fake-id-token"))

    @patch("clinical_sessions.services.specialist_session_service.confirm_display_code")
    def test_confirm_and_associate_updates_existing_owned_session(self, mock_confirm):
        mock_confirm.return_value = self._confirm_response(status="confirmed")
        confirm_and_associate_session(
            self.specialist, "123456", "fake-id-token", api_client=Mock()
        )

        mock_confirm.return_value = self._confirm_response(status="in_progress")
        session = confirm_and_associate_session(
            self.specialist, "123456", "fake-id-token", api_client=Mock()
        )

        self.assertEqual(session.status, "in_progress")
        self.assertEqual(SpecialistSession.objects.count(), 1)

    @patch("clinical_sessions.services.specialist_session_service.confirm_display_code")
    def test_confirm_and_associate_rejects_session_owned_by_other_specialist(
        self, mock_confirm
    ):
        mock_confirm.return_value = self._confirm_response()
        confirm_and_associate_session(
            self.specialist, "123456", "fake-id-token", api_client=Mock()
        )

        mock_confirm.return_value = self._confirm_response()
        with self.assertRaises(SessionAlreadyAssociatedError):
            confirm_and_associate_session(
                self.other_specialist, "123456", "fake-id-token", api_client=Mock()
            )

    def test_is_session_owned_by_is_false_for_unknown_session(self):
        self.assertFalse(is_session_owned_by(self.specialist, "unknown-session"))

    @patch("clinical_sessions.services.specialist_session_service.confirm_display_code")
    def test_list_active_sessions_excludes_completed(self, mock_confirm):
        mock_confirm.return_value = self._confirm_response(
            session_id="active-session", status="confirmed"
        )
        confirm_and_associate_session(
            self.specialist, "111111", "fake-id-token", api_client=Mock()
        )

        mock_confirm.return_value = self._confirm_response(
            session_id="finished-session", status="completed"
        )
        confirm_and_associate_session(
            self.specialist, "222222", "fake-id-token", api_client=Mock()
        )

        active_ids = [
            session.session_id
            for session in list_active_sessions_for_specialist(self.specialist)
        ]

        self.assertEqual(active_ids, ["active-session"])
