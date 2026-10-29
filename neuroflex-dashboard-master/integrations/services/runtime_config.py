"""In-memory singleton mirroring the resolved .env files."""

from __future__ import annotations

import os
import re
import tempfile
import threading
from pathlib import Path

from dotenv import dotenv_values


BASE_DIR = Path(__file__).resolve().parent.parent.parent
ALLOWED_KEYS = (
    "NEUROFLEX_API_BASE_URL",
    "COGNITO_CLIENT_ID",
    "GITHUB_TOKEN",
)
_DEFAULTS = {
    "NEUROFLEX_API_BASE_URL": "change-me",
    "COGNITO_CLIENT_ID": "change-me",
    "GITHUB_TOKEN": "",
}


def resolve_dotenv_path() -> Path:
    """Return the .env path used for writes."""
    data_dir = Path(os.environ.get("NEUROFLEX_DATA_DIR", BASE_DIR))
    return data_dir / ".env"


def _read_dotenv_values() -> dict:
    """Read the base .env, then let the data-dir .env override it."""
    data_dir = Path(os.environ.get("NEUROFLEX_DATA_DIR", BASE_DIR))
    merged = dotenv_values(BASE_DIR / ".env")
    if data_dir != BASE_DIR:
        merged.update(dotenv_values(data_dir / ".env"))
    return merged


def _serialize_dotenv_value(value: str) -> str:
    """Serialize a value without allowing dotenv syntax to change its value."""
    if value and re.fullmatch(r"[A-Za-z0-9_./:@%+=,-]+", value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("\r", "\\r").replace("\n", "\\n")
    return f'"{escaped}"'


def _inline_comment_suffix(value: str) -> str:
    quote = None
    escaped = False
    for index, character in enumerate(value):
        if escaped:
            escaped = False
            continue
        if character == "\\":
            escaped = True
            continue
        if character in ('"', "'"):
            quote = None if quote == character else character if quote is None else quote
            continue
        if character == "#" and quote is None and (
            index == 0 or value[index - 1].isspace()
        ):
            return value[len(value[:index].rstrip()) :]
    return ""


def _serialize_dotenv_updates(path: Path, updates: dict[str, str]) -> str:
    """Return path contents with only the requested assignments changed."""
    try:
        with path.open("r", encoding="utf-8", newline="") as dotenv_file:
            content = dotenv_file.read()
    except FileNotFoundError:
        content = ""

    lines = content.splitlines(keepends=True)
    found = set()
    patterns = {
        key: re.compile(rf"^(\s*(?:export\s+)?{re.escape(key)}\s*=\s*)(.*?)(\r?\n)?$")
        for key in updates
    }
    serialized_lines = []
    for line in lines:
        replacement = None
        for key, pattern in patterns.items():
            match = pattern.match(line)
            if match:
                comment_suffix = _inline_comment_suffix(match.group(2))
                replacement = (
                    f"{match.group(1)}{_serialize_dotenv_value(updates[key])}"
                    f"{comment_suffix}{match.group(3) or ''}"
                )
                found.add(key)
                break
        serialized_lines.append(replacement if replacement is not None else line)

    missing = [key for key in updates if key not in found]
    if missing:
        newline = "\r\n" if "\r\n" in content else "\n"
        if serialized_lines and not serialized_lines[-1].endswith(("\n", "\r")):
            serialized_lines.append(newline)
        serialized_lines.extend(
            f"{key}={_serialize_dotenv_value(updates[key])}{newline}"
            for key in missing
        )
    return "".join(serialized_lines)


class RuntimeConfig:
    """Singleton holding the editable configuration values in memory."""

    _instance = None
    _singleton_lock = threading.Lock()

    def __new__(cls):
        with cls._singleton_lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance._initialize()
                cls._instance = instance
        return cls._instance

    def _initialize(self):
        self.dotenv_path = resolve_dotenv_path()
        self._lock = threading.RLock()
        # Keep the old name available for callers that coordinate updates.
        self._update_lock = self._lock
        file_values = _read_dotenv_values()
        with self._lock:
            self._values = {
                key: (
                    os.environ.get(key)
                    or file_values.get(key)
                    or _DEFAULTS[key]
                )
                for key in ALLOWED_KEYS
            }

    def read_config(self) -> dict:
        """Return a consistent snapshot of all editable values."""
        with self._lock:
            return dict(self._values)

    def get_neuroflex_api_base_url(self) -> str:
        with self._lock:
            return self._values["NEUROFLEX_API_BASE_URL"]

    def get_cognito_client_id(self) -> str:
        with self._lock:
            return self._values["COGNITO_CLIENT_ID"]

    def get_github_token(self) -> str:
        with self._lock:
            return self._values["GITHUB_TOKEN"]

    def update(self, values: dict) -> dict:
        """Persist allowed values before refreshing the in-memory snapshot."""
        updates = {key: str(values[key]) for key in ALLOWED_KEYS if key in values}
        if not updates:
            return self.read_config()
        if "GITHUB_TOKEN" in updates and len(updates["GITHUB_TOKEN"]) < 70:
            raise ValueError("GITHUB_TOKEN must be at least 70 characters long")

        with self._lock:
            self.dotenv_path.parent.mkdir(parents=True, exist_ok=True)
            serialized = _serialize_dotenv_updates(self.dotenv_path, updates)
            temporary_path = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    newline="",
                    dir=self.dotenv_path.parent,
                    prefix=f".{self.dotenv_path.name}.",
                    suffix=".tmp",
                    delete=False,
                ) as temporary_file:
                    temporary_path = Path(temporary_file.name)
                    temporary_file.write(serialized)
                    temporary_file.flush()
                os.replace(temporary_path, self.dotenv_path)
            finally:
                if temporary_path is not None:
                    try:
                        temporary_path.unlink()
                    except FileNotFoundError:
                        pass

            self._values.update(updates)
            return dict(self._values)
