"""Etiquetas de efectos secundarios detectadas por patrones deterministas.

Se buscan sobre las líneas añadidas. Los controles de acceso se buscan además
en las eliminadas: quitar un `@login_required` es tan importante como añadir
una llamada de red.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True)
class Tag:
    nombre: str
    riesgo: int  # 1 bajo, 2 medio, 3 alto
    frase: str   # completa "la función X ... <frase>"
    origen: str  # "añadidas" | "eliminadas" | "ruta" | "análisis"


_PERMISSIONS = re.compile(
    r"\b(login_required|permission_required|user_passes_test|has_perms?|PermissionDenied"
    r"|\w*(Login|Permission|Role)\w*Mixin|UserPassesTestMixin|is_staff|is_superuser"
    r"|is_authenticated|allowed_roles|(login|permission|role|roles|staff|admin|superuser|group)_required)\b"
    r"|\.role\b|\brole\s*(==|!=|\bin\b)"
)

_ADDED_RULES = [
    Tag("red", 2, "hace llamadas de red", "añadidas"),
    Tag("escribe en disco", 1, "escribe archivos en disco", "añadidas"),
    Tag("borrado", 3, "borra datos o archivos", "añadidas"),
    Tag("base de datos", 1, "lee o escribe en la base de datos", "añadidas"),
    Tag("ejecuta procesos", 2, "ejecuta otros programas o código dinámico", "añadidas"),
    Tag("secretos", 3, "maneja contraseñas o claves", "añadidas"),
    Tag("desactiva CSRF", 3, "desactiva la protección CSRF", "añadidas"),
    Tag("permisos", 2, "toca controles de acceso", "añadidas"),
]

_PATTERNS = {
    "red": re.compile(
        r"\b(requests|httpx|aiohttp|urllib3?(?!\.parse)|socket|smtplib|ftplib)\.\w+"
        r"|\bimport\s+(requests|httpx|aiohttp|socket|smtplib)\b"
        r"|\bfrom\s+(requests|httpx|aiohttp|socket|urllib\.request)\s+import\b"
        r"|\bfetch\(|XMLHttpRequest|\baxios\b|\bhttp\.client\b|new\s+WebSocket"),
    "escribe en disco": re.compile(
        r"\bopen\([^)]*?,\s*(?:mode\s*=\s*)?['\"][rbt]*[wax+]"
        r"|\.write_(text|bytes)\(|\bshutil\.(copy\w*|move)\(|\b(json|pickle|joblib|yaml)\.dump\("
        r"|\.to_(csv|excel|json|parquet|pickle)\(|\bos\.(makedirs|rename|replace)\(|\.mkdir\("
        r"|writeFile(Sync)?\("),
    "borrado": re.compile(
        r"\bos\.(remove|unlink|rmdir)\(|\.unlink\(|\bshutil\.rmtree\(|\.delete\("
        r"|\bDROP\s+(TABLE|DATABASE)\b|\bDELETE\s+FROM\b|\bTRUNCATE\s+TABLE\b|\bfs\.(rm|rmSync|unlink)"),
    "base de datos": re.compile(
        r"\.objects\.|\.save\(|\bbulk_(create|update)\(|\bmigrations\.\w+\(|\.execute\("
        r"|\btransaction\.atomic\b|\.raw\("),
    "ejecuta procesos": re.compile(
        r"\bsubprocess\b|\bos\.(system|popen|startfile|exec\w*|spawn\w*)\b|\bPopen\("
        r"|child_process|(?<![\w.])eval\(|(?<![\w.])exec\(|ShellExecute"),
    "secretos": re.compile(
        r"(?i)\b\w*(password|passwd|secret|api_?key|access_?token|auth_?token|refresh_?token"
        r"|private_?key|credential)\w*\b\s*(=(?!=)|:)"),
    "desactiva CSRF": re.compile(r"\bcsrf_exempt\b"),
    "permisos": _PERMISSIONS,
}

_REMOVED_PERMISSIONS = Tag("quita permisos", 3, "elimina un control de acceso", "eliminadas")
_DEPENDENCIES = Tag("dependencias", 2, "cambia las dependencias del proyecto", "ruta")
SYNTAX_ERROR = Tag("error de sintaxis", 2, "deja el archivo con un error de sintaxis", "análisis")

_DEPENDENCY_FILES = re.compile(
    r"^(requirements[\w.-]*\.txt|package(-lock)?\.json|pyproject\.toml|Pipfile(\.lock)?"
    r"|setup\.(py|cfg)|poetry\.lock|yarn\.lock|pnpm-lock\.yaml)$", re.IGNORECASE)

_COMMENT_PREFIXES = ("#", "//", "/*", "*", "<!--", "{#")
_PROSE_EXTENSIONS = (".md", ".markdown", ".rst", ".txt")


def _code_lines(lines: list[str]) -> list[str]:
    return [ln for ln in lines if ln.strip() and not ln.strip().startswith(_COMMENT_PREFIXES)]


def moved_lines(added: list[str], removed: list[str]) -> set[str]:
    """Líneas que aparecen añadidas y eliminadas: código movido o reindentado."""
    return {ln.strip() for ln in added} & {ln.strip() for ln in removed}


def detect(path: str, added: list[str], removed: list[str], ignore: set[str] | None = None) -> list[Tag]:
    """Etiquetas de un cambio. `ignore` excluye líneas que solo se movieron."""
    ignore = ignore or set()
    prose = PurePosixPath(path).suffix.lower() in _PROSE_EXTENSIONS
    added_code = [] if prose else [ln for ln in _code_lines(added) if ln.strip() not in ignore]
    removed_code = [] if prose else [ln for ln in _code_lines(removed) if ln.strip() not in ignore]
    found: list[Tag] = []
    for tag in _ADDED_RULES:
        if any(_PATTERNS[tag.nombre].search(ln) for ln in added_code):
            found.append(tag)
    added_perms = sum(1 for ln in added_code if _PERMISSIONS.search(ln))
    removed_perms = sum(1 for ln in removed_code if _PERMISSIONS.search(ln))
    if removed_perms > added_perms:
        found.append(_REMOVED_PERMISSIONS)
    if _DEPENDENCY_FILES.match(PurePosixPath(path).name):
        found.append(_DEPENDENCIES)
    return found
