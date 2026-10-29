import json
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase

from clinical_sessions.services.local_session_provider import (
    DuplicateSessionError,
    LocalSessionProvider,
    SessionNotFoundError,
)


class LocalSessionProviderTests(SimpleTestCase):
    def test_returns_configured_storage_path(self):
        provider = LocalSessionProvider()

        self.assertTrue(
            str(provider.get_storage_path()).endswith(
                "clinical_sessions\\data\\local_sessions"
            )
        )

    def test_lists_folders_and_normalized_sessions(self):
        with TemporaryDirectory() as temp_dir:
            base_path = Path(temp_dir)
            folder = base_path / "Sesion_1_20251013"
            folder.mkdir(parents=True)
            session_file = folder / "session-a.json"
            session_file.write_text(
                json.dumps(
                    {
                        "session_id": "session-a",
                        "timestamp": "2025-10-13T19:16:15.691686",
                        "patient_info": {
                            "name": "Paciente Demo",
                            "age": 73,
                            "rut": "1-9",
                        },
                        "data": {"Precision": 91.5, "TipoEscena": 1},
                    }
                ),
                encoding="utf-8",
            )

            provider = LocalSessionProvider(base_path=base_path)
            payload = provider.list_sessions()

            self.assertEqual(payload["folders"], ["Sesion_1_20251013"])
            self.assertEqual(len(payload["sessions"]), 1)
            self.assertEqual(payload["errors"], [])
            self.assertEqual(payload["sessions"][0]["session_id"], "session-a")
            self.assertEqual(
                payload["sessions"][0]["source_folder"], "Sesion_1_20251013"
            )
            self.assertEqual(
                payload["sessions"][0]["metrics"],
                {"precision": 91.5, "scene_type": 1},
            )
            self.assertEqual(
                payload["sessions"][0]["patient"]["age"],
                73,
            )

    def test_collects_errors_for_invalid_files_without_breaking_listing(self):
        with TemporaryDirectory() as temp_dir:
            base_path = Path(temp_dir)
            folder = base_path / "Sesion_1_20251013"
            folder.mkdir(parents=True)
            (folder / "valid.json").write_text(
                json.dumps(
                    {
                        "session_id": "session-a",
                        "timestamp": "2025-10-13T19:16:15.691686",
                        "data": {"Precision": 91.5},
                    }
                ),
                encoding="utf-8",
            )
            (folder / "invalid.json").write_text("{invalid", encoding="utf-8")

            provider = LocalSessionProvider(base_path=base_path)
            payload = provider.list_sessions()

            self.assertEqual(len(payload["sessions"]), 1)
            self.assertEqual(len(payload["errors"]), 1)
            self.assertEqual(payload["errors"][0]["source_file"], "invalid.json")

    def test_loads_one_session_by_identifier(self):
        with TemporaryDirectory() as temp_dir:
            base_path = Path(temp_dir)
            folder = base_path / "Sesion_2_20251016"
            folder.mkdir(parents=True)
            (folder / "session-b.json").write_text(
                json.dumps(
                    {
                        "session_id": "session-b",
                        "timestamp": "2025-10-16T19:05:01.681841",
                        "patient_info": {"name": "Paciente B"},
                        "data": {"Precision": 80.0},
                    }
                ),
                encoding="utf-8",
            )

            provider = LocalSessionProvider(base_path=base_path)
            payload = provider.get_session_by_id("session-b")

            self.assertEqual(payload["session_id"], "session-b")
            self.assertTrue(payload["has_patient_info"])
            self.assertEqual(payload["metrics"]["precision"], 80.0)

    def test_raises_not_found_for_unknown_session(self):
        with TemporaryDirectory() as temp_dir:
            provider = LocalSessionProvider(base_path=Path(temp_dir))

            with self.assertRaises(SessionNotFoundError):
                provider.get_session_by_id("missing-session")

    def test_raises_duplicate_session_error_when_identifier_is_reused(self):
        with TemporaryDirectory() as temp_dir:
            base_path = Path(temp_dir)
            folder_a = base_path / "Sesion_1_20251013"
            folder_b = base_path / "Sesion_2_20251016"
            folder_a.mkdir(parents=True)
            folder_b.mkdir(parents=True)
            payload = {
                "session_id": "duplicated-session",
                "timestamp": "2025-10-16T19:05:01.681841",
                "data": {"Precision": 80.0},
            }
            (folder_a / "session-a.json").write_text(
                json.dumps(payload),
                encoding="utf-8",
            )
            (folder_b / "session-b.json").write_text(
                json.dumps(payload),
                encoding="utf-8",
            )

            provider = LocalSessionProvider(base_path=base_path)

            with self.assertRaises(DuplicateSessionError):
                provider.get_session_by_id("duplicated-session")

    def test_handles_missing_optional_patient_info(self):
        with TemporaryDirectory() as temp_dir:
            base_path = Path(temp_dir)
            folder = base_path / "Sesion_3_20251020"
            folder.mkdir(parents=True)
            (folder / "session-c.json").write_text(
                json.dumps(
                    {
                        "session_id": "session-c",
                        "timestamp": "2025-10-20T19:13:59.316949",
                        "data": {"Precision": 77.0},
                    }
                ),
                encoding="utf-8",
            )

            provider = LocalSessionProvider(base_path=base_path)
            payload = provider.get_session_by_id("session-c")

            self.assertFalse(payload["has_patient_info"])
            self.assertEqual(
                payload["warnings"],
                ["La sesion no incluye informacion general del paciente."],
            )

    def test_normalizes_consistent_structure_between_sessions(self):
        with TemporaryDirectory() as temp_dir:
            base_path = Path(temp_dir)
            folder = base_path / "Sesion_4_20251023"
            folder.mkdir(parents=True)
            for index in range(2):
                (folder / f"session-{index}.json").write_text(
                    json.dumps(
                        {
                            "session_id": f"session-{index}",
                            "timestamp": f"2025-10-23T19:0{index}:13.408089",
                            "data": {"Precision": 90 + index, "TipoEscena": index},
                        }
                    ),
                    encoding="utf-8",
                )

            provider = LocalSessionProvider(base_path=base_path)
            payload = provider.list_sessions()

            session_keys = [set(session.keys()) for session in payload["sessions"]]
            self.assertEqual(session_keys[0], session_keys[1])
