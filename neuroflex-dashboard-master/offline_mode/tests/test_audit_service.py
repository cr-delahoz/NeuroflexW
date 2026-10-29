from django.test import TestCase
from audit.models import AuditLog
from offline_mode.services.audit_service import log_offline_event
from offline_mode.services.checksums import sha256_hex, compute_metrics_checksum


class AuditServiceTests(TestCase):
    def test_log_event_creates_audit_row(self):
        log_offline_event(actor=None, action="DEVICE_PAIRED", resource_type="device",
                          resource_id="abc", result="SUCCESS", metadata={"name": "Quest-A4F2"})
        row = AuditLog.objects.get(action="DEVICE_PAIRED")
        self.assertEqual(row.resource_id, "abc")
        self.assertNotIn("metrics", (row.metadata or {}))

    def test_metadata_is_filtered_to_allowlist(self):
        log_offline_event(actor=None, action="X", resource_type="t",
                          metadata={"name": "ok", "metrics": {"Precision": 1},
                                    "patient_info": {}})
        row = AuditLog.objects.get(action="X")
        self.assertEqual(row.metadata, {"name": "ok"})

    def test_metadata_nested_values_are_dropped(self):
        log_offline_event(actor=None, action="Y", resource_type="t",
                          metadata={"name": {"patient_info": {"age": 70}},
                                    "reason": "ok"})
        row = AuditLog.objects.get(action="Y")
        self.assertEqual(row.metadata, {"reason": "ok"})


class ChecksumTests(TestCase):
    def test_sha256_hex_known_value(self):
        self.assertEqual(sha256_hex("123456"),
                         "8d969eef6ecad3c29a3a629280e686cf0c3f5d5a86aff3ca12020c923adc6c92")

    def test_metrics_checksum_is_order_independent(self):
        a = {"Precision": 1.0, "TipoEscena": 2}
        b = {"TipoEscena": 2, "Precision": 1.0}
        self.assertEqual(compute_metrics_checksum(a), compute_metrics_checksum(b))
