"""Servidor local: cada recarga de la página vuelve a analizar el repositorio."""

from __future__ import annotations

import html
import json
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from .render import render_html


def serve(build: Callable[[], dict], host: str = "127.0.0.1", port: int = 8765,
          open_browser: bool = False) -> None:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: str, content_type: str) -> None:
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path not in ("/", "/index.html", "/api/cambios"):
                self._send(404, "No encontrado", "text/plain")
                return
            try:
                data = build()
            except Exception:  # se muestra en la página en lugar de cortar el servidor
                detail = html.escape(traceback.format_exc())
                self._send(500, f"<h1>Error al analizar</h1><pre>{detail}</pre>", "text/html")
                return
            if path == "/api/cambios":
                self._send(200, json.dumps(data, ensure_ascii=False), "application/json")
            else:
                self._send(200, render_html(data), "text/html")

        def log_message(self, format: str, *args) -> None:  # noqa: A002
            pass

    try:
        server = ThreadingHTTPServer((host, port), Handler)
    except OSError as exc:
        raise SystemExit(f"No se pudo usar el puerto {port} ({exc}). Prueba con --port <otro>.")
    url = f"http://{host}:{port}/"
    print(f"Codemap en {url}  (recarga la página para ver cambios nuevos; Ctrl+C para salir)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
