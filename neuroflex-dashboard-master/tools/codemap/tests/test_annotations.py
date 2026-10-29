import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from _util import TempRepo

from codemap_core import annotations
from codemap_core.analyze import analyze
from codemap_core.cli import compact, main

CONFIG = {"excluir": [], "secciones": [{"nombre": "Backend", "rutas": ["**/*.py"]}]}
BASE = "def uno():\n    return 1\n\n\ndef dos():\n    return 2\n"
NEW = "def uno():\n    return 10\n\n\ndef dos():\n    return 20\n"


class AnnotationTests(unittest.TestCase):
    def setUp(self):
        self.repo = TempRepo()
        self.repo.write("app.py", BASE)
        self.repo.commit()
        self.repo.write("app.py", NEW)
        self.work = Path(tempfile.mkdtemp(prefix="codemap-ann-"))
        self.config = self.work / "config.json"
        self.config.write_text(json.dumps(CONFIG), encoding="utf-8")
        self.store = self.work / "store"

    def tearDown(self):
        self.repo.cleanup()
        shutil.rmtree(self.work, ignore_errors=True)

    def cli(self, *args: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = main([*args[:1], "--repo", str(self.repo.root), "--config", str(self.config),
                         "--store", str(self.store), *args[1:]])
        return code, out.getvalue()

    def annotate(self, payload: dict) -> tuple[int, str]:
        path = self.work / "ann.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return self.cli("annotate", str(path))

    def state(self) -> dict:
        changeset = analyze(self.repo.root, config_path=self.config)
        store = annotations.load(changeset.base_commit, self.store)
        return annotations.apply(changeset, store).to_dict()

    def test_without_annotations_nothing_is_flagged(self):
        data = self.state()
        self.assertTrue(all(c["estado_anotacion"] is None for c in data["cambios"]))
        self.assertEqual(data["totales"]["no_declarados"], 0)

    def test_complete_annotation(self):
        code, out = self.annotate({"tarea": "Multiplicar por diez", "cambios": {
            "app.py::uno": "uno devuelve diez", "app.py::dos": "dos devuelve veinte"}})
        self.assertEqual(code, 0, out)
        data = self.state()
        self.assertEqual({c["estado_anotacion"] for c in data["cambios"]}, {"anotado"})
        self.assertEqual(data["tarea"], "Multiplicar por diez")
        self.assertEqual(next(c for c in data["cambios"] if c["id"] == "app.py::uno")["resumen_ia"],
                         "uno devuelve diez")

    def test_missing_and_unknown_ids(self):
        code, out = self.annotate({"tarea": "t", "cambios": {"app.py::uno": "x", "app.py::fantasma": "y"}})
        self.assertEqual(code, 1)
        self.assertIn("app.py::fantasma", out)
        self.assertIn("app.py::dos", out)
        data = self.state()
        states = {c["id"]: c["estado_anotacion"] for c in data["cambios"]}
        self.assertEqual(states, {"app.py::uno": "anotado", "app.py::dos": "no_declarado"})
        self.assertEqual([d["id"] for d in data["declaraciones_sin_respaldo"]], ["app.py::fantasma"])

    def test_annotations_merge_across_calls(self):
        self.annotate({"tarea": "t", "cambios": {"app.py::uno": "x"}})
        code, _ = self.annotate({"cambios": {"app.py::dos": "y"}})
        self.assertEqual(code, 0)
        self.assertEqual(self.state()["tarea"], "t")

    def test_editing_code_after_annotating_marks_stale(self):
        self.annotate({"tarea": "t", "cambios": {"app.py::uno": "x", "app.py::dos": "y"}})
        self.repo.write("app.py", NEW.replace("return 20", "return 99"))
        states = {c["id"]: c["estado_anotacion"] for c in self.state()["cambios"]}
        self.assertEqual(states, {"app.py::uno": "anotado", "app.py::dos": "desactualizado"})

    def test_annotations_belong_to_their_base_commit(self):
        self.annotate({"tarea": "t", "cambios": {"app.py::uno": "x", "app.py::dos": "y"}})
        self.repo.commit("otra base")
        self.repo.write("app.py", NEW + "\n\ndef tres():\n    return 3\n")
        data = self.state()
        self.assertIsNone(data["tarea"])
        self.assertTrue(all(c["estado_anotacion"] is None for c in data["cambios"]))

    def test_invalid_input(self):
        code, out = self.annotate({"cambios": {"app.py::uno": ""}})
        self.assertEqual(code, 2)
        self.assertIn("vacío", out)
        self.assertEqual(annotations.parse_input('{"cambios": [{"id": "a", "resumen": "b"}]}')["cambios"], {"a": "b"})

    def test_inline_options_without_a_file(self):
        code, out = self.cli("annotate", "--tarea", "Multiplicar por diez", "--autor", "opencode",
                             "--cambio", "app.py::uno", "uno devuelve diez",
                             "--cambio", "app.py::dos", "dos devuelve `veinte`")
        self.assertEqual(code, 0, out)
        data = self.state()
        self.assertEqual(data["autor_anotaciones"], "opencode")
        self.assertEqual({c["estado_anotacion"] for c in data["cambios"]}, {"anotado"})
        self.assertEqual(next(c for c in data["cambios"] if c["id"] == "app.py::dos")["resumen_ia"],
                         "dos devuelve `veinte`")

    def test_file_and_inline_options_are_exclusive(self):
        path = self.work / "ann.json"
        path.write_text("{}", encoding="utf-8")
        code, _ = self.cli("annotate", str(path), "--tarea", "t")
        self.assertEqual(code, 2)
        code, out = self.cli("annotate")
        self.assertEqual(code, 2)
        self.assertIn("--cambio", out)

    def test_missing_task_is_reported(self):
        code, out = self.annotate({"cambios": {"app.py::uno": "x", "app.py::dos": "y"}})
        self.assertEqual(code, 1)
        self.assertIn("Falta 'tarea'", out)

    def test_clear(self):
        self.annotate({"tarea": "t", "cambios": {"app.py::uno": "x"}})
        code, _ = self.cli("annotate", "--clear")
        self.assertEqual(code, 0)
        self.assertIsNone(self.state()["tarea"])

    def test_compact_json_for_agents(self):
        code, out = self.cli("scan", "--json", "-", "--compact")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertNotIn("diff", data["cambios"][0])
        self.assertIn("huella", data["cambios"][0])
        self.assertEqual(compact(data)["cambios"][0]["id"], data["cambios"][0]["id"])

    def test_install_skill(self):
        dest = self.work / "skills" / "codemap-annotate"
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            self.assertEqual(main(["install-skill", "--dest", str(dest)]), 0)
            self.assertEqual(main(["install-skill", "--dest", str(dest)]), 1)  # no sobrescribe
        text = (dest / "SKILL.md").read_text(encoding="utf-8")
        self.assertNotIn("{{CODEMAP}}", text)
        self.assertIn("codemap.py", text)
        self.assertTrue(text.startswith("---\nname: codemap-annotate"))


if __name__ == "__main__":
    unittest.main()
