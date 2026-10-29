import json
from pathlib import Path

from django.conf import settings
from django.utils.dateparse import parse_datetime


class LocalSessionProviderError(Exception):
    """Base exception for local session loading errors."""


class SessionNotFoundError(LocalSessionProviderError):
    """Raised when no session matches the requested identifier."""


class DuplicateSessionError(LocalSessionProviderError):
    """Raised when more than one file shares the same session identifier."""


class LocalSessionProvider:
    """
    Read and normalize local NeuroFlex session JSON files without modifying them.

    Current observed structure:
    - one folder per session batch / working day
    - one JSON file per individual session
    - top-level keys usually include session_id, timestamp, patient_info and data
    """

    def __init__(self, base_path=None):
        self.base_path = Path(
            base_path or settings.SESSION_LOCAL_DATA_PATH
        )

    METRIC_DEFINITIONS = [
        ("Precision", "precision", "Precision"),
        ("TiempoActivoTarea", "active_task_time", "Tiempo activo en la tarea"),
        ("CantAciertasTotales", "total_correct_answers", "Cantidad total de aciertos"),
        (
            "ObjetosInteractuadosCorrectamente",
            "correct_interacted_objects",
            "Objetos interactuados correctamente",
        ),
        ("TiempoTutorial", "tutorial_time", "Tiempo del tutorial"),
        ("TipoEscena", "scene_type", "Tipo de escena"),
        (
            "TiempoRespuestaPararse",
            "stand_response_time",
            "Tiempo de respuesta al levantarse",
        ),
        (
            "TiempoRespuestaPregunta1",
            "question_1_response_time",
            "Tiempo de respuesta de la pregunta 1",
        ),
        (
            "TiempoRespuestaPregunta2",
            "question_2_response_time",
            "Tiempo de respuesta de la pregunta 2",
        ),
        (
            "TiempoRespuestaPregunta3",
            "question_3_response_time",
            "Tiempo de respuesta de la pregunta 3",
        ),
        (
            "TiempoCapturarNumero",
            "number_capture_time",
            "Tiempo utilizado para capturar el numero",
        ),
    ]

    def get_storage_path(self):
        """Return the directory where local session folders will be copied."""
        return self.base_path

    def list_session_folders(self):
        if not self.base_path.exists():
            return []
        return sorted(path for path in self.base_path.iterdir() if path.is_dir())

    def list_json_files(self):
        if not self.base_path.exists():
            return []
        return sorted(self.base_path.rglob("*.json"))

    def list_sessions(self):
        """
        Return normalized local sessions and non-fatal file loading errors.

        Invalid files are reported in `errors` and skipped from the returned
        session list so one bad file does not break the full listing.
        """
        sessions = []
        errors = []

        for file_path in self.list_json_files():
            try:
                raw_session = self._read_json_file(file_path)
                sessions.append(self._normalize_session(raw_session, file_path))
            except LocalSessionProviderError as exc:
                errors.append(
                    {
                        "source_file": file_path.name,
                        "source_folder": file_path.parent.name,
                        "message": str(exc),
                    }
                )

        sessions.sort(key=lambda item: item.get("evaluated_at") or "", reverse=True)

        return {
            "source": "local",
            "source_label": (
                "Los datos mostrados corresponden temporalmente a sesiones "
                "cargadas de forma local mientras se completa la integracion "
                "con NeuroFlex."
            ),
            "storage_path": str(self.base_path),
            "folders": [folder.name for folder in self.list_session_folders()],
            "sessions": sessions,
            "errors": errors,
        }

    def get_session_by_id(self, session_id):
        matches = []

        for file_path in self.list_json_files():
            raw_session = self._read_json_file(file_path)
            if raw_session.get("session_id") == session_id:
                matches.append((raw_session, file_path))

        if not matches:
            raise SessionNotFoundError(
                f"No local session was found for identifier '{session_id}'."
            )

        if len(matches) > 1:
            raise DuplicateSessionError(
                f"More than one local file uses session_id '{session_id}'."
            )

        raw_session, file_path = matches[0]
        return self._normalize_session(raw_session, file_path)

    def _read_json_file(self, file_path):
        try:
            return json.loads(file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise LocalSessionProviderError(
                f"Invalid JSON content in '{file_path.name}'."
            ) from exc
        except OSError as exc:
            raise LocalSessionProviderError(
                f"Could not read '{file_path.name}'."
            ) from exc

    def _normalize_session(self, raw_session, file_path):
        if not isinstance(raw_session, dict):
            raise LocalSessionProviderError(
                f"Unexpected root JSON type in '{file_path.name}'."
            )

        if "session_id" not in raw_session:
            raise LocalSessionProviderError(
                f"Missing required key 'session_id' in '{file_path.name}'."
            )

        if "timestamp" not in raw_session:
            raise LocalSessionProviderError(
                f"Missing required key 'timestamp' in '{file_path.name}'."
            )

        if "data" not in raw_session:
            raise LocalSessionProviderError(
                f"Missing required key 'data' in '{file_path.name}'."
            )

        patient_info = raw_session.get("patient_info")
        if patient_info is not None and not isinstance(patient_info, dict):
            raise LocalSessionProviderError(
                f"Invalid 'patient_info' structure in '{file_path.name}'."
            )

        data = raw_session.get("data")
        if not isinstance(data, dict):
            raise LocalSessionProviderError(
                f"Invalid 'data' structure in '{file_path.name}'."
            )

        evaluated_at = parse_datetime(raw_session["timestamp"]) or raw_session["timestamp"]
        patient_updated_at = None
        if patient_info and patient_info.get("updated_at"):
            patient_updated_at = (
                parse_datetime(patient_info["updated_at"]) or patient_info["updated_at"]
            )

        return {
            "session_id": raw_session["session_id"],
            "evaluated_at": evaluated_at,
            "evaluated_at_raw": raw_session["timestamp"],
            "source_folder": file_path.parent.name,
            "source_file": file_path.name,
            "availability_status": "LOCAL_AVAILABLE",
            "availability_label": "Disponible localmente",
            "raw_keys": sorted(raw_session.keys()),
            "has_patient_info": patient_info is not None,
            "patient": {
                "internal_id": None,
                "age": patient_info.get("age") if patient_info else None,
                "dominant_hand": (
                    patient_info.get("dominant_hand") if patient_info else None
                ),
                "updated_at": patient_updated_at,
            },
            "metrics": self._normalize_metrics(data),
            "performance_items": self._build_performance_items(data),
            "general_items": self._build_general_items(raw_session, patient_info, data),
            "cognitive_result": {},
            "cognitive_result_items": [],
            "warnings": self._build_warnings(patient_info),
        }

    def _normalize_metrics(self, data):
        normalized = {}
        for source_key, normalized_key, _ in self.METRIC_DEFINITIONS:
            if source_key in data:
                normalized[normalized_key] = data[source_key]
        return normalized

    def _build_performance_items(self, data):
        items = []
        for source_key, normalized_key, label in self.METRIC_DEFINITIONS:
            if source_key in data:
                items.append(
                    {
                        "key": normalized_key,
                        "label": label,
                        "value": data[source_key],
                    }
                )
        return items

    def _build_general_items(self, raw_session, patient_info, data):
        items = [
            {
                "label": "Identificador de sesion",
                "value": raw_session["session_id"],
            },
            {
                "label": "Fecha de evaluacion",
                "value": raw_session["timestamp"],
            },
        ]

        if patient_info and patient_info.get("age") is not None:
            items.append({"label": "Edad", "value": patient_info["age"]})

        if patient_info and patient_info.get("dominant_hand"):
            items.append(
                {
                    "label": "Mano dominante",
                    "value": patient_info["dominant_hand"],
                }
            )

        if "TipoEscena" in data:
            items.append({"label": "Tipo de escena", "value": data["TipoEscena"]})

        return items

    def _build_warnings(self, patient_info):
        warnings = []
        if patient_info is None:
            warnings.append(
                "La sesion no incluye informacion general del paciente."
            )
        return warnings
