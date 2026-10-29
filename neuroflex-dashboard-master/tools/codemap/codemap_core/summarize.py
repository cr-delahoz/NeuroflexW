"""Resúmenes en lenguaje natural generados con plantillas deterministas.

Cada frase se construye solo con datos del modelo (símbolo, tipo de cambio,
conteos, etiquetas, detalles). En la fase 3 un LLM podrá reformular estos
mismos datos; `resumen_origen` indica de dónde viene el texto.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from .model import ADDED, DELETED, MODIFIED, MOVED, Change
from .symbols import BLOCK, CLASS, FUNCTION, HEADING, METHOD
from .tags import Tag

_ARTICLE = {FUNCTION: "la función", METHOD: "el método", CLASS: "la clase", BLOCK: "el bloque"}
_PLURAL = {FUNCTION: "funciones", METHOD: "métodos", CLASS: "clases", BLOCK: "bloques", HEADING: "apartados"}
_SINGULAR = {FUNCTION: "función", METHOD: "método", CLASS: "clase", BLOCK: "bloque", HEADING: "apartado"}
_MAX_NAMES = 4


def _join(items: list[str]) -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " y " + items[-1]


def _name(kind: str, name: str) -> str:
    if kind in (FUNCTION, METHOD):
        return f"`{name}()`"
    if kind == HEADING:
        return f"«{name}»"
    return f"`{name}`"


def _ref(kind: str, name: str) -> str:
    if kind == HEADING:
        return f"el apartado {_name(kind, name)}"
    return f"{_ARTICLE.get(kind, '')} {_name(kind, name)}".strip()


def _counts(change: Change) -> str:
    return f"+{change.lineas['añadidas']} / −{change.lineas['eliminadas']} líneas"


def _phrases(tags: list[Tag]) -> tuple[list[str], list[str]]:
    new = [t.frase for t in tags if t.origen in ("añadidas", "ruta")]
    lost = [t.frase for t in tags if t.origen in ("eliminadas", "análisis")]
    return new, lost


def _describe_symbols(symbols: list[list[str]]) -> str:
    counts: dict[str, int] = {}
    for kind, _ in symbols:
        counts[kind] = counts.get(kind, 0) + 1
    parts = [f"{n} {_SINGULAR[k] if n == 1 else _PLURAL[k]}" for k, n in counts.items()]
    names = [_name(k, n) for k, n in symbols[:_MAX_NAMES]]
    more = "…" if len(symbols) > _MAX_NAMES else ""
    return f"{_join(parts)}: {', '.join(names)}{more}"


def _parts(parts: dict | None) -> list[str]:
    """'nuevos bloques `a` y `b`', 'se quitó el bloque `c`', 'cambia el apartado «d»'."""
    if not parts or not parts.get("tipo"):
        return []
    kind = parts["tipo"]
    one, many = _SINGULAR[kind], _PLURAL[kind]

    def names(items: list[str]) -> str:
        return _join([_name(kind, n) for n in items])

    out = []
    if added := parts["añadidas"]:
        out.append(f"nuevo {one} {names(added)}" if len(added) == 1 else f"nuevos {many} {names(added)}")
    if gone := parts["eliminadas"]:
        out.append(f"se quitó el {one} {names(gone)}" if len(gone) == 1
                   else f"se quitaron los {many} {names(gone)}")
    if changed := parts["modificadas"]:
        out.append(f"cambia el {one} {names(changed)}" if len(changed) == 1
                   else f"cambian los {many} {names(changed)}")
    return out


def _sentence(base: str, extras: list[str]) -> str:
    return f"{base}: {'; '.join(extras)}." if extras else f"{base}."


def simple(change: Change, tags: list[Tag]) -> str:
    d = change.detalles
    new, lost = _phrases(tags)
    file_name = PurePosixPath(change.archivo).name

    if d.get("binario"):
        if change.tipo_cambio == MOVED:
            return f"`{change.archivo_anterior}` se movió a `{change.archivo}` (archivo binario)."
        verb = {ADDED: "añadió", DELETED: "eliminó"}.get(change.tipo_cambio, "modificó")
        return f"Se {verb} el archivo binario `{file_name}`."

    if change.tipo_cambio == MOVED:
        if not change.lineas["añadidas"] and not change.lineas["eliminadas"]:
            return f"`{change.archivo_anterior}` se movió a `{change.archivo}` sin cambios."
        base = (f"`{change.archivo_anterior}` se movió a `{change.archivo}` con cambios "
                f"({d.get('similitud', 0)} % igual, {_counts(change)})")
        return _sentence(base, lost + ([f"el código nuevo {_join(new)}"] if new else []))

    if change.tipo_simbolo == "archivo" and change.tipo_cambio in (ADDED, DELETED):
        lines = d.get("total_lineas", 0)
        symbols = d.get("simbolos") or []
        if change.tipo_cambio == ADDED:
            text = f"Nuevo archivo `{file_name}` ({lines} líneas)"
            text += f" con {_describe_symbols(symbols)}." if symbols else "."
            if new:
                text += f" Su código {_join(new)}."
        else:
            text = f"Se eliminó el archivo `{file_name}` ({lines} líneas)"
            text += f", que tenía {_describe_symbols(symbols)}." if symbols else "."
        if lost:
            text += f" Atención: {_join(lost)}."
        return text

    if change.simbolo is None:
        imports = d.get("importaciones")
        if d.get("solo_importaciones") and imports:
            parts = []
            if imports["añadidas"]:
                parts.append("nuevas: " + ", ".join(f"`{m}`" for m in imports["añadidas"]))
            if imports["quitadas"]:
                parts.append("quitadas: " + ", ".join(f"`{m}`" for m in imports["quitadas"]))
            suffix = f" ({'; '.join(parts)})" if parts else ""
            return _sentence(f"Se cambiaron las importaciones de `{file_name}`{suffix}", new + lost)
        if change.tipo_simbolo == "módulo":
            base = f"Cambios en `{file_name}` fuera de funciones y clases ({_counts(change)})"
        else:
            base = f"Se modificó `{file_name}` ({_counts(change)})"
        return _sentence(base, _parts(d.get("partes")) + lost
                         + ([f"el código nuevo {_join(new)}"] if new else []))

    ref = _ref(change.tipo_simbolo, change.simbolo)
    if change.tipo_cambio == ADDED:
        text = f"Se añadió {ref}"
        text += f", que {_join(new)}." if new else "."
        if lost:
            text += f" Atención: {_join(lost)}."
        return text
    if change.tipo_cambio == DELETED:
        return _sentence(f"Se eliminó {ref}", lost)

    extras: list[str] = []
    if "firma" in d:
        extras.append("cambian sus parámetros" if change.tipo_simbolo in (FUNCTION, METHOD)
                      else "cambia su declaración")
    decorators = d.get("decoradores", {})
    for deco in decorators.get("quitados", []):
        extras.append(f"se le quitó el decorador `@{deco}`")
    for deco in decorators.get("añadidos", []):
        extras.append(f"se le añadió el decorador `@{deco}`")
    extras += lost
    if new:
        extras.append(f"ahora también {_join(new)}")
    if "renombrado_desde" in d:
        old_ref = _ref(change.tipo_simbolo, d["renombrado_desde"])
        base = f"Se renombró {old_ref} a {_name(change.tipo_simbolo, change.simbolo)} ({_counts(change)})"
    else:
        base = f"Se modificó {ref} ({_counts(change)})"
    return _sentence(base, extras)


def technical(change: Change) -> str:
    d = change.detalles
    target = change.simbolo or change.archivo
    parts = [f"[{change.tipo_cambio.upper()}] {change.tipo_simbolo} {target}"]
    if change.evidencia:
        first, last = change.evidencia[0], change.evidencia[-1]
        side = " (versión base)" if first.lado == "viejo" else ""
        parts.append(f"{change.archivo}:{first.linea_inicio}-{last.linea_fin}{side}")
    else:
        parts.append(change.archivo)
    parts.append(f"+{change.lineas['añadidas']}/−{change.lineas['eliminadas']}")
    if change.archivo_anterior:
        parts.append(f"desde {change.archivo_anterior}")
    if "similitud" in d and d["similitud"] is not None:
        parts.append(f"similitud {d['similitud']} %")
    if "renombrado_desde" in d:
        parts.append(f"antes: {d['renombrado_desde']}")
    if "firma" in d:
        parts.append(f"firma: `{d['firma']['antes']}` → `{d['firma']['despues']}`")
    decorators = d.get("decoradores", {})
    if decorators:
        deco = [f"+@{x}" for x in decorators.get("añadidos", [])] + [f"−@{x}" for x in decorators.get("quitados", [])]
        parts.append("decoradores " + " ".join(deco))
    imports = d.get("importaciones")
    if imports and (imports["añadidas"] or imports["quitadas"]):
        imp = [f"+{x}" for x in imports["añadidas"]] + [f"−{x}" for x in imports["quitadas"]]
        parts.append("imports " + " ".join(imp))
    parts_detail = d.get("partes")
    if parts_detail and parts_detail.get("tipo"):
        marks = ([f"+{x}" for x in parts_detail["añadidas"]] + [f"−{x}" for x in parts_detail["eliminadas"]]
                 + [f"~{x}" for x in parts_detail["modificadas"]])
        parts.append(f"{_PLURAL[parts_detail['tipo']]} " + " ".join(marks))
    if d.get("error_sintaxis"):
        parts.append(f"SyntaxError: {d['error_sintaxis']}")
    if change.etiquetas:
        parts.append("etiquetas: " + ", ".join(change.etiquetas))
    return " · ".join(parts)


def fill(change: Change, tags: list[Tag]) -> Change:
    change.etiquetas = [t.nombre for t in tags]
    change.riesgo = max([t.riesgo for t in tags] + [change.riesgo])
    change.resumen = simple(change, tags)
    change.resumen_tecnico = technical(change)
    change.resumen_origen = "regla"
    return change
