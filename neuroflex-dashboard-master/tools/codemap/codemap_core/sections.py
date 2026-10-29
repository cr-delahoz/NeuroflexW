"""Clasificación de archivos en secciones según reglas de `codemap.config.json`."""

from __future__ import annotations

import json
import re
from pathlib import Path

UNCLASSIFIED = "Sin clasificar"


def glob_to_regex(pattern: str) -> re.Pattern:
    """Glob con `**` (cualquier número de carpetas), `*` y `?`."""
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            out += ".*"
            i += 2
        elif pattern[i] == "*":
            out += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile(f"^{out}$", re.IGNORECASE)


def load_config(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {"excluir": [], "secciones": []}
    return json.loads(path.read_text(encoding="utf-8"))


class SectionMatcher:
    def __init__(self, config: dict, extra_exclude: list[str] | None = None):
        self._exclude = [glob_to_regex(p) for p in [*config.get("excluir", []), *(extra_exclude or [])]]
        self._rules = []
        for rule in config.get("secciones", []):
            self._rules.append((
                rule["nombre"],
                [glob_to_regex(p) for p in rule.get("rutas", [])],
                [re.compile(p) for p in rule.get("contenido", [])],
            ))
        self.sections = [
            {"nombre": r["nombre"], "descripcion": r.get("descripcion", "")}
            for r in config.get("secciones", [])
        ] + [{"nombre": UNCLASSIFIED, "descripcion": "Archivos que no coinciden con ninguna regla."}]

    def excluded(self, path: str) -> bool:
        return any(p.match(path) for p in self._exclude)

    def section_for(self, path: str, text: str | None = None) -> str:
        for name, globs, content in self._rules:
            if any(g.match(path) for g in globs):
                return name
            if content and text and any(c.search(text) for c in content):
                return name
        return UNCLASSIFIED

    def order(self, name: str) -> int:
        for i, section in enumerate(self.sections):
            if section["nombre"] == name:
                return i
        return len(self.sections)
