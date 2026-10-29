from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from clinical_sessions.models import SpecialistSession
from clinical_sessions.services import cache_session_metrics

User = get_user_model()


class CacheSessionMetricsServiceTests(TestCase):
    def test_updates_existing_row_with_metrics(self):
        session = SpecialistSession.objects.create(
            specialist=None, session_id="S1", status="completed"
        )
        cache_session_metrics("S1", {"TipoEscena": 1})

        session.refresh_from_db()
        self.assertEqual(session.metrics, {"TipoEscena": 1})
        self.assertIsNotNone(session.metrics_synced_at)

    def test_ignores_empty_metrics(self):
        session = SpecialistSession.objects.create(
            specialist=None, session_id="S1", status="completed"
        )
        cache_session_metrics("S1", {})

        session.refresh_from_db()
        self.assertEqual(session.metrics, {})
        self.assertIsNone(session.metrics_synced_at)

    def test_does_not_create_a_missing_row(self):
        cache_session_metrics("MISSING", {"TipoEscena": 1})
        self.assertFalse(SpecialistSession.objects.filter(session_id="MISSING").exists())


class SessionDetailCachesMetricsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="spec", password="p", role=User.Role.SPECIALIST
        )
        SpecialistSession.objects.create(
            specialist=cls.user, session_id="SESS-1", status="confirmed"
        )

    def setUp(self):
        self.client.force_login(self.user)
        session = self.client.session
        session["cognito_id_token"] = "tok"
        session["cognito_sub"] = "sub"
        session.save()

    @patch(
        "clinical_sessions.views.predict_cognitive_result",
        return_value={"available": False},
    )
    @patch("clinical_sessions.views.get_session_confirmed_by")
    def test_detail_caches_completed_metrics(self, mock_get, _mock_pred):
        mock_get.return_value = {
            "session_id": "SESS-1",
            "status": "completed",
            "created_at": "2026-07-09T20:00:00+00:00",
            "metrics": {"TipoEscena": 2},
        }

        response = self.client.get(
            reverse("clinical_sessions:session-detail", args=["SESS-1"])
        )

        self.assertEqual(response.status_code, 200)
        row = SpecialistSession.objects.get(session_id="SESS-1")
        self.assertEqual(row.metrics, {"TipoEscena": 2})
        self.assertIsNotNone(row.metrics_synced_at)
