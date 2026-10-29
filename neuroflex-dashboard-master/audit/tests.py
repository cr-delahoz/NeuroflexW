import csv
import json
from io import StringIO
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .action_labels import humanize_action, humanize_metadata
from .models import AuditLog
from .services import log_event


User = get_user_model()


class AuditModuleTests(TestCase):
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

    def test_log_event_creates_sanitized_audit_log(self):
        log_event(
            actor=self.admin_user,
            action="user_created",
            resource_type="user",
            resource_id=self.specialist_user.pk,
            result=AuditLog.Result.SUCCESS,
            ip_address="127.0.0.1",
            metadata={
                "username": "specialist_user",
                "password": "secret-value",
                "token": "abc",
            },
        )

        log = AuditLog.objects.get()
        self.assertEqual(log.action, "user_created")
        self.assertEqual(log.resource_type, "user")
        self.assertEqual(log.resource_id, str(self.specialist_user.pk))
        self.assertEqual(log.result, AuditLog.Result.SUCCESS)
        self.assertEqual(log.ip_address, "127.0.0.1")
        self.assertEqual(log.metadata, {"username": "specialist_user"})

    def test_log_event_exports_minimal_json_for_wazuh(self):
        with TemporaryDirectory() as directory:
            log_path = f"{directory}/security-audit.jsonl"
            with override_settings(
                WAZUH_AUDIT_LOG_PATH=log_path,
                WAZUH_AUDIT_HASH_KEY="test-wazuh-key",
            ):
                log_event(
                    actor=self.specialist_user,
                    action="session_detail_viewed",
                    resource_type="clinical_session",
                    resource_id="SESSION-SECRET-001",
                    result=AuditLog.Result.SUCCESS,
                    ip_address="127.0.0.1",
                    metadata={"session_id": "SESSION-SECRET-001", "metrics": {"x": 1}},
                )

            with open(log_path, encoding="utf-8") as exported:
                event = json.loads(exported.readline())

        self.assertEqual(event["event"]["action"], "session_detail_viewed")
        self.assertEqual(event["event"]["outcome"], "success")
        self.assertEqual(event["user"]["id"], str(self.specialist_user.pk))
        self.assertEqual(event["resource"]["type"], "clinical_session")
        self.assertNotIn("SESSION-SECRET-001", json.dumps(event))
        self.assertNotIn("metrics", json.dumps(event))

    def test_admin_can_view_filtered_audit_logs(self):
        log_event(
            actor=self.admin_user,
            action="user_created",
            resource_type="user",
            resource_id=self.specialist_user.pk,
            result=AuditLog.Result.SUCCESS,
            metadata={"username": "specialist_user"},
        )
        log_event(
            actor=self.admin_user,
            action="user_deactivated",
            resource_type="user",
            resource_id=self.specialist_user.pk,
            result=AuditLog.Result.FAILURE,
            metadata={"username": "specialist_user"},
        )
        self.client.login(username="admin_user", password="test-pass-123")

        response = self.client.get(
            reverse("audit:log-list"),
            {"action": "user_created", "result": AuditLog.Result.SUCCESS},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "user_created")
        self.assertNotContains(response, "user_deactivated")

    def test_non_admin_cannot_view_audit_logs(self):
        self.client.login(username="specialist_user", password="test-pass-123")

        response = self.client.get(reverse("audit:log-list"))

        self.assertEqual(response.status_code, 403)

    def test_unauthenticated_user_is_redirected_from_audit_logs(self):
        response = self.client.get(reverse("audit:log-list"))

        self.assertEqual(response.status_code, 302)

    def test_admin_can_export_filtered_audit_logs_to_csv(self):
        log_event(
            actor=self.admin_user,
            action="user_created",
            resource_type="user",
            resource_id=self.specialist_user.pk,
            result=AuditLog.Result.SUCCESS,
            metadata={"username": "specialist_user"},
        )
        log_event(
            actor=self.admin_user,
            action="user_deactivated",
            resource_type="user",
            resource_id=self.specialist_user.pk,
            result=AuditLog.Result.FAILURE,
            metadata={"username": "specialist_user"},
        )
        self.client.login(username="admin_user", password="test-pass-123")

        response = self.client.get(
            reverse("audit:log-export"),
            {"action": "user_created", "result": AuditLog.Result.SUCCESS},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
        rows = list(csv.DictReader(StringIO(response.content.decode("utf-8"))))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["action"], "user_created")
        self.assertTrue(
            AuditLog.objects.filter(
                actor=self.admin_user,
                action="audit_exported",
                resource_type="audit_log",
                result=AuditLog.Result.SUCCESS,
            ).exists()
        )

    def test_admin_can_filter_logs_by_actor_and_date(self):
        older_log = AuditLog.objects.create(
            actor=self.admin_user,
            action="older_action",
            resource_type="user",
            resource_id=str(self.specialist_user.pk),
            result=AuditLog.Result.SUCCESS,
            metadata={},
        )
        older_log.created_at = timezone.now() - timezone.timedelta(days=3)
        older_log.save(update_fields=["created_at"])
        recent_log = AuditLog.objects.create(
            actor=self.specialist_user,
            action="recent_action",
            resource_type="report",
            resource_id="42",
            result=AuditLog.Result.SUCCESS,
            metadata={},
        )
        self.client.login(username="admin_user", password="test-pass-123")

        response = self.client.get(
            reverse("audit:log-list"),
            {
                "actor": str(self.specialist_user.pk),
                "start_date": (timezone.now().date() - timezone.timedelta(days=1)).isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "recent_action")
        self.assertNotContains(response, "older_action")


class ActionLabelsTests(TestCase):
    def test_humanize_action_returns_mapped_label(self):
        self.assertEqual(humanize_action("user_created"), "Usuario creado")

    def test_humanize_action_falls_back_for_unmapped_code(self):
        self.assertEqual(
            humanize_action("some_future_action"), "Some future action"
        )

    def test_humanize_action_handles_empty_value(self):
        self.assertEqual(humanize_action(""), "Accion no especificada")
        self.assertEqual(humanize_action(None), "Accion no especificada")

    def test_humanize_metadata_handles_empty_dict(self):
        self.assertEqual(humanize_metadata({}), "Sin detalles adicionales.")

    def test_humanize_metadata_translates_known_keys(self):
        result = humanize_metadata({"username": "jdoe", "role": "SPECIALIST"})
        self.assertIn("Usuario: jdoe", result)
        self.assertIn("Rol: Especialista", result)

    def test_humanize_metadata_falls_back_for_unmapped_key(self):
        result = humanize_metadata({"totally_unknown_key": "value123"})
        self.assertIn("totally_unknown_key: value123", result)

    def test_humanize_metadata_renders_booleans(self):
        result = humanize_metadata({"active": True})
        self.assertIn("Estado: Si", result)
        result = humanize_metadata({"active": False})
        self.assertIn("Estado: No", result)

    def test_humanize_metadata_flattens_nested_filters(self):
        result = humanize_metadata(
            {
                "filters": {"action": "user_created", "result": "SUCCESS"},
                "exported_rows": 3,
            }
        )
        self.assertIn("Filtros aplicados:", result)
        self.assertIn("Accion: user_created", result)
        self.assertIn("Resultado: SUCCESS", result)
        self.assertIn("Filas exportadas: 3", result)

    def test_humanize_metadata_handles_empty_filters(self):
        result = humanize_metadata({"filters": {}, "exported_rows": 0})
        self.assertNotIn("Filtros aplicados", result)
        self.assertIn("Filas exportadas: 0", result)


class AuditPdfExportTests(TestCase):
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

    def test_non_admin_cannot_export_pdf(self):
        self.client.login(username="specialist_user", password="test-pass-123")

        response = self.client.get(reverse("audit:log-export-pdf"))

        self.assertEqual(response.status_code, 403)

    def test_unauthenticated_user_is_redirected_from_pdf_export(self):
        response = self.client.get(reverse("audit:log-export-pdf"))

        self.assertEqual(response.status_code, 302)

    def test_admin_can_export_pdf_with_zero_results(self):
        self.client.login(username="admin_user", password="test-pass-123")

        response = self.client.get(
            reverse("audit:log-export-pdf"), {"action": "no-such-action"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF-"))
        self.assertIn(b"No hay eventos en el rango seleccionado", response.content)

    def test_pdf_export_respects_same_filters_as_csv_export(self):
        log_event(
            actor=self.admin_user,
            action="user_created",
            resource_type="user",
            resource_id=self.specialist_user.pk,
            result=AuditLog.Result.SUCCESS,
            metadata={"username": "specialist_user"},
        )
        log_event(
            actor=self.admin_user,
            action="user_deactivated",
            resource_type="user",
            resource_id=self.specialist_user.pk,
            result=AuditLog.Result.FAILURE,
            metadata={"username": "specialist_user"},
        )
        self.client.login(username="admin_user", password="test-pass-123")
        query = {"action": "user_created", "result": AuditLog.Result.SUCCESS}

        csv_response = self.client.get(reverse("audit:log-export"), query)
        pdf_response = self.client.get(reverse("audit:log-export-pdf"), query)

        rows = list(csv.DictReader(StringIO(csv_response.content.decode("utf-8"))))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["action"], "user_created")

        self.assertTrue(pdf_response.content.startswith(b"%PDF-"))
        self.assertIn(b"Usuario creado", pdf_response.content)
        self.assertNotIn(b"Usuario desactivado", pdf_response.content)

    def test_pdf_export_logs_audit_exported_pdf_event(self):
        self.client.login(username="admin_user", password="test-pass-123")

        self.client.get(reverse("audit:log-export-pdf"))

        self.assertTrue(
            AuditLog.objects.filter(
                actor=self.admin_user,
                action="audit_exported_pdf",
                resource_type="audit_log",
                result=AuditLog.Result.SUCCESS,
            ).exists()
        )

    def test_pdf_export_handles_unmapped_action_without_crashing(self):
        AuditLog.objects.create(
            actor=self.admin_user,
            action="some_brand_new_action",
            resource_type="user",
            resource_id="1",
            result=AuditLog.Result.SUCCESS,
            metadata={},
        )
        self.client.login(username="admin_user", password="test-pass-123")

        response = self.client.get(reverse("audit:log-export-pdf"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF-"))
        self.assertIn(b"Some brand new action", response.content)

    def test_pdf_export_handles_unmapped_metadata_key_without_crashing(self):
        AuditLog.objects.create(
            actor=self.admin_user,
            action="user_created",
            resource_type="user",
            resource_id="1",
            result=AuditLog.Result.SUCCESS,
            metadata={"some_future_field": "unexpected-value"},
        )
        self.client.login(username="admin_user", password="test-pass-123")

        response = self.client.get(reverse("audit:log-export-pdf"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF-"))
        self.assertIn(b"some_future_field", response.content)
        self.assertIn(b"unexpected-value", response.content)

    def test_pdf_export_handles_null_actor(self):
        AuditLog.objects.create(
            actor=None,
            action="password_reset_self_requested",
            resource_type="user",
            resource_id="",
            result=AuditLog.Result.SUCCESS,
            metadata={},
        )
        self.client.login(username="admin_user", password="test-pass-123")

        response = self.client.get(reverse("audit:log-export-pdf"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF-"))
        self.assertIn(b"Sistema", response.content)

    def test_pdf_export_paginates_large_result_sets(self):
        for index in range(60):
            AuditLog.objects.create(
                actor=self.admin_user,
                action="session_list_viewed",
                resource_type="clinical_session",
                resource_id=str(index),
                result=AuditLog.Result.SUCCESS,
                metadata={"active_sessions": index, "completed_sessions": index},
            )
        self.client.login(username="admin_user", password="test-pass-123")

        response = self.client.get(reverse("audit:log-export-pdf"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF-"))
        # More than one landscape table page should have been created, so
        # more than one Type /Page object exists in the assembled PDF.
        self.assertGreater(response.content.count(b"/Type /Page "), 1)

class AuditPdfAccentExportTests(TestCase):
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

    def test_pdf_export_encodes_accented_characters(self):
        self.admin_user.first_name = "Nicolás"
        self.admin_user.last_name = "Muñoz"
        self.admin_user.save(update_fields=["first_name", "last_name"])
        log_event(
            actor=self.admin_user,
            action="user_created",
            resource_type="user",
            resource_id="1",
            result=AuditLog.Result.SUCCESS,
            metadata={"username": "jose.nuñez"},
        )
        self.client.login(username="admin_user", password="test-pass-123")

        response = self.client.get(reverse("audit:log-export-pdf"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("Nicolás Muñoz".encode("latin-1"), response.content)

