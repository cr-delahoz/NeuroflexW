import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from _util import TempRepo

from codemap_core.cli import main

HARNESS = Path(__file__).with_name("opencode_harness.mjs")
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "Node.js no está instalado")
class OpencodePluginTests(unittest.TestCase):
    def setUp(self):
        self.repo = TempRepo()
        self.repo.write("app.py", "def uno():\n    return 1\n")
        self.repo.commit()
        self.work = Path(tempfile.mkdtemp(prefix="codemap-oc-"))
        self.plugin = self.work / "codemap.js"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["install-opencode-plugin", "--dest", str(self.plugin)]), 0)

    def tearDown(self):
        self.repo.cleanup()
        shutil.rmtree(self.work, ignore_errors=True)

    def run_steps(self, steps: list[dict]) -> list[dict]:
        steps_file = self.work / "steps.json"
        steps_file.write_text(json.dumps(steps), encoding="utf-8")
        env = {**os.environ, "CODEMAP_STORE": str(self.work / "store")}
        proc = subprocess.run([NODE, str(HARNESS), str(self.plugin), str(self.repo.root), str(steps_file)],
                              capture_output=True, text=True, encoding="utf-8", env=env, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_install_fills_paths(self):
        text = self.plugin.read_text(encoding="utf-8")
        self.assertNotIn("{{", text)
        self.assertIn("codemap.py", text)

    def test_nudges_once_for_changes_made_in_the_session(self):
        prompts = self.run_steps([
            {"op": "message", "session": "root"},
            {"op": "write", "path": "app.py", "text": "def uno():\n    return 10\n"},
            {"op": "idle", "session": "child"},   # los subagentes no reciben avisos
            {"op": "idle", "session": "root"},
            {"op": "idle", "session": "root"},    # mismo conjunto: no repite
        ])
        self.assertEqual(len(prompts), 1)
        self.assertEqual(prompts[0]["session"], "root")
        self.assertIn("app.py::uno", prompts[0]["text"])
        self.assertIn("codemap-annotate", prompts[0]["text"])

    def test_annotated_changes_stop_the_nudges(self):
        prompts = self.run_steps([
            {"op": "message", "session": "root"},
            {"op": "write", "path": "app.py", "text": "def uno():\n    return 10\n"},
            {"op": "annotate", "json": {"tarea": "t", "cambios": {"app.py::uno": "devuelve diez"}}},
            {"op": "idle", "session": "root"},
        ])
        self.assertEqual(prompts, [])

    def test_preexisting_changes_are_not_claimed(self):
        self.repo.write("app.py", "def uno():\n    return 5\n")  # cambio previo a la sesión
        prompts = self.run_steps([
            {"op": "message", "session": "root"},
            {"op": "idle", "session": "root"},
            {"op": "write", "path": "nuevo.py", "text": "def dos():\n    return 2\n"},
            {"op": "idle", "session": "root"},
        ])
        self.assertEqual(len(prompts), 1)
        self.assertIn("nuevo.py::*", prompts[0]["text"])
        self.assertNotIn("app.py::uno", prompts[0]["text"])

    def test_at_most_two_nudges_per_session(self):
        steps = [{"op": "message", "session": "root"}]
        for n in range(4):
            steps += [{"op": "write", "path": f"f{n}.py", "text": f"x = {n}\n"}, {"op": "idle", "session": "root"}]
        self.assertEqual(len(self.run_steps(steps)), 2)

    def test_outside_a_git_repo_does_nothing(self):
        # En Windows git deja archivos de solo lectura: se les quita el atributo para borrarlos.
        shutil.rmtree(self.repo.root / ".git", onexc=lambda fn, path, _: (os.chmod(path, 0o700), fn(path)))
        prompts = self.run_steps([
            {"op": "message", "session": "root"},
            {"op": "write", "path": "app.py", "text": "x = 1\n"},
            {"op": "idle", "session": "root"},
        ])
        self.assertEqual(prompts, [])


if __name__ == "__main__":
    unittest.main()
