"""Read/write the 3 editable local config values, validating input.

Persistence is delegated to RuntimeConfig so the .env file and the
in-memory values stay in sync atomically.
"""

from __future__ import annotations

from urllib.parse import urlparse

from integrations.services.runtime_config import RuntimeConfig


ALLOWED_KEYS = ("NEUROFLEX_API_BASE_URL", "COGNITO_CLIENT_ID", "GITHUB_TOKEN")
MIN_GITHUB_TOKEN_LENGTH = 70


class LocalConfigValidationError(ValueError):
    """Raised when submitted config values are invalid."""


def mask_token(token: str) -> str:
    """Mask a token while showing only its last four characters."""
    if not token:
        return ""
    if len(token) == 1:
        return token[-1]
    if len(token) <= 4:
        return "•" * (len(token) - 1) + token[-1]
    return "•" * (len(token) - 4) + token[-4:]


def read_config() -> dict:
    """Return the editable values with GITHUB_TOKEN masked."""
    values = RuntimeConfig().read_config()
    return {
        "NEUROFLEX_API_BASE_URL": values["NEUROFLEX_API_BASE_URL"],
        "COGNITO_CLIENT_ID": values["COGNITO_CLIENT_ID"],
        "GITHUB_TOKEN": mask_token(values["GITHUB_TOKEN"]),
    }


def write_config(values: dict) -> dict:
    """Validate and persist values, returning the new masked read view."""
    validated = _validate(values)
    RuntimeConfig().update(validated)
    return read_config()


def _validate(values: dict) -> dict:
    if not isinstance(values, dict):
        raise LocalConfigValidationError("Se esperaba un objeto JSON.")

    if any(not isinstance(key, str) for key in values):
        raise LocalConfigValidationError("Las claves deben ser cadenas de texto.")

    unknown = set(values) - set(ALLOWED_KEYS)
    if unknown:
        raise LocalConfigValidationError(
            f"Claves no permitidas: {', '.join(sorted(unknown))}."
        )

    current_token = RuntimeConfig().get_github_token()
    validated = {}
    for key in ALLOWED_KEYS:
        if key == "GITHUB_TOKEN" and key not in values:
            if current_token:
                if len(current_token) < MIN_GITHUB_TOKEN_LENGTH:
                    raise LocalConfigValidationError(
                        "El token debe tener al menos 70 caracteres."
                    )
                continue
            raise LocalConfigValidationError("Este campo es obligatorio.")

        value = values.get(key)
        if not isinstance(value, str) or not value.strip():
            raise LocalConfigValidationError(f"El campo {key} es obligatorio.")
        if "\r" in value or "\n" in value:
            raise LocalConfigValidationError(
                "El valor no puede contener saltos de línea."
            )
        value = value.strip()

        if key == "NEUROFLEX_API_BASE_URL":
            try:
                parsed = urlparse(value)
                parsed.port
            except ValueError as exc:
                raise LocalConfigValidationError(
                    "NEUROFLEX_API_BASE_URL debe ser una URL http/https válida."
                ) from exc
            if (
                parsed.scheme not in ("http", "https")
                or not parsed.netloc
                or not parsed.hostname
            ):
                raise LocalConfigValidationError(
                    "NEUROFLEX_API_BASE_URL debe ser una URL http/https válida."
                )
        if key == "GITHUB_TOKEN" and value.startswith("•"):
            raise LocalConfigValidationError(
                "GITHUB_TOKEN debe ser un token completo, no un valor enmascarado."
            )
        if key == "GITHUB_TOKEN" and len(value) < MIN_GITHUB_TOKEN_LENGTH:
            raise LocalConfigValidationError(
                "El token debe tener al menos 70 caracteres."
            )
        validated[key] = value

    return validated
