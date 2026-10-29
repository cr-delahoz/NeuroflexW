"""Orquestador: git diff -> símbolos -> secciones -> etiquetas -> ChangeSet."""

from __future__ import annotations

import difflib
import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath

from . import diffparse, gitsource, summarize, symbols, tags
from .diffparse import DiffLine, FileDiff, Hunk
from .model import ADDED, DELETED, MODIFIED, MOVED, Change, ChangeSet, Evidence
from .moves import FileContent, pair_moves
from .sections import SectionMatcher, load_config

TOOL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = TOOL_DIR / "codemap.config.json"
MAX_DIFF_LINES = 400
MAX_EVIDENCE = 12
SYMBOL_RENAME_THRESHOLD = 0.7
SYMBOL_RENAME_MIN_LINES = 3
# En estos archivos las partes (bloques, apartados) se listan dentro de un único
# cambio por archivo; en código (Python, JS) cada función es un cambio aparte.
FILE_GRANULAR = (".html", ".htm", ".jinja", ".j2", ".md", ".markdown")
_IMPORT_RE = re.compile(r"^\s*(?:import\s+([\w.]+)|from\s+([\w.]+)\s+import\b)")


class _Sources:
    """Contenido viejo (base) y nuevo (árbol de trabajo o índice), con caché."""

    def __init__(self, root: Path, base_ref: str, staged: bool):
        self.root, self.base_ref, self.staged = root, base_ref, staged
        self._cache: dict[tuple[str, str], FileContent] = {}

    def _load(self, side: str, path: str) -> FileContent:
        key = (side, path)
        if key not in self._cache:
            if side == "old":
                data = None if self.base_ref == gitsource.EMPTY_TREE else gitsource.show(self.root, self.base_ref, path)
            elif self.staged:
                data = gitsource.show(self.root, "", path)
            else:
                data = gitsource.read_worktree(self.root, path)
            self._cache[key] = FileContent(path, data, gitsource.to_text(data))
        return self._cache[key]

    def old(self, path: str | None) -> FileContent | None:
        return self._load("old", path) if path else None

    def new(self, path: str | None) -> FileContent | None:
        return self._load("new", path) if path else None


# --- utilidades ---------------------------------------------------------------

def _lines(text: str | None) -> list[str]:
    return text.splitlines() if text else []


def _hunks_between(old_text: str | None, new_text: str | None) -> list[Hunk]:
    body = "\n".join(difflib.unified_diff(_lines(old_text), _lines(new_text), "a/x", "b/x", lineterm=""))
    parsed = diffparse.parse("diff --git a/x b/x\n" + body)
    return parsed[0].hunks if parsed else []


def _all_added(path: str, content: FileContent) -> FileDiff:
    diff = FileDiff(None, path, status="added", binary=content.text is None and content.data is not None)
    lines = _lines(content.text)
    if lines:
        diff.hunks.append(Hunk(0, 0, 1, len(lines),
                               lines=[DiffLine("+", None, i, t) for i, t in enumerate(lines, 1)]))
    return diff


def _all_removed(lines: list[str]) -> list[DiffLine]:
    return [DiffLine("-", i, None, t) for i, t in enumerate(lines, 1)]


def _runs(numbers: list[int]) -> list[tuple[int, int]]:
    runs: list[list[int]] = []
    for n in sorted(set(numbers)):
        if runs and n <= runs[-1][1] + 2:
            runs[-1][1] = n
        else:
            runs.append([n, n])
    return [(a, b) for a, b in runs]


def _evidence(path: str, old_path: str | None, lines: list[DiffLine]) -> list[Evidence]:
    added = [ln.new_no for ln in lines if ln.kind == "+"]
    if added:
        return [Evidence(path, a, b, "nuevo") for a, b in _runs(added)][:MAX_EVIDENCE]
    removed = [ln.old_no for ln in lines if ln.kind == "-"]
    return [Evidence(old_path or path, a, b, "viejo") for a, b in _runs(removed)][:MAX_EVIDENCE]


def _display(entries: list[tuple[int, DiffLine]]) -> list[dict]:
    out: list[dict] = []
    prev = None
    for shown, (idx, ln) in enumerate(entries):
        if shown == MAX_DIFF_LINES:
            out.append({"t": "…", "x": f"{len(entries) - shown} líneas más; abre el archivo para verlas"})
            break
        if prev is not None and idx != prev + 1:
            out.append({"t": "…"})
        prev = idx
        out.append({"t": ln.kind, "o": ln.old_no, "n": ln.new_no, "x": ln.text})
    return out


def _numbered(hunks: list[Hunk]) -> list[tuple[int, DiffLine]]:
    entries, idx = [], 0
    for hunk in hunks:
        for ln in hunk.lines:
            entries.append((idx, ln))
            idx += 1
        idx += 1  # hueco entre hunks -> separador en la vista
    return entries


def _counts(lines: list[DiffLine]) -> dict:
    return {"añadidas": sum(1 for ln in lines if ln.kind == "+"),
            "eliminadas": sum(1 for ln in lines if ln.kind == "-")}


def _detect(path: str, lines: list[DiffLine], ignore: set[str] | None = None) -> list[tags.Tag]:
    return tags.detect(path, [ln.text for ln in lines if ln.kind == "+"],
                       [ln.text for ln in lines if ln.kind == "-"], ignore)


def _moved_in_file(lines: list[DiffLine]) -> set[str]:
    return tags.moved_lines([ln.text for ln in lines if ln.kind == "+"],
                            [ln.text for ln in lines if ln.kind == "-"])


def _safe_extract(path: str | None, text: str | None) -> tuple[list[symbols.Symbol] | None, str | None]:
    if path is None or text is None:
        return None, None
    try:
        return symbols.extract(path, text), None
    except symbols.ParseFailure as exc:
        return None, str(exc)


def _top_symbols(syms: list[symbols.Symbol] | None) -> list[list[str]]:
    return [[s.kind, s.name] for s in syms or [] if "." not in s.name or s.kind == symbols.HEADING]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


# --- construcción de cambios ---------------------------------------------------

def _base_change(f: FileDiff, section: str, kind: str, symbol: str | None, symbol_kind: str,
                 lines: list[DiffLine], entries: list[tuple[int, DiffLine]]) -> Change:
    path = f.path
    fingerprint = hashlib.sha1(
        "\n".join(f"{ln.kind}{ln.text.strip()}" for ln in lines if ln.kind != " ").encode("utf-8")
    ).hexdigest()[:12]
    return Change(
        id=f"{path}::{symbol or '*'}",
        seccion=section,
        archivo=path,
        tipo_cambio=kind,
        simbolo=symbol,
        tipo_simbolo=symbol_kind,
        lineas=_counts(lines),
        evidencia=_evidence(path, f.old_path, lines),
        diff=_display(entries),
        archivo_anterior=f.old_path if kind == MOVED else None,
        huella=fingerprint,
    )


def _whole_file_change(f: FileDiff, section: str, old: FileContent | None,
                       new: FileContent | None) -> Change:
    entries = _numbered(f.hunks)
    lines = [ln for _, ln in entries]
    if f.status == "added":
        kind = ADDED
    elif f.status == "deleted":
        kind = DELETED
        if not lines and old and old.text:
            lines = _all_removed(_lines(old.text))
            entries = list(enumerate(lines))
    elif f.status == "renamed":
        kind = MOVED
    else:
        kind = MODIFIED
    change = _base_change(f, section, kind, None, "archivo", lines, entries)
    found = [] if f.binary else _detect(f.path, lines, _moved_in_file(lines))

    if f.binary:
        change.detalles["binario"] = True
    if kind == MOVED:
        change.detalles["similitud"] = f.similarity if f.similarity is not None else 100
        if not change.evidencia and new and new.text:
            change.evidencia = [Evidence(f.path, 1, max(1, len(_lines(new.text))))]
    if kind in (ADDED, DELETED) and not f.binary:
        content = new if kind == ADDED else old
        syms, error = _safe_extract(content.path if content else None, content.text if content else None)
        change.detalles["total_lineas"] = len(_lines(content.text if content else None))
        change.detalles["simbolos"] = _top_symbols(syms)
        if error and kind == ADDED:
            change.detalles["error_sintaxis"] = error
            found.append(tags.SYNTAX_ERROR)
        if kind == DELETED:
            change.riesgo = 1
    return summarize.fill(change, found)


@dataclass
class _Group:
    key: str | None
    entries: list[tuple[int, DiffLine]] = field(default_factory=list)
    renamed_from: str | None = None

    @property
    def changed(self) -> list[DiffLine]:
        return [ln for _, ln in self.entries if ln.kind != " "]


def _symbol_body(text: str | None, sym: symbols.Symbol) -> list[str]:
    """Líneas del símbolo sin su primera línea (nombre/firma), sin espacios sobrantes."""
    return [ln.strip() for ln in _lines(text)[sym.start:sym.end] if ln.strip()]


def _merge_renamed_symbols(groups: dict, old_by: dict, new_by: dict,
                           old_text: str | None, new_text: str | None) -> None:
    deleted = [k for k in groups if k is not None and k in old_by and k not in new_by]
    added = [k for k in groups if k is not None and k in new_by and k not in old_by]
    for old_key in deleted:
        old_body = _symbol_body(old_text, old_by[old_key])
        if len(old_body) < SYMBOL_RENAME_MIN_LINES:
            continue  # en funciones mínimas el parecido es casualidad
        best, best_ratio = None, SYMBOL_RENAME_THRESHOLD
        for new_key in added:
            if new_by[new_key].kind != old_by[old_key].kind:
                continue
            new_body = _symbol_body(new_text, new_by[new_key])
            ratio = difflib.SequenceMatcher(None, old_body, new_body, autojunk=False).ratio()
            if ratio >= best_ratio:
                best, best_ratio = new_key, ratio
        if best:
            target = groups[best]
            target.entries = sorted(target.entries + groups.pop(old_key).entries, key=lambda e: e[0])
            target.renamed_from = old_key
            added.remove(best)


def _symbol_changes(f: FileDiff, section: str, old: FileContent, new: FileContent,
                    old_syms: list[symbols.Symbol], new_syms: list[symbols.Symbol]) -> list[Change]:
    groups: dict[str | None, _Group] = {}
    for idx, ln in _numbered(f.hunks):
        if ln.kind == "-":
            sym = symbols.innermost(old_syms, ln.old_no)
        else:
            sym = symbols.innermost(new_syms, ln.new_no)
        key = sym.name if sym else None
        groups.setdefault(key, _Group(key)).entries.append((idx, ln))

    old_by = {s.name: s for s in old_syms}
    new_by = {s.name: s for s in new_syms}
    _merge_renamed_symbols(groups, old_by, new_by, old.text, new.text)
    suffix = PurePosixPath(f.path).suffix.lower()
    is_python = suffix in (".py", ".pyw")
    all_changed = [ln for h in f.hunks for ln in h.lines if ln.kind != " "]
    moved = _moved_in_file(all_changed)

    classified = []
    for key, group in groups.items():
        if not any(ln.text.strip() for ln in group.changed):
            continue  # solo líneas en blanco o contexto
        if key is None:
            kind, sym = MODIFIED, None
        elif group.renamed_from:
            kind, sym = MODIFIED, new_by[key]
        elif key in new_by and key not in old_by:
            kind, sym = ADDED, new_by[key]
        elif key in old_by and key not in new_by:
            kind, sym = DELETED, old_by[key]
        else:
            kind, sym = MODIFIED, new_by[key]
        classified.append((key, group, kind, sym))

    if suffix in FILE_GRANULAR:
        return [_aggregated_change(f, section, classified, moved)]

    changes = []
    for key, group, kind, sym in classified:
        changed = group.changed
        symbol_kind = sym.kind if sym else ("módulo" if is_python else "archivo")
        change = _base_change(f, section, kind, key, symbol_kind, changed, group.entries)
        details = change.detalles

        if kind == MODIFIED and sym is not None:
            before = old_by[group.renamed_from or key]
            old_sig = _norm(before.signature).replace(before.name.split(".")[-1], sym.name.split(".")[-1], 1)
            if old_sig != _norm(sym.signature):
                details["firma"] = {"antes": _norm(before.signature), "despues": _norm(sym.signature)}
            gone = [d for d in before.decorators if d not in sym.decorators]
            came = [d for d in sym.decorators if d not in before.decorators]
            if gone or came:
                details["decoradores"] = {"añadidos": came, "quitados": gone}
            if group.renamed_from:
                details["renombrado_desde"] = group.renamed_from
        if key is None and is_python:
            added_imports = [m.group(1) or m.group(2) for ln in changed if ln.kind == "+"
                             for m in [_IMPORT_RE.match(ln.text)] if m]
            removed_imports = [m.group(1) or m.group(2) for ln in changed if ln.kind == "-"
                               for m in [_IMPORT_RE.match(ln.text)] if m]
            details["importaciones"] = {
                "añadidas": [m for m in added_imports if m not in removed_imports],
                "quitadas": [m for m in removed_imports if m not in added_imports],
            }
            meaningful = [ln for ln in changed if ln.text.strip() and not ln.text.strip().startswith("#")]
            details["solo_importaciones"] = all(_IMPORT_RE.match(ln.text) for ln in meaningful)
        if kind == DELETED:
            change.riesgo = 1
        changes.append(summarize.fill(change, _detect(f.path, changed, moved)))
    return changes


def _aggregated_change(f: FileDiff, section: str, classified: list, moved: set[str]) -> Change:
    """Un único cambio por archivo (plantillas, Markdown) con el detalle de sus partes."""
    entries = sorted((e for _, group, _, _ in classified for e in group.entries), key=lambda e: e[0])
    lines = [ln for _, ln in entries if ln.kind != " "]
    change = _base_change(f, section, MODIFIED, None, "archivo", lines, entries)
    parts = {"añadidas": [], "eliminadas": [], "modificadas": [], "tipo": None}
    bucket = {ADDED: "añadidas", DELETED: "eliminadas", MODIFIED: "modificadas"}
    for key, group, kind, sym in classified:
        if key is None:
            continue
        parts["tipo"] = parts["tipo"] or sym.kind
        name = f"{group.renamed_from} → {key}" if group.renamed_from else key
        parts[bucket[kind]].append(name)
    if parts["tipo"]:
        change.detalles["partes"] = parts
    return summarize.fill(change, _detect(f.path, lines, moved))


def _file_changes(f: FileDiff, sources: _Sources, matcher: SectionMatcher) -> list[Change]:
    old = sources.old(f.old_path)
    new = sources.new(f.new_path)
    content = new if new and new.text is not None else old
    section = matcher.section_for(f.path, content.text if content else None)

    if new is not None and new.text is None and new.data is not None:
        f.binary = True
    if f.binary or f.status != "modified":
        return [_whole_file_change(f, section, old, new)]
    if not f.hunks:
        return []  # p. ej. solo cambió el modo del archivo

    old_syms, _ = _safe_extract(f.old_path, old.text if old else None)
    new_syms, new_error = _safe_extract(f.path, new.text if new else None)
    if old_syms is None or new_syms is None:
        change = _whole_file_change(f, section, old, new)
        if new_error:
            change.detalles["error_sintaxis"] = new_error
            lines = [ln for h in f.hunks for ln in h.lines]
            change = summarize.fill(change, _detect(f.path, lines, _moved_in_file(lines)) + [tags.SYNTAX_ERROR])
        return [change]
    return _symbol_changes(f, section, old, new, old_syms, new_syms)


def _detect_moves(files: list[FileDiff], sources: _Sources) -> list[FileDiff]:
    deleted = [f for f in files if f.status == "deleted"]
    added = [f for f in files if f.status == "added"]
    if not deleted or not added:
        return files
    pairs = pair_moves([sources.old(f.old_path) for f in deleted], [sources.new(f.new_path) for f in added])
    if not pairs:
        return files
    gone = {old.path for old, _, _ in pairs} | {new.path for _, new, _ in pairs}
    result = [f for f in files if f.path not in gone]
    for old, new, ratio in pairs:
        binary = new.text is None
        moved = FileDiff(old.path, new.path, status="renamed", binary=binary, similarity=round(ratio * 100))
        if not binary:
            moved.hunks = _hunks_between(old.text, new.text)
        result.append(moved)
    return result


def analyze(repo: str | Path = ".", base: str = "HEAD", staged: bool = False,
            config_path: Path | None = None) -> ChangeSet:
    root = gitsource.repo_root(repo).resolve()
    config = load_config(config_path or DEFAULT_CONFIG)
    extra_exclude = []
    try:
        extra_exclude.append(TOOL_DIR.relative_to(root).as_posix() + "/**")
    except ValueError:
        pass  # Codemap analiza un repo distinto al suyo
    matcher = SectionMatcher(config, extra_exclude)

    base_ref, short_sha = gitsource.resolve_base(root, base)
    sources = _Sources(root, base_ref, staged)
    files = diffparse.parse(gitsource.diff(root, base_ref, staged))
    if not staged:
        for path in gitsource.untracked(root):
            if not matcher.excluded(path):
                files.append(_all_added(path, sources.new(path)))
    files = [f for f in files if not matcher.excluded(f.path)]
    files = _detect_moves(files, sources)

    changes: list[Change] = []
    for f in files:
        changes.extend(_file_changes(f, sources, matcher))
    changes.sort(key=lambda c: (
        matcher.order(c.seccion), -c.riesgo, c.archivo.lower(),
        c.evidencia[0].linea_inicio if c.evidencia else 0,
    ))

    return ChangeSet(
        repo=root.name,
        base=base if base_ref != gitsource.EMPTY_TREE else "(repositorio sin commits)",
        base_commit=short_sha,
        modo="índice (staged)" if staged else "árbol de trabajo",
        generado=datetime.now().isoformat(timespec="seconds"),
        secciones=matcher.sections,
        cambios=changes,
    )
