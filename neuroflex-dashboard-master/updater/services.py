import hashlib
import os
import sys
from pathlib import Path

import requests

from integrations.services.runtime_config import RuntimeConfig

GITHUB_API_URL = (
    "https://api.github.com/repos/basstiago/neuroflex-dashboard/releases/latest"
)
REQUEST_TIMEOUT = 10


def _get_auth_headers() -> dict:
    token = RuntimeConfig().get_github_token()
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


class UpdaterError(Exception):
    pass


def _get_install_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(os.path.dirname(os.path.abspath(__file__)))


def get_current_version() -> str:
    version_file = _get_install_dir() / "VERSION"
    if not version_file.exists():
        return "unknown"
    return version_file.read_text(encoding="utf-8").strip()


def get_latest_release_info() -> dict | None:
    try:
        response = requests.get(
            GITHUB_API_URL,
            headers={
                **_get_auth_headers(),
                "Accept": "application/vnd.github+json",
            },
            timeout=REQUEST_TIMEOUT,
        )
    except requests.exceptions.RequestException:
        return None

    if response.status_code != 200:
        return None

    try:
        release_data = response.json()
    except ValueError:
        return None

    tag_name = release_data.get("tag_name", "")
    version = tag_name.lstrip("v")
    changelog = release_data.get("body", "") or ""

    assets = release_data.get("assets", [])

    exe_asset = next(
        (a for a in assets if a.get("name", "").endswith(".exe")), None
    )
    if exe_asset is None:
        return None
    url = exe_asset.get("url", "")
    filename = exe_asset.get("name", "")

    json_asset = next(
        (a for a in assets if a.get("name") == "latest.json"), None
    )
    if json_asset is None:
        return None

    sha256 = _fetch_sha256_from_latest_json(
        json_asset.get("url", "")
    )
    if sha256 is None:
        return None

    return {
        "version": version,
        "changelog": changelog,
        "url": url,
        "filename": filename,
        "sha256": sha256,
    }


def _fetch_sha256_from_latest_json(json_url: str) -> str | None:
    try:
        response = requests.get(
            json_url,
            headers={
                **_get_auth_headers(),
                "Accept": "application/octet-stream",
            },
            timeout=REQUEST_TIMEOUT,
        )
    except requests.exceptions.RequestException:
        return None

    if response.status_code != 200:
        return None

    try:
        data = response.json()
    except ValueError:
        return None

    return data.get("sha256")


def download_installer(
    url: str,
    expected_sha256: str,
    dest_dir: Path | None = None,
    filename: str | None = None,
) -> Path:
    if dest_dir is None:
        dest_dir = Path(os.environ.get("TEMP", "/tmp"))

    dest_dir.mkdir(parents=True, exist_ok=True)
    if filename:
        filename = Path(filename).name
        if not filename:
            raise UpdaterError("Nombre de archivo inválido.")
    else:
        filename = url.rsplit("/", 1)[-1]
    dest_path = dest_dir / filename

    try:
        response = requests.get(
            url,
            headers={
                **_get_auth_headers(),
                "Accept": "application/octet-stream",
            },
            stream=True,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()

        hasher = hashlib.sha256()
        with open(dest_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    hasher.update(chunk)
    except Exception as exc:
        dest_path.unlink(missing_ok=True)
        raise UpdaterError(f"Error al descargar el instalador: {exc}")

    actual_hash = hasher.hexdigest().lower()
    if actual_hash != expected_sha256.lower():
        dest_path.unlink(missing_ok=True)
        raise UpdaterError(
            f"SHA256 mismatch: expected {expected_sha256}, got {actual_hash}"
        )

    return dest_path


def download_installer_with_progress(job_id, callback, url, expected_sha256, dest_dir=None, filename=None):
    del job_id
    if dest_dir is None:
        dest_dir = Path(os.environ.get("TEMP", "/tmp"))
    dest_dir.mkdir(parents=True, exist_ok=True)
    if filename:
        filename = Path(filename).name
        if not filename:
            raise UpdaterError("Nombre de archivo inválido.")
    else:
        filename = url.rsplit("/", 1)[-1]
    dest_path = dest_dir / filename
    try:
        response = requests.get(url, headers={**_get_auth_headers(), "Accept": "application/octet-stream"}, stream=True, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        try:
            total = int(response.headers.get("Content-Length", ""))
        except ValueError:
            total = 0
        total = total if total > 0 else None
        if total is None:
            callback(None, "Descargando instalador…")
        written = 0
        hasher = hashlib.sha256()
        with open(dest_path, "wb") as output:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    output.write(chunk)
                    hasher.update(chunk)
                    written += len(chunk)
                    if total is not None:
                        callback(min(100, int(written * 100 / total)), "Descargando instalador…")
    except Exception as exc:
        dest_path.unlink(missing_ok=True)
        raise UpdaterError(f"Error al descargar el instalador: {exc}")
    actual_hash = hasher.hexdigest().lower()
    if actual_hash != expected_sha256.lower():
        dest_path.unlink(missing_ok=True)
        raise UpdaterError(f"SHA256 mismatch: expected {expected_sha256}, got {actual_hash}")
    return dest_path


def _parse_version(version_str: str) -> list[int]:
    parts = version_str.strip().lstrip("v").split(".")
    try:
        return [int(p) for p in parts]
    except ValueError:
        return [0]


def has_update_available() -> dict | None:
    latest = get_latest_release_info()
    if latest is None:
        return None

    current_version = get_current_version()
    if current_version == "unknown":
        return None

    current = _parse_version(current_version)
    remote = _parse_version(latest.get("version", "0.0.0"))

    if remote <= current:
        return None

    return {
        "version": latest.get("version", ""),
        "changelog": latest.get("changelog", ""),
        "url": latest.get("url", ""),
        "filename": latest.get("filename", ""),
        "sha256": latest.get("sha256", ""),
    }
