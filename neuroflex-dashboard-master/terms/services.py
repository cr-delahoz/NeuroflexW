"""Sync the local TermsVersion mirror from the external terms endpoints."""

from __future__ import annotations

from uuid import uuid4

from django.db import models, transaction
from django.utils import timezone

from integrations.services.neuroflex_api_client import (
    NeuroflexApiClient,
    NeuroflexApiClientError,
    NeuroflexApiResponseError,
)

from .models import TermsVersion


class TermsSyncError(Exception):
    """Base exception for terms catalog synchronization errors."""


def sync_terms_versions(id_token, language=None, *, api_client=None):
    """Upsert the current TermsVersion from the external terms endpoint.

    The endpoint returns a single object describing the current version,
    which is always considered published. Returns a summary dict:
    {"created": N, "updated": N, "unchanged": N}.
    """
    client = api_client or NeuroflexApiClient()
    params = {"language": language} if language else None

    try:
        response = client.get("/terms/current", token=id_token, params=params)
    except NeuroflexApiClientError as exc:
        raise TermsSyncError(
            "Could not reach the NeuroFlex API to sync the current terms version."
        ) from exc

    if not isinstance(response, dict) or not response.get("version_id"):
        raise TermsSyncError(
            "Unexpected payload from the NeuroFlex API terms endpoint."
        )

    version_id = response["version_id"]
    entry_language = response.get("language") or "es"
    content_hash = response.get("content_hash", "")
    summary = {"created": 0, "updated": 0, "unchanged": 0}

    with transaction.atomic():
        existing = TermsVersion.objects.filter(
            version_id=version_id, language=entry_language
        ).first()

        if existing is None:
            TermsVersion.objects.create(
                version_id=version_id,
                language=entry_language,
                title=response.get("title", ""),
                content=response.get("content", ""),
                content_hash=content_hash,
                published=True,
            )
            summary["created"] += 1
        elif existing.content_hash != content_hash:
            existing.title = response.get("title", existing.title)
            existing.content = response.get("content", existing.content)
            existing.content_hash = content_hash
            existing.published = True
            existing.save(
                update_fields=["title", "content", "content_hash", "published"]
            )
            summary["updated"] += 1
        else:
            summary["unchanged"] += 1

    return summary


class TermsVersionConflictError(TermsSyncError):
    """A terms version with the same version_id already exists remotely."""


class TermsVersionNotFoundError(TermsSyncError):
    """The requested terms version no longer exists remotely."""


class TermsPublicationForbiddenError(TermsSyncError):
    """The API refuses to leave a language without a current terms version."""


def list_terms_versions(token, *, api_client=None):
    """Return the remote terms history (metadata only, no content)."""
    client = api_client or NeuroflexApiClient()
    try:
        response = client.get("/terms/versions", token=token)
    except NeuroflexApiClientError as exc:
        raise TermsSyncError(
            "Could not reach the NeuroFlex API to list terms versions."
        ) from exc
    versions = response.get("versions") if isinstance(response, dict) else None
    if not isinstance(versions, list):
        raise TermsSyncError(
            "Unexpected payload from the NeuroFlex API terms history endpoint."
        )
    return versions


def fetch_terms_version(token, version_id, language="es", *, api_client=None):
    """Return the full remote version (including content) by id and language."""
    client = api_client or NeuroflexApiClient()
    try:
        response = client.get(
            f"/terms/versions/{version_id}", token=token, params={"language": language}
        )
    except NeuroflexApiClientError as exc:
        raise TermsSyncError(
            "Could not reach the NeuroFlex API to fetch the terms version."
        ) from exc
    if not isinstance(response, dict) or not response.get("version_id"):
        raise TermsSyncError(
            "Unexpected payload from the NeuroFlex API terms endpoint."
        )
    return response


def create_terms_version(
    token, version_id, title, content, language="es", published=True, *, api_client=None
):
    """Publish a new terms version; raises TermsVersionConflictError on 409."""
    client = api_client or NeuroflexApiClient()
    try:
        return client.post(
            "/terms/versions",
            token=token,
            json_body={
                "version_id": version_id,
                "language": language,
                "title": title,
                "content": content,
                "published": published,
            },
        )
    except NeuroflexApiResponseError as exc:
        if exc.status_code == 409:
            raise TermsVersionConflictError(
                "A terms version with this identifier already exists."
            ) from exc
        raise TermsSyncError(
            "The NeuroFlex API rejected the new terms version."
        ) from exc
    except NeuroflexApiClientError as exc:
        raise TermsSyncError(
            "Could not reach the NeuroFlex API to publish the terms version."
        ) from exc


def set_terms_publication(
    token, version_id, language="es", published=True, *, api_client=None
):
    """Change which terms version is the current one for a language.

    Remote endpoint PATCH /terms/versions/{version_id}/publication with
    admin-only access enforced by the Lambda. Raises
    TermsVersionNotFoundError when the version no longer exists remotely
    (404) and TermsSyncError for any other API failure.
    """
    client = api_client or NeuroflexApiClient()
    try:
        return client.patch(
            f"/terms/versions/{version_id}/publication",
            token=token,
            json_body={"language": language, "published": published},
        )
    except NeuroflexApiResponseError as exc:
        if exc.status_code == 404:
            raise TermsVersionNotFoundError(
                "The requested terms version no longer exists remotely."
            ) from exc
        if exc.status_code == 403:
            raise TermsPublicationForbiddenError(
                "The API refuses to leave the language without a current version."
            ) from exc
        raise TermsSyncError(
            "The NeuroFlex API rejected the publication change."
        ) from exc
    except NeuroflexApiClientError as exc:
        raise TermsSyncError(
            "Could not reach the NeuroFlex API to change the publication."
        ) from exc


def generate_terms_version_id():
    """Deterministic timestamp id, e.g. tc-20261001-143502."""
    now = timezone.now()
    return f"tc-{now.strftime('%Y%m%d')}-{now.strftime('%H%M%S')}"


def generate_terms_version_id_with_suffix():
    """Timestamp id plus a short random suffix to survive collisions."""
    return f"{generate_terms_version_id()}-{uuid4().hex[:4]}"


def sync_terms_history(token, *, api_client=None):
    """Mirror the full remote terms history into the local TermsVersion table.

    Content is not included in the history endpoint: rows are stored with
    empty content and cached later by the detail view. Rows removed remotely
    are deleted locally. Returns {"created", "updated", "unchanged"}.
    """
    versions = list_terms_versions(token, api_client=api_client)
    required = {
        "version_id",
        "title",
        "content_hash",
        "created_at",
        "published",
    }
    for entry in versions:
        if (
            not isinstance(entry, dict)
            or not required.issubset(entry)
            or not entry["version_id"]
        ):
            raise TermsSyncError(
                "Remote terms history payload is incomplete or invalid."
            )

    remote_keys = {
        (entry["version_id"], entry.get("language") or "es") for entry in versions
    }
    remote_pairs = list(remote_keys)
    summary = {"created": 0, "updated": 0, "unchanged": 0}
    with transaction.atomic():
        if remote_pairs:
            keep_q = models.Q()
            for version_id, _language in remote_pairs:
                keep_q |= models.Q(version_id=version_id)
            TermsVersion.objects.exclude(keep_q).delete()
        else:
            TermsVersion.objects.all().delete()
        for entry in versions:
            version_id = entry["version_id"]
            language = entry.get("language") or "es"
            published = str(entry.get("published", "false")).lower() == "true"
            content_hash = entry.get("content_hash", "")
            existing = TermsVersion.objects.filter(
                version_id=version_id, language=language
            ).first()
            if existing is None:
                TermsVersion.objects.create(
                    version_id=version_id,
                    language=language,
                    title=entry.get("title", ""),
                    content="",
                    content_hash=content_hash,
                    published=published,
                )
                summary["created"] += 1
            elif existing.content_hash != content_hash or existing.published != published:
                existing.title = entry.get("title", existing.title)
                existing.content_hash = content_hash
                existing.published = published
                existing.content = ""
                existing.save(
                    update_fields=["title", "content_hash", "published", "content"]
                )
                summary["updated"] += 1
            else:
                summary["unchanged"] += 1
    return summary
