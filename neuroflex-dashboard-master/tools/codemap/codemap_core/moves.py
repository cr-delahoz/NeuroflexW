"""Detección de archivos movidos: un borrado y un archivo nuevo muy parecidos.

Git solo detecta renombres entre archivos con seguimiento; un archivo movido a
una carpeta todavía sin `git add` aparece como "borrado + nuevo". Aquí se
emparejan por nombre y similitud de contenido.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import PurePosixPath

THRESHOLD = 0.6
MAX_BLIND_PAIRS = 100  # comparaciones permitidas entre archivos de distinto nombre


@dataclass
class FileContent:
    path: str
    data: bytes | None
    text: str | None


def similarity(a: FileContent, b: FileContent) -> float:
    if a.data is not None and a.data == b.data:
        return 1.0
    if a.text is None or b.text is None:
        return 0.0
    left, right = a.text.splitlines(), b.text.splitlines()
    matcher = SequenceMatcher(None, left, right, autojunk=False)
    if matcher.real_quick_ratio() < THRESHOLD or matcher.quick_ratio() < THRESHOLD:
        return 0.0
    return matcher.ratio()


def pair_moves(deleted: list[FileContent], added: list[FileContent]) -> list[tuple[FileContent, FileContent, float]]:
    blind = len(deleted) * len(added) <= MAX_BLIND_PAIRS
    candidates = []
    for old in deleted:
        for new in added:
            same_name = PurePosixPath(old.path).name.lower() == PurePosixPath(new.path).name.lower()
            if not same_name and not blind:
                continue
            ratio = similarity(old, new)
            if ratio >= THRESHOLD:
                candidates.append((same_name, ratio, old, new))
    candidates.sort(key=lambda c: (c[0], c[1]), reverse=True)

    used_old, used_new, pairs = set(), set(), []
    for _, ratio, old, new in candidates:
        if old.path in used_old or new.path in used_new:
            continue
        used_old.add(old.path)
        used_new.add(new.path)
        pairs.append((old, new, ratio))
    return pairs
