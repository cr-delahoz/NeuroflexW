from offline_mode.models import OfflineTermsAcceptance
from terms.models import TermsVersion


def current_terms():
    return TermsVersion.objects.filter(published=True).order_by("-pk").first()


def accept_terms(*, device, version_id, content_hash, application_version):
    terms = TermsVersion.objects.filter(
        version_id=version_id, published=True
    ).first()
    if terms is None or terms.content_hash != content_hash:
        return None
    return OfflineTermsAcceptance.objects.create(
        device=device,
        terms_version_id=version_id,
        content_hash=content_hash,
        application_version=application_version or "",
    )
