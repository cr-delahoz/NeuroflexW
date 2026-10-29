"""Genera la página HTML autocontenida con los datos embebidos."""

from __future__ import annotations

import json
from pathlib import Path

TEMPLATE = Path(__file__).parent / "templates" / "report.html"
PLACEHOLDER = "/*__CODEMAP_DATA__*/null"


def render_html(data: dict) -> str:
    # "<" escapado: el código del diff no puede cerrar el <script> que lo contiene.
    payload = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    return TEMPLATE.read_text(encoding="utf-8").replace(PLACEHOLDER, payload, 1)


def write_report(data: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html(data), encoding="utf-8")
    return path
