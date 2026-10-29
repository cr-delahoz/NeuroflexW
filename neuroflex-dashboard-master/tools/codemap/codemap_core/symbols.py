"""Extracción de símbolos (funciones, clases, bloques…) con sus rangos de líneas.

Python usa `ast` (exacto). HTML de Django, JavaScript y Markdown usan
heurísticas por regex. Para cualquier otro tipo de archivo se devuelve None y
el cambio se trata a nivel de archivo.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

FUNCTION = "función"
METHOD = "método"
CLASS = "clase"
BLOCK = "bloque"
HEADING = "apartado"


@dataclass
class Symbol:
    name: str  # nombre calificado, p. ej. "Clase.metodo"
    kind: str
    start: int
    end: int
    signature: str = ""
    decorators: list[str] = field(default_factory=list)

    @property
    def span(self) -> int:
        return self.end - self.start


class ParseFailure(Exception):
    """El archivo es de un lenguaje soportado pero no se pudo analizar."""


def extract(path: str, text: str) -> list[Symbol] | None:
    """Símbolos de `text`; None si el tipo de archivo no está soportado.

    Lanza ParseFailure si es Python con errores de sintaxis.
    """
    ext = PurePosixPath(path).suffix.lower()
    if ext in (".py", ".pyw"):
        return _python(text)
    if ext in (".html", ".htm", ".jinja", ".j2"):
        return _django_blocks(text)
    if ext in (".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx"):
        return _javascript(text)
    if ext in (".md", ".markdown"):
        return _markdown(text)
    return None


def innermost(symbols: list[Symbol] | None, line: int | None) -> Symbol | None:
    if not symbols or line is None:
        return None
    best = None
    for sym in symbols:
        if sym.start <= line <= sym.end and (best is None or sym.span <= best.span):
            best = sym
    return best


# --- Python -----------------------------------------------------------------

def _python(text: str) -> list[Symbol]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError) as exc:
        raise ParseFailure(str(exc)) from exc
    lines = text.splitlines()
    out: list[Symbol] = []

    def signature(node: ast.AST) -> str:
        parts = []
        for i in range(node.lineno - 1, min(node.lineno + 9, len(lines))):
            parts.append(lines[i].strip())
            if lines[i].rstrip().endswith(":"):
                break
        return re.sub(r"\s+", " ", " ".join(parts)).rstrip(":").strip()

    def visit(body: list[ast.stmt], prefix: str, in_class: bool) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                is_class = isinstance(node, ast.ClassDef)
                kind = CLASS if is_class else (METHOD if in_class else FUNCTION)
                start = min([node.lineno] + [d.lineno for d in node.decorator_list])
                out.append(Symbol(
                    prefix + node.name, kind, start, node.end_lineno or node.lineno,
                    signature(node), [ast.unparse(d) for d in node.decorator_list],
                ))
                if is_class:
                    visit(node.body, f"{prefix}{node.name}.", True)
                # Las funciones anidadas pertenecen a su función contenedora.
            elif isinstance(node, (ast.If, ast.Try, ast.With, ast.AsyncWith)):
                for attr in ("body", "orelse", "finalbody"):
                    visit(getattr(node, attr, []), prefix, in_class)
                for handler in getattr(node, "handlers", []):
                    visit(handler.body, prefix, in_class)

    visit(tree.body, "", False)
    return out


# --- HTML / plantillas Django ------------------------------------------------

_BLOCK_RE = re.compile(r"{%-?\s*(block|endblock)\b\s*([\w.-]+)?")


def _django_blocks(text: str) -> list[Symbol]:
    lines = text.splitlines()
    stack: list[tuple[str, int]] = []
    out: list[Symbol] = []
    for no, line in enumerate(lines, 1):
        for match in _BLOCK_RE.finditer(line):
            if match.group(1) == "block":
                stack.append((match.group(2) or "?", no))
            elif stack:
                name, start = stack.pop()
                out.append(Symbol(name, BLOCK, start, no))
    for name, start in stack:
        out.append(Symbol(name, BLOCK, start, len(lines)))
    return out


# --- JavaScript --------------------------------------------------------------

_JS_PATTERNS = [
    (FUNCTION, re.compile(
        r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)\s*\(")),
    (FUNCTION, re.compile(
        r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s+)?"
        r"(?:function\b|\([^)]*\)\s*=>|[A-Za-z_$][\w$]*\s*=>)")),
    (CLASS, re.compile(r"^\s*(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_$][\w$]*)")),
]
_JS_NOISE = re.compile(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`|//.*$")


def _block_end(lines: list[str], start: int) -> int:
    """Línea donde cierra la llave abierta en `start` (1-based)."""
    depth, opened = 0, False
    for i in range(start - 1, len(lines)):
        clean = _JS_NOISE.sub("", lines[i])
        for ch in clean:
            if ch == "{":
                depth += 1
                opened = True
            elif ch == "}":
                depth -= 1
        if opened and depth <= 0:
            return i + 1
        if not opened and i - (start - 1) >= 2:
            return start
    return len(lines)


def _javascript(text: str) -> list[Symbol]:
    lines = text.splitlines()
    out: list[Symbol] = []
    for no, line in enumerate(lines, 1):
        for kind, pattern in _JS_PATTERNS:
            match = pattern.match(line)
            if match:
                out.append(Symbol(match.group(1), kind, no, _block_end(lines, no), line.strip().rstrip("{").strip()))
                break
    return out


# --- Markdown ---------------------------------------------------------------

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


def _markdown(text: str) -> list[Symbol]:
    lines = text.splitlines()
    heads: list[tuple[int, str]] = []
    fenced = False
    for no, line in enumerate(lines, 1):
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            continue
        match = None if fenced else _HEADING_RE.match(line)
        if match:
            heads.append((no, match.group(2)))
    out = []
    for i, (no, title) in enumerate(heads):
        end = heads[i + 1][0] - 1 if i + 1 < len(heads) else len(lines)
        out.append(Symbol(title, HEADING, no, end))
    return out
