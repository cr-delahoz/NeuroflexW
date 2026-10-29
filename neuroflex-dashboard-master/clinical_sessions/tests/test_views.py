from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from clinical_sessions.services.external_session_client import (
    ExternalSessionServiceUnavailableError,
)

User = get_user_model()


class ClinicalSessionViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin_user = User.objects.create_user(
            username="admin_user",
            password="test-pass-123",
            role=User.Role.ADMIN,
        )
        cls.specialist_user = User.objects.create_user(
            username="specialist_user",
            password="test-pass-123",
            role=User.Role.SPECIALIST,
        )

    def _login_with_neuroflex_session(self):
        self.client.login(username="specialist_user", password="test-pass-123")
        session = self.client.session
        session["cognito_id_token"] = "fake-id-token"
        session["cognito_sub"] = "fake-sub"
        session.save()

    def test_unauthenticated_user_cannot_view_sessions(self):
        response = self.client.get(reverse("clinical_sessions:session-list"))

        self.assertEqual(response.status_code, 302)

    def test_admin_cannot_view_session_list(self):
        self.client.login(username="admin_user", password="test-pass-123")

        response = self.client.get(reverse("clinical_sessions:session-list"))

        self.assertEqual(response.status_code, 403)

    def test_admin_cannot_view_session_detail(self):
        self.client.login(username="admin_user", password="test-pass-123")

        response = self.client.get(
            reverse("clinical_sessions:session-detail", args=["SESSION-001"])
        )

        self.assertEqual(response.status_code, 403)

    def test_unauthenticated_user_cannot_view_session_detail(self):
        response = self.client.get(
            reverse("clinical_sessions:session-detail", args=["SESSION-001"])
        )

        self.assertEqual(response.status_code, 302)

    def test_missing_neuroflex_session_returns_404_on_detail(self):
        self.client.login(username="specialist_user", password="test-pass-123")

        with patch(
            "clinical_sessions.views.get_session_confirmed_by"
        ) as mock_get_session:
            response = self.client.get(
                reverse("clinical_sessions:session-detail", args=["SESSION-001"])
            )

        mock_get_session.assert_not_called()
        self.assertEqual(response.status_code, 404)

    @patch("clinical_sessions.views.get_session_confirmed_by", return_value=None)
    def test_session_not_owned_by_specialist_returns_404(self, mock_get_session):
        self._login_with_neuroflex_session()

        response = self.client.get(
            reverse("clinical_sessions:session-detail", args=["SESSION-001"])
        )

        self.assertEqual(response.status_code, 404)
        mock_get_session.assert_called_once_with(
            "fake-sub", "fake-id-token", "SESSION-001"
        )

    @patch(
        "clinical_sessions.views.get_session_confirmed_by",
        side_effect=ExternalSessionServiceUnavailableError("down"),
    )
    def test_api_unavailable_on_detail_does_not_break_page(self, mock_get_session):
        self._login_with_neuroflex_session()

        response = self.client.get(
            reverse("clinical_sessions:session-detail", args=["SESSION-001"])
        )

        self.assertEqual(response.status_code, 502)
        self.assertContains(response, "down", status_code=502)

    @patch("clinical_sessions.views.get_session_confirmed_by")
    def test_session_detail_shows_metrics_sorted_and_rounded(self, mock_get_session):
        mock_get_session.return_value = {
            "session_id": "SESSION-001",
            "display_code": "123456",
            "created_at": "2026-07-08T20:01:19.146575+00:00",
            "vr_user_email": None,
            "status": "completed",
            "metrics": {
                "TipoEscena": 1,
                "CantAciertasTotales": 1,
                "Precision": 100.0,
                "TiempoActivoTarea": 215.869,
            },
        }
        self._login_with_neuroflex_session()

        response = self.client.get(
            reverse("clinical_sessions:session-detail", args=["SESSION-001"])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Metricas de la sesion")
        content = response.content.decode()
        self.assertLess(
            content.index("CantAciertasTotales"), content.index("Precision")
        )
        self.assertLess(content.index("Precision"), content.index("TipoEscena"))
        self.assertContains(response, "215.87")

    @patch("clinical_sessions.views.get_session_confirmed_by")
    def test_session_detail_without_metrics_shows_empty_state(self, mock_get_session):
        mock_get_session.return_value = {
            "session_id": "SESSION-001",
            "display_code": "123456",
            "created_at": "2026-07-08T20:01:19.146575+00:00",
            "vr_user_email": None,
            "status": "confirmed",
            "metrics": None,
        }
        self._login_with_neuroflex_session()

        response = self.client.get(
            reverse("clinical_sessions:session-detail", args=["SESSION-001"])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sin metricas disponibles")
        self.assertContains(response, "Resultado automatizado no disponible")

    @patch("clinical_sessions.views.get_session_confirmed_by")
    def test_session_detail_shows_automated_result_section_when_available(
        self, mock_get_session
    ):
        mock_get_session.return_value = {
            "session_id": "SESSION-001",
            "display_code": "123456",
            "created_at": "2026-07-08T20:01:19.146575+00:00",
            "vr_user_email": None,
            "status": "completed",
            "metrics": {
                "TiempoRespuestaPararse": 2.5,
                "TiempoRespuestaPregunta1": 3.1,
                "TiempoRespuestaPregunta2": 3.8,
                "TiempoRespuestaPregunta3": 4.2,
                "TiempoReaccionVisual": 0.9,
                "TiempoCapturarNumero": 2.8,
            },
        }
        self._login_with_neuroflex_session()

        response = self.client.get(
            reverse("clinical_sessions:session-detail", args=["SESSION-001"])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Resultado automatizado (provisional)")
        self.assertContains(response, "Confianza tecnica asociada")
        self.assertContains(response, "Resultado provisional generado")
