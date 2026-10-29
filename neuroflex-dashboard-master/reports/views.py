from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View

from audit.models import AuditLog
from audit.services import get_client_ip, log_event
from clinical_sessions.models import SpecialistSession
from clinical_sessions.services import (
    ExternalSessionServiceUnavailableError,
    get_session_confirmed_by,
)
from dashboard.views import RoleRequiredMixin

from .forms import ReportAdminFilterForm, ReportRequestForm, ReportReviewForm
from .models import ReportRequest
from .services import (
    ACTIVE_REPORT_STATUSES,
    auto_generate_report,
    create_report_request,
    generate_orphan_report,
    generate_report_file,
    get_active_duplicate_queryset,
)


User = get_user_model()

EXPIRED_NEUROFLEX_SESSION_MESSAGE = (
    "Tu sesion con NeuroFlex expiro. Cierra sesion y vuelve a iniciarla."
)


class SpecialistReportListView(RoleRequiredMixin, View):
    required_role = User.Role.SPECIALIST

    def get(self, request, *args, **kwargs):
        reports = ReportRequest.objects.filter(requested_by=request.user)
        return render(
            request,
            "reports/specialist_report_list.html",
            {"reports": reports},
        )


class ReportRequestCreateView(RoleRequiredMixin, View):
    required_role = User.Role.SPECIALIST

    def get(self, request, *args, **kwargs):
        form = ReportRequestForm(initial={"session_id": request.GET.get("session_id", "")})
        return render(
            request,
            "reports/report_request_form.html",
            {"form": form, "next_url": request.GET.get("next", "")},
        )

    def post(self, request, *args, **kwargs):
        form = ReportRequestForm(request.POST)
        if form.is_valid():
            session_id = form.cleaned_data["session_id"]
            sub = request.session.get("cognito_sub")
            id_token = request.session.get("cognito_id_token")

            if not sub or not id_token:
                form.add_error("session_id", EXPIRED_NEUROFLEX_SESSION_MESSAGE)
            else:
                try:
                    api_session = get_session_confirmed_by(sub, id_token, session_id)
                except ExternalSessionServiceUnavailableError:
                    form.add_error(
                        "session_id",
                        "No fue posible validar la sesion con NeuroFlex en este momento. Intenta nuevamente.",
                    )
                else:
                    if api_session is None:
                        form.add_error(
                            "session_id",
                            "No se encontro la sesion para tu cuenta.",
                        )
                        return render(
                            request,
                            "reports/report_request_form.html",
                            {"form": form, "next_url": request.POST.get("next", "")},
                            status=403,
                        )

                    if not api_session.get("metrics"):
                        form.add_error(
                            "session_id",
                            "La sesion aun no tiene metricas disponibles para generar un informe.",
                        )
                    else:
                        duplicate_queryset = get_active_duplicate_queryset(
                            requested_by=request.user,
                            session_id=session_id,
                        )
                        if duplicate_queryset.exists():
                            log_event(
                                actor=request.user,
                                action="report_request_duplicate",
                                resource_type="report_request",
                                resource_id=session_id,
                                result=AuditLog.Result.FAILURE,
                                ip_address=get_client_ip(request),
                                metadata={},
                            )
                            form.add_error(
                                "session_id",
                                "Ya existe una solicitud activa para esta sesion.",
                            )
                        else:
                            patient_info = (
                                api_session.get("patient")
                                or api_session.get("patient_info")
                                or api_session
                            )
                            patient_hand = (
                                patient_info.get("dominant_hand")
                                or patient_info.get("ManoPredominante")
                                or patient_info.get("dominantHand")
                            )
                            patient_age = patient_info.get("age") or patient_info.get("Edad")
                            snapshot = {
                                "session_id": api_session.get("session_id"),
                                "display_code": api_session.get("display_code"),
                                "created_at": api_session.get("created_at"),
                                "vr_user_email": api_session.get("vr_user_email"),
                                "status": api_session.get("status"),
                                "metrics": api_session.get("metrics"),
                                # Keep only inference/display fields; never snapshot patient identifiers.
                                "patient_info": {
                                    key: value
                                    for key, value in (
                                        ("age", patient_age),
                                        ("dominant_hand", patient_hand),
                                    )
                                    if value is not None
                                },
                            }
                            try:
                                report_request = create_report_request(
                                    form=form,
                                    requested_by=request.user,
                                    session_snapshot=snapshot,
                                )
                            except IntegrityError:
                                form.add_error(
                                    "session_id",
                                    "Ya existe una solicitud activa para esta sesion.",
                                )
                            else:
                                log_event(
                                    actor=request.user,
                                    action="report_requested",
                                    resource_type="report_request",
                                    resource_id=report_request.pk,
                                    result=AuditLog.Result.SUCCESS,
                                    ip_address=get_client_ip(request),
                                    metadata={"session_id": report_request.session_id},
                                )
                                if request.user.can_generate_pdf_without_approval:
                                    auto_generate_report(
                                        report_request,
                                        actor=request.user,
                                        ip_address=get_client_ip(request),
                                    )
                                next_url = request.POST.get("next")
                                if next_url:
                                    return redirect(next_url)
                                return redirect("reports:specialist-list")

        return render(
            request,
            "reports/report_request_form.html",
            {"form": form, "next_url": request.POST.get("next", "")},
            status=400,
        )


class AdminReportListView(RoleRequiredMixin, View):
    required_role = User.Role.ADMIN

    def get(self, request, *args, **kwargs):
        reports = ReportRequest.objects.select_related("requested_by", "reviewed_by")
        form = ReportAdminFilterForm(
            request.GET or None,
            specialist_queryset=User.objects.filter(role=User.Role.SPECIALIST).order_by(
                "username"
            ),
        )
        if form.is_valid():
            if form.cleaned_data.get("status"):
                reports = reports.filter(status=form.cleaned_data["status"])
            if form.cleaned_data.get("specialist"):
                reports = reports.filter(requested_by=form.cleaned_data["specialist"])
            if form.cleaned_data.get("requested_at"):
                reports = reports.filter(
                    requested_at__date=form.cleaned_data["requested_at"]
                )
            if form.cleaned_data.get("session_id"):
                reports = reports.filter(
                    session_id__icontains=form.cleaned_data["session_id"].strip()
                )

        return render(
            request,
            "reports/admin_report_list.html",
            {"reports": reports, "filter_form": form},
        )


class ReportApproveView(RoleRequiredMixin, View):
    required_role = User.Role.ADMIN

    def post(self, request, report_id, *args, **kwargs):
        with transaction.atomic():
            report_request = get_object_or_404(
                ReportRequest.objects.select_for_update(),
                pk=report_id,
            )
            if report_request.status != ReportRequest.Status.PENDING:
                return render(
                    request,
                    "errors/403.html",
                    {"message": "Solo se pueden aprobar solicitudes pendientes."},
                    status=403,
                )

            report_request.status = ReportRequest.Status.APPROVED
            report_request.reviewed_by = request.user
            report_request.reviewed_at = timezone.now()
            report_request.rejection_reason = ""
            report_request.save(
                update_fields=[
                    "status",
                    "reviewed_by",
                    "reviewed_at",
                    "rejection_reason",
                ]
            )
        log_event(
            actor=request.user,
            action="report_approved",
            resource_type="report_request",
            resource_id=report_request.pk,
            result=AuditLog.Result.SUCCESS,
            ip_address=get_client_ip(request),
            metadata={"session_id": report_request.session_id},
        )
        generate_report_file(
            report_request,
            actor=request.user,
            ip_address=get_client_ip(request),
        )
        return redirect("reports:admin-list")


class ReportRejectView(RoleRequiredMixin, View):
    required_role = User.Role.ADMIN

    def post(self, request, report_id, *args, **kwargs):
        form = ReportReviewForm(request.POST)
        with transaction.atomic():
            report_request = get_object_or_404(
                ReportRequest.objects.select_for_update(),
                pk=report_id,
            )

            if report_request.status != ReportRequest.Status.PENDING:
                return render(
                    request,
                    "errors/403.html",
                    {"message": "Solo se pueden rechazar solicitudes pendientes."},
                    status=403,
                )

            if not form.is_valid() or not form.cleaned_data["rejection_reason"]:
                reports = ReportRequest.objects.select_related(
                    "requested_by", "reviewed_by"
                )
                form.add_error(
                    "rejection_reason",
                    "Debes ingresar un motivo para rechazar la solicitud.",
                )
                filter_form = ReportAdminFilterForm(
                    request.GET or None,
                    specialist_queryset=User.objects.filter(
                        role=User.Role.SPECIALIST
                    ).order_by("username"),
                )
                return render(
                    request,
                    "reports/admin_report_list.html",
                    {
                        "reports": reports,
                        "filter_form": filter_form,
                        "review_form_errors": form.errors,
                        "active_report_id": report_id,
                    },
                    status=400,
                )

            report_request.status = ReportRequest.Status.REJECTED
            report_request.reviewed_by = request.user
            report_request.reviewed_at = timezone.now()
            report_request.rejection_reason = form.cleaned_data["rejection_reason"]
            report_request.save(
                update_fields=[
                    "status",
                    "reviewed_by",
                    "reviewed_at",
                    "rejection_reason",
                ]
            )
        log_event(
            actor=request.user,
            action="report_rejected",
            resource_type="report_request",
            resource_id=report_request.pk,
            result=AuditLog.Result.SUCCESS,
            ip_address=get_client_ip(request),
            metadata={"session_id": report_request.session_id},
        )
        return redirect("reports:admin-list")


class ReportDownloadView(RoleRequiredMixin, View):
    required_role = User.Role.SPECIALIST

    def get(self, request, report_id, *args, **kwargs):
        report_request = get_object_or_404(
            ReportRequest,
            pk=report_id,
            requested_by=request.user,
        )
        if report_request.status != ReportRequest.Status.GENERATED or not report_request.file:
            raise Http404("Report file is not available.")

        log_event(
            actor=request.user,
            action="report_downloaded",
            resource_type="report_request",
            resource_id=report_request.pk,
            result=AuditLog.Result.SUCCESS,
            ip_address=get_client_ip(request),
            metadata={"session_id": report_request.session_id},
        )
        return FileResponse(
            report_request.file.open("rb"),
            as_attachment=True,
            filename=report_request.file.name.split("/")[-1],
        )


class AdminReportDownloadView(RoleRequiredMixin, View):
    """Lets an admin download a report whose requesting specialist was deleted.

    Scoped to requested_by__isnull=True so this doesn't widen access to
    reports that still belong to an active specialist.
    """

    required_role = User.Role.ADMIN

    def get(self, request, report_id, *args, **kwargs):
        report_request = get_object_or_404(
            ReportRequest,
            pk=report_id,
            requested_by__isnull=True,
        )
        if report_request.status != ReportRequest.Status.GENERATED or not report_request.file:
            raise Http404("Report file is not available.")

        log_event(
            actor=request.user,
            action="unassociated_report_downloaded",
            resource_type="report_request",
            resource_id=report_request.pk,
            result=AuditLog.Result.SUCCESS,
            ip_address=get_client_ip(request),
            metadata={"session_id": report_request.session_id},
        )
        return FileResponse(
            report_request.file.open("rb"),
            as_attachment=True,
            filename=report_request.file.name.split("/")[-1],
        )


class AdminGenerateOrphanReportView(RoleRequiredMixin, View):
    """Lets an admin generate the PDF of an orphaned session that has no report.

    Only works for sessions whose specialist was deleted (specialist NULL) and
    that have locally cached metrics (see cache_session_metrics). Skips human
    approval: it is the admin exception for sessions nobody owns anymore.
    """

    required_role = User.Role.ADMIN

    def post(self, request, *args, **kwargs):
        session_id = request.POST.get("session_id", "")
        redirect_url = redirect("clinical_sessions:unassociated-sessions")

        session = SpecialistSession.objects.filter(
            session_id=session_id, specialist__isnull=True
        ).first()
        if session is None:
            messages.error(
                request,
                "La sesion no existe o aun tiene un especialista asociado.",
            )
            return redirect_url

        if not session.metrics:
            messages.error(
                request,
                "No hay metricas locales para esta sesion; no es posible generar el informe.",
            )
            return redirect_url

        if ReportRequest.objects.filter(
            session_id=session_id, status__in=ACTIVE_REPORT_STATUSES
        ).exists():
            messages.error(
                request,
                "Ya existe un informe activo para esta sesion.",
            )
            return redirect_url

        report_request = generate_orphan_report(
            session=session,
            admin_user=request.user,
            ip_address=get_client_ip(request),
        )
        if report_request.status == ReportRequest.Status.GENERATED:
            messages.success(request, "Informe generado correctamente.")
        else:
            messages.error(
                request,
                "No fue posible generar el informe. Intenta nuevamente.",
            )
        return redirect_url
