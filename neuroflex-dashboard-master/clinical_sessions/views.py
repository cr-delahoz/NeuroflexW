from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.dateparse import parse_datetime
from django.views import View

from dashboard.views import RoleRequiredMixin

from audit.models import AuditLog
from audit.services import get_client_ip, log_event
from ml.services import predict_cognitive_result
from reports.services import (
    build_generated_report_map_for_orphaned_sessions,
    build_report_status_map_for_user,
)

from .forms import DisplayCodeForm, SessionSearchForm
from .models import SpecialistSession
from .services import (
    ExternalSessionClientError,
    ExternalSessionServiceUnavailableError,
    SessionAlreadyAssociatedError,
    cache_session_metrics,
    confirm_and_associate_session,
    get_session_confirmed_by,
    list_sessions_confirmed_by,
)

User = get_user_model()

DEFAULT_REPORT_STATUS = {
    "code": "NOT_REQUESTED",
    "label": "Sin solicitar",
    "tone": "default",
    "action_label": "Solicitar informe",
    "request_id": None,
    "rejection_reason": "",
}

EXPIRED_NEUROFLEX_SESSION_MESSAGE = (
    "Tu sesion con NeuroFlex expiro. Cierra sesion y vuelve a iniciarla."
)


def _build_sorted_metrics_items(metrics):
    """Build a label/value list from a raw API metrics dict, sorted by key.

    Floats are rounded to 2 decimals for display; other value types are kept
    as-is. Sorting/rounding happens here (not in the template) per project
    convention of keeping templates free of logic.

    Model-specific transformations are handled by the ML feature builder;
    this helper only formats values for display.
    """
    items = []
    for key in sorted(metrics):
        value = metrics[key]
        if isinstance(value, float):
            value = round(value, 2)
        items.append({"label": key, "value": value})
    return items


class SessionListView(RoleRequiredMixin, View):
    required_role = "SPECIALIST"

    def get(self, request, *args, **kwargs):
        sub = request.session.get("cognito_sub")
        id_token = request.session.get("cognito_id_token")
        form = SessionSearchForm(request.GET or None)
        selected_status = request.GET.get("status", "")
        query = ""
        errors = []
        active_sessions = []
        completed_sessions = []

        if not sub or not id_token:
            errors.append({"message": EXPIRED_NEUROFLEX_SESSION_MESSAGE})
        else:
            try:
                all_sessions = list_sessions_confirmed_by(sub, id_token)
            except ExternalSessionServiceUnavailableError as exc:
                errors.append({"message": str(exc)})
                all_sessions = []

            for session in all_sessions:
                session["created_at_parsed"] = parse_datetime(session.get("created_at") or "")

            active_sessions = [s for s in all_sessions if s.get("status") == "confirmed"]
            completed_sessions = [s for s in all_sessions if s.get("status") == "completed"]

            for session in completed_sessions:
                cache_session_metrics(session["session_id"], session.get("metrics") or {})

        if form.is_valid():
            query = form.cleaned_data.get("session_id", "").strip()
            if query:
                completed_sessions = [
                    session
                    for session in completed_sessions
                    if query.lower() in session["session_id"].lower()
                ]

        if selected_status == "confirmed":
            completed_sessions = []
        elif selected_status == "completed":
            active_sessions = []

        report_status_map = build_report_status_map_for_user(
            request.user,
            [session["session_id"] for session in completed_sessions],
        )
        for session in completed_sessions:
            session["report_status"] = report_status_map.get(
                session["session_id"], DEFAULT_REPORT_STATUS
            )
            session["has_metrics"] = bool(session.get("metrics"))

        paginator = Paginator(completed_sessions, 10)
        page_obj = paginator.get_page(request.GET.get("page"))

        log_event(
            actor=request.user,
            action="session_list_viewed",
            resource_type="clinical_session",
            resource_id="list",
            result=AuditLog.Result.SUCCESS,
            ip_address=get_client_ip(request),
            metadata={
                "active_sessions": len(active_sessions),
                "completed_sessions": len(completed_sessions),
            },
        )
        return render(
            request,
            "clinical_sessions/session_list.html",
            {
                "form": form,
                "active_sessions": active_sessions,
                "page_obj": page_obj,
                "completed_sessions": page_obj.object_list,
                "total_completed_sessions": len(completed_sessions),
                "selected_status": selected_status,
                "errors": errors,
                "query": query,
            },
        )


class SessionDetailView(RoleRequiredMixin, View):
    required_role = "SPECIALIST"

    def get(self, request, session_id, *args, **kwargs):
        sub = request.session.get("cognito_sub")
        id_token = request.session.get("cognito_id_token")

        if not sub or not id_token:
            return render(
                request,
                "errors/404.html",
                {"message": EXPIRED_NEUROFLEX_SESSION_MESSAGE},
                status=404,
            )

        try:
            session = get_session_confirmed_by(sub, id_token, session_id)
        except ExternalSessionServiceUnavailableError as exc:
            return render(
                request,
                "clinical_sessions/session_detail.html",
                {"loading_error": str(exc)},
                status=502,
            )

        if session is None:
            return render(
                request,
                "errors/404.html",
                {
                    "message": f"No se encontro la sesion '{session_id}' para este especialista."
                },
                status=404,
            )

        session["created_at_parsed"] = parse_datetime(session.get("created_at") or "")
        session["report_status"] = build_report_status_map_for_user(
            request.user,
            [session_id],
        ).get(session_id, DEFAULT_REPORT_STATUS)

        metrics = session.get("metrics") or {}
        if session.get("status") == "completed" and metrics:
            patient_info = (
                session.get("patient") or session.get("patient_info") or session
            )
            cached_metrics = dict(metrics)
            if (
                patient_info.get("dominant_hand") is not None
                and cached_metrics.get("dominant_hand") is None
                and cached_metrics.get("ManoPredominante") is None
            ):
                cached_metrics["dominant_hand"] = patient_info["dominant_hand"]
            cache_session_metrics(session_id, cached_metrics)
        metrics_items = _build_sorted_metrics_items(metrics) if metrics else []
        cognitive_result = predict_cognitive_result(
            metrics,
            patient_info=(
                session.get("patient") or session.get("patient_info") or session
            ),
        )

        log_event(
            actor=request.user,
            action="inference_executed",
            resource_type="clinical_session",
            resource_id=session_id,
            result=(
                AuditLog.Result.SUCCESS
                if cognitive_result.get("available")
                else AuditLog.Result.FAILURE
            ),
            ip_address=get_client_ip(request),
            metadata={"available": bool(cognitive_result.get("available"))},
        )

        log_event(
            actor=request.user,
            action="session_detail_viewed",
            resource_type="clinical_session",
            resource_id=session_id,
            result=AuditLog.Result.SUCCESS,
            ip_address=get_client_ip(request),
            metadata={},
        )

        return render(
            request,
            "clinical_sessions/session_detail.html",
            {
                "session": session,
                "metrics_items": metrics_items,
                "cognitive_result": cognitive_result,
            },
        )


class SessionConfirmView(RoleRequiredMixin, View):
    required_role = "SPECIALIST"

    def get(self, request, *args, **kwargs):
        form = DisplayCodeForm()
        return render(request, "clinical_sessions/session_confirm.html", {"form": form})

    def post(self, request, *args, **kwargs):
        form = DisplayCodeForm(request.POST)
        id_token = request.session.get("cognito_id_token")

        if form.is_valid() and not id_token:
            form.add_error(
                None,
                "Tu sesion con NeuroFlex expiro. Cierra sesion y vuelve a iniciarla.",
            )

        if form.is_valid() and id_token:
            display_code = form.cleaned_data["display_code"]
            try:
                session = confirm_and_associate_session(
                    request.user, display_code, id_token
                )
            except SessionAlreadyAssociatedError:
                form.add_error(
                    "display_code",
                    "Esta sesion ya fue asociada a otro especialista.",
                )
            except ExternalSessionClientError as exc:
                form.add_error("display_code", str(exc))
            else:
                log_event(
                    actor=request.user,
                    action="session_confirmed",
                    resource_type="clinical_session",
                    resource_id=session.session_id,
                    result=AuditLog.Result.SUCCESS,
                    ip_address=get_client_ip(request),
                    metadata={"status": session.status},
                )
                return redirect(reverse("clinical_sessions:session-list"))

        return render(
            request,
            "clinical_sessions/session_confirm.html",
            {"form": form},
            status=400,
        )


class ActiveSessionsView(RoleRequiredMixin, View):
    required_role = "SPECIALIST"

    def get(self, request, *args, **kwargs):
        sub = request.session.get("cognito_sub")
        id_token = request.session.get("cognito_id_token")

        if not sub or not id_token:
            return JsonResponse({"active_sessions": []}, status=503)

        try:
            all_sessions = list_sessions_confirmed_by(sub, id_token)
        except ExternalSessionServiceUnavailableError:
            return JsonResponse({"active_sessions": []}, status=503)

        return JsonResponse(
            {
                "active_sessions": [
                    {
                        "session_id": session.get("session_id"),
                        "status": session.get("status"),
                        "display_code": session.get("display_code"),
                        "created_at": session.get("created_at"),
                        "vr_user_email": session.get("vr_user_email"),
                    }
                    for session in all_sessions
                    if session.get("status") == "confirmed"
                ]
            }
        )


class UnassociatedSessionsView(RoleRequiredMixin, View):
    """Sessions whose owning specialist account was deleted.

    SpecialistSession.specialist and ReportRequest.requested_by are
    SET_NULL on delete so this data survives instead of cascading away; this
    view is the only place an admin can see and download it.
    """

    required_role = User.Role.ADMIN

    def get(self, request, *args, **kwargs):
        sessions = list(
            SpecialistSession.objects.filter(specialist__isnull=True).order_by(
                "-confirmed_at"
            )
        )
        report_map = build_generated_report_map_for_orphaned_sessions(
            [session.session_id for session in sessions]
        )
        for session in sessions:
            session.report = report_map.get(session.session_id)
            session.has_metrics = bool(session.metrics)

        log_event(
            actor=request.user,
            action="unassociated_sessions_viewed",
            resource_type="clinical_session",
            resource_id="list",
            result=AuditLog.Result.SUCCESS,
            ip_address=get_client_ip(request),
            metadata={"orphaned_sessions": len(sessions)},
        )

        return render(
            request,
            "clinical_sessions/unassociated_sessions.html",
            {"sessions": sessions},
        )
