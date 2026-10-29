"""Anotaciones de la IA: lo que el agente *dice* que hizo, superpuesto al diff.

El diff sigue siendo la fuente de verdad. Una anotación solo se acepta para un
cambio que existe (`Change.id`) y queda ligada a su huella: si el código cambia
después, la anotación pasa a "desactualizada". Los cambios sin anotar se marcan
como "no declarados" y las anotaciones sobre ids inexistentes como
"declaraciones sin respaldo".
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .analyze import TOOL_DIR
from .model import ChangeSet

DEFAULT_STORE = TOOL_DIR / "out" / "anotaciones"
ANNOTATED = "anotado"
UNDECLARED = "no_declarado"
STALE = "desactualizado"


def _empty() -> dict:
    return {"tarea": None, "autor": None, "fecha": None, "cambios": {}}


def store_path(base_commit: str, store_dir: Path | None = None) -> Path:
    # Un archivo por commit base: las anotaciones siguen valiendo con --base <sha>
    # aunque HEAD avance después de un commit.
    return (store_dir or DEFAULT_STORE) / f"{base_commit or 'sin-commits'}.json"


def load(base_commit: str, store_dir: Path | None = None) -> dict:
    path = store_path(base_commit, store_dir)
    if not path.exists():
        return _empty()
    data = json.loads(path.read_text(encoding="utf-8"))
    return {**_empty(), **data}


def save(base_commit: str, store: dict, store_dir: Path | None = None) -> Path:
    path = store_path(base_commit, store_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"base_commit": base_commit, **store}, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path


def clear(base_commit: str, store_dir: Path | None = None) -> bool:
    path = store_path(base_commit, store_dir)
    if path.exists():
        path.unlink()
        return True
    return False


def parse_input(text: str) -> dict:
    """Valida el JSON que escribe la IA.

    Formato: {"tarea": str, "autor": str, "cambios": {id: "resumen"}}
    También se acepta "cambios" como lista de {"id": ..., "resumen": ...}.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"El archivo de anotaciones no es JSON válido: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Se esperaba un objeto JSON con las claves 'tarea' y 'cambios'.")

    raw = data.get("cambios", {})
    if isinstance(raw, list):
        try:
            raw = {item["id"]: item["resumen"] for item in raw}
        except (KeyError, TypeError) as exc:
            raise ValueError("Cada elemento de 'cambios' debe tener 'id' y 'resumen'.") from exc
    if not isinstance(raw, dict):
        raise ValueError("'cambios' debe ser un objeto {id: resumen} o una lista.")

    changes = {}
    for change_id, summary in raw.items():
        if isinstance(summary, dict):
            summary = summary.get("resumen")
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError(f"El resumen de '{change_id}' está vacío o no es texto.")
        changes[str(change_id)] = summary.strip()

    task = data.get("tarea")
    if task is not None and not isinstance(task, str):
        raise ValueError("'tarea' debe ser texto.")
    author = data.get("autor")
    return {"tarea": task.strip() if task else None, "autor": str(author) if author else None,
            "cambios": changes}


def record(changeset: ChangeSet, store: dict, incoming: dict) -> dict:
    """Fusiona las anotaciones nuevas en `store` (se modifica) con la huella actual."""
    current = {c.id: c for c in changeset.cambios}
    if incoming["tarea"]:
        store["tarea"] = incoming["tarea"]
    if incoming["autor"]:
        store["autor"] = incoming["autor"]
    store["fecha"] = datetime.now().isoformat(timespec="seconds")
    for change_id, summary in incoming["cambios"].items():
        change = current.get(change_id)
        store["cambios"][change_id] = {"resumen": summary, "huella": change.huella if change else None}
    return store


def apply(changeset: ChangeSet, store: dict) -> ChangeSet:
    """Marca cada cambio como anotado, no declarado o desactualizado."""
    if not store["cambios"] and not store["tarea"]:
        return changeset  # nadie anotó esta revisión: no hay nada que contrastar
    current_ids = set()
    for change in changeset.cambios:
        current_ids.add(change.id)
        note = store["cambios"].get(change.id)
        if note is None:
            change.estado_anotacion = UNDECLARED
            continue
        change.resumen_ia = note["resumen"]
        change.estado_anotacion = ANNOTATED if note.get("huella") == change.huella else STALE
    changeset.tarea = store["tarea"]
    changeset.autor_anotaciones = store["autor"]
    changeset.declaraciones_sin_respaldo = [
        {"id": change_id, "resumen": note["resumen"]}
        for change_id, note in store["cambios"].items() if change_id not in current_ids
    ]
    return changeset
