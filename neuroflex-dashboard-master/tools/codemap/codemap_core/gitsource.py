"""Acceso a git: raíz del repo, diff contra una base y contenidos de archivos."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Hash del árbol vacío de git: sirve como base en repos sin commits.
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
BINARY_SNIFF = 8000


class GitError(RuntimeError):
    pass


def _run(args: list[str], cwd: Path | str) -> subprocess.CompletedProcess:
    cmd = ["git", "-c", "core.quotepath=off", *args]
    extra = {}
    if sys.platform == "win32":
        extra["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, **extra)
    except FileNotFoundError as exc:
        raise GitError("No se encontró git en el PATH.") from exc


def _git(args: list[str], cwd: Path | str) -> bytes:
    proc = _run(args, cwd)
    if proc.returncode != 0:
        message = proc.stderr.decode("utf-8", "replace").strip()
        raise GitError(message or f"git {' '.join(args)} falló")
    return proc.stdout


def decode(data: bytes) -> str:
    text = data.decode("utf-8", "replace")
    return text[1:] if text.startswith("﻿") else text


def to_text(data: bytes | None) -> str | None:
    """Texto del archivo, o None si es binario o no existe."""
    if data is None or b"\0" in data[:BINARY_SNIFF]:
        return None
    return decode(data)


def repo_root(start: Path | str) -> Path:
    out = _git(["rev-parse", "--show-toplevel"], start)
    return Path(decode(out).strip())


def resolve_base(root: Path, base: str) -> tuple[str, str]:
    """Devuelve (referencia para diff, commit corto) de la base indicada."""
    proc = _run(["rev-parse", "--verify", "--quiet", f"{base}^{{commit}}"], root)
    if proc.returncode == 0:
        sha = decode(proc.stdout).strip()
        return sha, sha[:7]
    if base == "HEAD":
        return EMPTY_TREE, ""
    raise GitError(f"No existe la referencia '{base}' en este repositorio.")


def diff(root: Path, base_ref: str, staged: bool) -> str:
    args = [
        "diff", "--no-color", "--no-ext-diff", "--no-textconv", "-M", "-U3",
        "--src-prefix=a/", "--dst-prefix=b/",
    ]
    if staged:
        args.append("--cached")
    args += [base_ref, "--"]
    return decode(_git(args, root))


def untracked(root: Path) -> list[str]:
    out = decode(_git(["ls-files", "--others", "--exclude-standard", "-z"], root))
    return [p for p in out.split("\0") if p]


def show(root: Path, rev: str, path: str) -> bytes | None:
    """Contenido de `path` en `rev` (rev vacío = índice). None si no existe."""
    proc = _run(["show", f"{rev}:{path}"], root)
    return proc.stdout if proc.returncode == 0 else None


def read_worktree(root: Path, path: str) -> bytes | None:
    try:
        return (root / path).read_bytes()
    except OSError:
        return None
