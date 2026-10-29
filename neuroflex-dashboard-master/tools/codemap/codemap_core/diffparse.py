"""Parser de unified diff (salida de `git diff`)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")
_ESCAPES = {"n": "\n", "t": "\t", '"': '"', "\\": "\\", "a": "\a",
            "b": "\b", "f": "\f", "r": "\r", "v": "\v"}


@dataclass
class DiffLine:
    kind: str  # "+", "-" o " "
    old_no: int | None
    new_no: int | None
    text: str


@dataclass
class Hunk:
    old_start: int
    old_len: int
    new_start: int
    new_len: int
    context: str = ""
    lines: list[DiffLine] = field(default_factory=list)


@dataclass
class FileDiff:
    old_path: str | None
    new_path: str | None
    status: str = "modified"  # added | deleted | modified | renamed
    binary: bool = False
    similarity: int | None = None
    hunks: list[Hunk] = field(default_factory=list)

    @property
    def path(self) -> str:
        return self.new_path or self.old_path or ""

    @property
    def added(self) -> int:
        return sum(1 for h in self.hunks for ln in h.lines if ln.kind == "+")

    @property
    def removed(self) -> int:
        return sum(1 for h in self.hunks for ln in h.lines if ln.kind == "-")


def unquote(path: str) -> str:
    """Deshace el entrecomillado estilo C que git aplica a rutas especiales."""
    if len(path) < 2 or path[0] != '"' or path[-1] != '"':
        return path
    body, out, i = path[1:-1], bytearray(), 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            nxt = body[i + 1]
            if nxt in "01234567":
                digits = re.match(r"[0-7]{1,3}", body[i + 1:]).group(0)
                out.append(int(digits, 8) & 0xFF)
                i += 1 + len(digits)
                continue
            out += _ESCAPES.get(nxt, nxt).encode("utf-8")
            i += 2
            continue
        out += ch.encode("utf-8")
        i += 1
    return out.decode("utf-8", "replace")


def _strip_prefix(path: str, prefix: str) -> str | None:
    path = unquote(path.rstrip("\t"))
    if path == "/dev/null":
        return None
    return path[len(prefix):] if path.startswith(prefix) else path


def _header_paths(rest: str) -> tuple[str | None, str | None]:
    """Rutas de la línea `diff --git a/X b/Y` (solo como respaldo)."""
    if rest.startswith('"'):
        end = rest.find('" ', 1)
        while end != -1 and rest[end - 1] == "\\":
            end = rest.find('" ', end + 1)
        if end != -1:
            return _strip_prefix(rest[:end + 1], "a/"), _strip_prefix(rest[end + 2:], "b/")
    half = (len(rest) - 5) // 2
    candidate = rest[2:2 + half]
    if rest == f"a/{candidate} b/{candidate}":
        return candidate, candidate
    cut = rest.rfind(" b/")
    if cut != -1:
        return _strip_prefix(rest[:cut], "a/"), _strip_prefix(rest[cut + 1:], "b/")
    return None, None


def parse(text: str) -> list[FileDiff]:
    files: list[FileDiff] = []
    current: FileDiff | None = None
    hunk: Hunk | None = None
    old_left = new_left = old_no = new_no = 0

    for raw in text.split("\n"):
        line = raw[:-1] if raw.endswith("\r") else raw

        if hunk is not None and (old_left > 0 or new_left > 0):
            if line.startswith("\\"):
                continue
            kind = line[:1] or " "
            body = line[1:]
            if kind == "+":
                hunk.lines.append(DiffLine("+", None, new_no, body))
                new_no += 1
                new_left -= 1
            elif kind == "-":
                hunk.lines.append(DiffLine("-", old_no, None, body))
                old_no += 1
                old_left -= 1
            else:
                hunk.lines.append(DiffLine(" ", old_no, new_no, body))
                old_no += 1
                new_no += 1
                old_left -= 1
                new_left -= 1
            continue

        if line.startswith("diff --git "):
            old, new = _header_paths(line[len("diff --git "):])
            current = FileDiff(old, new)
            files.append(current)
            hunk = None
            continue
        if current is None:
            continue

        match = HUNK_RE.match(line)
        if match:
            o_start, o_len, n_start, n_len, ctx = match.groups()
            hunk = Hunk(int(o_start), int(o_len or 1), int(n_start), int(n_len or 1), ctx.strip())
            current.hunks.append(hunk)
            old_no, new_no = hunk.old_start, hunk.new_start
            old_left, new_left = hunk.old_len, hunk.new_len
        elif line.startswith("new file mode"):
            current.status = "added"
        elif line.startswith("deleted file mode"):
            current.status = "deleted"
        elif line.startswith("rename from "):
            current.old_path = unquote(line[len("rename from "):])
            current.status = "renamed"
        elif line.startswith("rename to "):
            current.new_path = unquote(line[len("rename to "):])
            current.status = "renamed"
        elif line.startswith("similarity index "):
            current.similarity = int(line[len("similarity index "):].rstrip("%") or 0)
        elif line.startswith("--- "):
            current.old_path = _strip_prefix(line[4:], "a/")
        elif line.startswith("+++ "):
            current.new_path = _strip_prefix(line[4:], "b/")
        elif line.startswith("Binary files ") or line.startswith("GIT binary patch"):
            current.binary = True

    for f in files:
        if f.status == "added":
            f.old_path = None
        elif f.status == "deleted":
            f.new_path = None
    return files
