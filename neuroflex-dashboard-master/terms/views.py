from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from audit.models import AuditLog
from audit.services import get_client_ip, log_event
from dashboard.views import RoleRequiredMixin

from .forms import TermsVersionCreateForm
from .models import TermsVersion
from .services import (
    TermsPublicationForbiddenError,
    TermsSyncError,
    TermsVersionConflictError,
    TermsVersionNotFoundError,
    create_terms_version,
    fetch_terms_version,
    generate_terms_version_id,
    generate_terms_version_id_with_suffix,
    set_terms_publication,
    sync_terms_history,
)


class TermsBaseView(RoleRequiredMixin, View):
    required_role = "ADMIN"

    def _token(self):
        return self.request.session.get("cognito_id_token")


class TermsListView(TermsBaseView):
    def get(self, request, *args, **kwargs):
        token = self._token()
        if token:
            try:
                summary = sync_terms_history(token)
            except TermsSyncError:
                messages.error(
                    request,
                    "No fue posible sincronizar el historial de terminos. Mostrando el catalogo local.",
                )
                log_event(
                    actor=request.user,
                    action="terms_catalog_synced",
                    resource_type="terms",
                    resource_id="",
                    result=AuditLog.Result.FAILURE,
                    ip_address=get_client_ip(request),
                )
            else:
                log_event(
                    actor=request.user,
                    action="terms_catalog_synced",
                    resource_type="terms",
                    resource_id="",
                    result=AuditLog.Result.SUCCESS,
                    ip_address=get_client_ip(request),
                    metadata=summary,
                )
        versions = TermsVersion.objects.order_by("-created_at")
        return render(request, "terms/terms_list.html", {"versions": versions})


class TermsVersionDetailView(TermsBaseView):
    def get(self, request, version_id, language, *args, **kwargs):
        version = get_object_or_404(TermsVersion, version_id=version_id, language=language)
        if version.content == "":
            token = self._token()
            if token:
                try:
                    remote = fetch_terms_version(token, version.version_id, version.language)
                except TermsSyncError:
                    messages.error(
                        request,
                        "No fue posible cargar el contenido completo de esta version.",
                    )
                else:
                    version.title = remote.get("title", version.title)
                    version.content = remote.get("content", "") or version.content
                    version.content_hash = remote.get("content_hash", version.content_hash)
                    version.save(update_fields=["title", "content", "content_hash"])

        log_event(
            actor=request.user,
            action="terms_viewed",
            resource_type="terms",
            resource_id=version.version_id,
            result=AuditLog.Result.SUCCESS,
            ip_address=get_client_ip(request),
            metadata={"language": version.language},
        )
        return render(request, "terms/terms_detail.html", {"version": version})


class TermsVersionCreateView(TermsBaseView):
    def get(self, request, *args, **kwargs):
        return render(
            request, "terms/terms_create.html", {"form": TermsVersionCreateForm()}
        )

    def post(self, request, *args, **kwargs):
        form = TermsVersionCreateForm(request.POST, request.FILES)
        if not form.is_valid():
            return render(
                request, "terms/terms_create.html", {"form": form}, status=200
            )

        token = self._token()
        title = form.cleaned_data["title"]
        language = form.cleaned_data["language"]
        published = form.cleaned_data["published"]
        content = form.cleaned_data["content"]

        for attempt in range(3):
            version_id = (
                generate_terms_version_id()
                if attempt == 0
                else generate_terms_version_id_with_suffix()
            )
            try:
                remote = create_terms_version(
                    token, version_id, title, content, language, published
                )
            except TermsVersionConflictError:
                continue
            except TermsSyncError:
                messages.error(
                    request,
                    "No fue posible publicar la nueva version de terminos en este momento.",
                )
                return render(
                    request, "terms/terms_create.html", {"form": form}, status=200
                )
            break
        else:
            form.add_error(
                None,
                "No fue posible generar un identificador unico para la version. Intenta nuevamente.",
            )
            return render(request, "terms/terms_create.html", {"form": form}, status=200)

        content_hash = remote.get("content_hash", "")
        version_id = remote.get("version_id") or version_id
        TermsVersion.objects.update_or_create(
            version_id=version_id,
            language=language,
            defaults={
                "title": title,
                "content": content,
                "content_hash": content_hash,
                "published": published,
            },
        )
        log_event(
            actor=request.user,
            action="terms_version_created",
            resource_type="terms",
            resource_id=version_id,
            result=AuditLog.Result.SUCCESS,
            ip_address=get_client_ip(request),
            metadata={
                "version_id": version_id,
                "language": language,
                "published": published,
                "content_length": len(content),
            },
        )
        messages.success(
            request, f"Version {version_id} publicada y vigente en el sistema."
        )
        return redirect("terms:terms-list")


class TermsSetCurrentView(TermsBaseView):
    """Change the publication state of a terms version for its language.

    POSTed `published` accepts "true"/"false": true makes the version the
    current one (the remote API unpublishes the previous current), false
    unpublishes it. The remote API refuses (403) to leave a language
    without a current version; that protection is authoritative.
    """

    def post(self, request, version_id, language, *args, **kwargs):
        published = request.POST.get("published", "true").strip().lower() == "true"
        token = self._token()
        try:
            set_terms_publication(token, version_id, language, published=published)
        except TermsVersionNotFoundError:
            messages.error(request, "La version indicada ya no existe en la API.")
            return redirect("terms:terms-list")
        except TermsPublicationForbiddenError:
            messages.error(
                request,
                "No se puede quitar la vigencia: debe existir siempre una version vigente.",
            )
            return redirect("terms:terms-list")
        except TermsSyncError:
            messages.error(
                request, "No fue posible cambiar la vigencia en este momento."
            )
            log_event(
                actor=request.user,
                action="terms_publication_changed",
                resource_type="terms",
                resource_id=version_id,
                result=AuditLog.Result.FAILURE,
                ip_address=get_client_ip(request),
                metadata={"version_id": version_id, "language": language, "published": published},
            )
            return redirect("terms:terms-list")

        with transaction.atomic():
            if published:
                TermsVersion.objects.filter(
                    language=language, published=True
                ).exclude(version_id=version_id).update(published=False)
            TermsVersion.objects.filter(
                version_id=version_id, language=language
            ).update(published=published)

        log_event(
            actor=request.user,
            action="terms_publication_changed",
            resource_type="terms",
            resource_id=version_id,
            result=AuditLog.Result.SUCCESS,
            ip_address=get_client_ip(request),
            metadata={"version_id": version_id, "language": language, "published": published},
        )
        if published:
            messages.success(request, f"La version {version_id} ahora es la vigente.")
        else:
            messages.success(request, f"La version {version_id} ya no es vigente.")
        return redirect("terms:terms-list")
