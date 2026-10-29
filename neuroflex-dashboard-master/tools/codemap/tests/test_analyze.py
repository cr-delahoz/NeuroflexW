import json
import unittest

from _util import TempRepo

from codemap_core.analyze import analyze
from codemap_core.cli import format_terminal
from codemap_core.render import render_html

CONFIG = {
    "excluir": [],
    "secciones": [
        {"nombre": "Backend", "rutas": ["**/views.py"]},
        {"nombre": "UI", "rutas": ["**/*.html"]},
        {"nombre": "Herramientas", "rutas": ["tools/**"]},
    ],
}

VIEWS_BASE = '''\
import os


@login_required
def listado(request):
    return render(request, "a.html")


def borrar_me():
    return 1


def calcular(a, b):
    total = a + b
    return total
'''

VIEWS_NEW = '''\
import os
import requests


def listado(request):
    return render(request, "a.html")


def calcular(a, b, c=0):
    total = a + b + c
    requests.post("https://example.com", json={"t": total})
    return total


def nueva():
    return 2
'''

TOOL = "".join(f"def paso_{i}():\n    return {i}\n\n" for i in range(30))


class AnalyzeTests(unittest.TestCase):
    def setUp(self):
        self.repo = TempRepo()
        self.repo.write("app/views.py", VIEWS_BASE)
        self.repo.write("tools/sim.py", TOOL)
        self.repo.write("app/page.html", "{% block content %}\n<p>hola</p>\n{% endblock %}\n")
        self.repo.commit()
        # El archivo de configuración vive fuera del árbol analizado.
        self.config = self.repo.root.parent / f"{self.repo.root.name}-config.json"
        self.config.write_text(json.dumps(CONFIG), encoding="utf-8")

    def tearDown(self):
        self.repo.cleanup()
        self.config.unlink(missing_ok=True)

    def run_analysis(self, **kwargs):
        return analyze(self.repo.root, config_path=self.config, **kwargs)

    def by_id(self, changeset):
        return {c.id: c for c in changeset.cambios}

    def test_symbol_level_changes(self):
        self.repo.write("app/views.py", VIEWS_NEW)
        changes = self.by_id(self.run_analysis())

        self.assertEqual(changes["app/views.py::nueva"].tipo_cambio, "añadido")
        self.assertEqual(changes["app/views.py::borrar_me"].tipo_cambio, "eliminado")

        calcular = changes["app/views.py::calcular"]
        self.assertEqual(calcular.tipo_cambio, "modificado")
        self.assertIn("red", calcular.etiquetas)
        self.assertIn("firma", calcular.detalles)
        self.assertIn("cambian sus parámetros", calcular.resumen)
        self.assertTrue(all(e.lado == "nuevo" for e in calcular.evidencia))

        listado = changes["app/views.py::listado"]
        self.assertIn("quita permisos", listado.etiquetas)
        self.assertEqual(listado.riesgo, 3)
        self.assertIn("se le quitó el decorador `@login_required`", listado.resumen)

        imports = changes["app/views.py::*"]
        self.assertTrue(imports.detalles["solo_importaciones"])
        self.assertEqual(imports.detalles["importaciones"]["añadidas"], ["requests"])

        self.assertTrue(all(c.seccion == "Backend" for c in changes.values()))

    def test_renamed_function_is_one_change(self):
        body = "    a = 1\n    b = 2\n    c = a + b\n    return c\n"
        self.repo.write("app/views.py", "def viejo():\n" + body)
        self.repo.commit("renombrar")
        self.repo.write("app/views.py", "def nuevo():\n" + body)
        changes = self.run_analysis().cambios
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].detalles["renombrado_desde"], "viejo")
        self.assertIn("Se renombró la función `viejo()` a `nuevo()`", changes[0].resumen)

    def test_untracked_move_is_detected(self):
        self.repo.remove("tools/sim.py")
        self.repo.write("tools/sim/sim.py", TOOL)
        changes = self.run_analysis().cambios
        self.assertEqual(len(changes), 1)
        moved = changes[0]
        self.assertEqual((moved.tipo_cambio, moved.archivo, moved.archivo_anterior),
                         ("movido", "tools/sim/sim.py", "tools/sim.py"))
        self.assertIn("sin cambios", moved.resumen)

    def test_template_changes_are_grouped_per_file(self):
        self.repo.write("app/page.html",
                        "{% block title %}T{% endblock %}\n{% block content %}\n<p>adiós</p>\n{% endblock %}\n")
        changes = self.run_analysis().cambios
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].detalles["partes"]["añadidas"], ["title"])
        self.assertEqual(changes[0].detalles["partes"]["modificadas"], ["content"])

    def test_syntax_error_is_flagged(self):
        self.repo.write("app/views.py", VIEWS_BASE + "\ndef rota(:\n    pass\n")
        changes = self.run_analysis().cambios
        self.assertEqual(len(changes), 1)
        self.assertIn("error de sintaxis", changes[0].etiquetas)

    def test_staged_mode_ignores_untracked_and_unstaged(self):
        self.repo.write("nuevo.py", "x = 1\n")
        self.repo.write("app/views.py", VIEWS_NEW)
        self.assertEqual(self.run_analysis(staged=True).cambios, [])
        self.repo.git("add", "app/views.py")
        self.assertTrue(self.run_analysis(staged=True).cambios)

    def test_repo_without_commits(self):
        empty = TempRepo()
        try:
            empty.write("a.py", "def f():\n    return 1\n")
            result = analyze(empty.root, config_path=self.config)
            self.assertEqual(result.base, "(repositorio sin commits)")
            self.assertEqual(result.cambios[0].tipo_cambio, "añadido")
        finally:
            empty.cleanup()

    def test_outputs_render(self):
        self.repo.write("app/views.py", VIEWS_NEW.replace("return 2", 'return "</script><b>"'))
        data = self.run_analysis().to_dict()
        html = render_html(data)
        self.assertNotIn("/*__CODEMAP_DATA__*/", html)
        self.assertEqual(html.count("</script>"), 2)  # solo los dos cierres reales
        self.assertIn("■ Backend", format_terminal(data, color=False))
        json.dumps(data)  # serializable


if __name__ == "__main__":
    unittest.main()
