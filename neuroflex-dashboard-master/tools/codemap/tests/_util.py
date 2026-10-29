"""Utilidades de tests: ruta del paquete y repos git temporales."""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class TempRepo:
    """Repositorio git desechable para probar el análisis de punta a punta."""

    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="codemap-test-"))
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "Codemap Test")
        self.git("config", "core.autocrlf", "false")

    def git(self, *args: str) -> str:
        proc = subprocess.run(["git", *args], cwd=self.root, capture_output=True, text=True, check=True)
        return proc.stdout

    def write(self, path: str, text: str) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")

    def remove(self, path: str) -> None:
        (self.root / path).unlink()

    def commit(self, message: str = "base") -> None:
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
