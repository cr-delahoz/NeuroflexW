"""Estructuras de datos de Codemap.

El modelo es la frontera estable entre el análisis (git + parser) y la
presentación (terminal, HTML y, en fases futuras, LLM / MCP). Los resúmenes se
derivan siempre de estos campos: un texto nunca afirma algo que no esté aquí.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

ADDED = "añadido"
MODIFIED = "modificado"
DELETED = "eliminado"
MOVED = "movido"


@dataclass
class Evidence:
    """Rango de líneas que respalda un cambio."""

    archivo: str
    linea_inicio: int
    linea_fin: int
    lado: str = "nuevo"  # "nuevo" = archivo actual, "viejo" = versión base


@dataclass
class Change:
    """Un cambio revisable: un símbolo (función, clase…) o un archivo."""

    id: str
    seccion: str
    archivo: str
    tipo_cambio: str
    simbolo: str | None
    tipo_simbolo: str
    resumen: str = ""
    resumen_tecnico: str = ""
    resumen_origen: str = "regla"  # "regla" hoy; "llm" en la fase 3
    etiquetas: list[str] = field(default_factory=list)
    riesgo: int = 0
    lineas: dict = field(default_factory=lambda: {"añadidas": 0, "eliminadas": 0})
    evidencia: list[Evidence] = field(default_factory=list)
    diff: list[dict] = field(default_factory=list)
    archivo_anterior: str | None = None
    detalles: dict = field(default_factory=dict)
    huella: str = ""  # hash de las líneas cambiadas: liga una anotación a un contenido concreto
    resumen_ia: str | None = None
    estado_anotacion: str | None = None  # anotado | no_declarado | desactualizado (None = sin anotaciones)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ChangeSet:
    repo: str
    base: str
    base_commit: str
    modo: str
    generado: str
    secciones: list[dict]
    cambios: list[Change]
    tarea: str | None = None
    autor_anotaciones: str | None = None
    declaraciones_sin_respaldo: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "version": 1,
            "repo": self.repo,
            "base": self.base,
            "base_commit": self.base_commit,
            "modo": self.modo,
            "generado": self.generado,
            "totales": {
                "cambios": len(self.cambios),
                "archivos": len({c.archivo for c in self.cambios}),
                "añadidas": sum(c.lineas["añadidas"] for c in self.cambios),
                "eliminadas": sum(c.lineas["eliminadas"] for c in self.cambios),
                "riesgo_alto": sum(1 for c in self.cambios if c.riesgo >= 3),
                "no_declarados": sum(1 for c in self.cambios if c.estado_anotacion == "no_declarado"),
                "desactualizados": sum(1 for c in self.cambios if c.estado_anotacion == "desactualizado"),
            },
            "tarea": self.tarea,
            "autor_anotaciones": self.autor_anotaciones,
            "declaraciones_sin_respaldo": self.declaraciones_sin_respaldo,
            "secciones": self.secciones,
            "cambios": [c.to_dict() for c in self.cambios],
        }
