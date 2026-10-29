import csv

from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views import View

from dashboard.views import RoleRequiredMixin

from .forms import AuditLogFilterForm
from .models import AuditLog
from .pdf_builder import build_audit_log_pdf
from .services import get_client_ip, log_event


class AuditLogBaseView(RoleRequiredMixin, View):
    required_role = "ADMIN"

    def serialize_filter_value(self, value):
        if hasattr(value, "pk"):
            return str(value.pk)
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return value

    def get_filtered_queryset(self, request):
        queryset = AuditLog.objects.select_related("actor")
        form = AuditLogFilterForm(request.GET or None)

        if form.is_valid():
            actor = form.cleaned_data.get("actor")
            action = form.cleaned_data.get("action")
            result = form.cleaned_data.get("result")
            start_date = form.cleaned_data.get("start_date")
            end_date = form.cleaned_data.get("end_date")

            if actor:
                queryset = queryset.filter(actor=actor)
            if action:
                queryset = queryset.filter(action__icontains=action)
            if result:
                queryset = queryset.filter(result=result)
            if start_date:
                queryset = queryset.filter(created_at__date__gte=start_date)
            if end_date:
                queryset = queryset.filter(created_at__date__lte=end_date)

        return form, queryset

    def get_applied_filters(self, form):
        if not form.is_valid():
            return {}
        return {
            key: self.serialize_filter_value(value)
            for key, value in form.cleaned_data.items()
            if value not in (None, "", [])
        }


class AuditLogListView(AuditLogBaseView):
    def get(self, request, *args, **kwargs):
        form, logs = self.get_filtered_queryset(request)
        return render(
            request,
            "audit/log_list.html",
            {"form": form, "logs": logs},
        )


class AuditLogExportView(AuditLogBaseView):
    def get(self, request, *args, **kwargs):
        form, logs = self.get_filtered_queryset(request)
        response = HttpResponse(content_type="text/csv")
        timestamp = timezone.now().strftime("%Y%m%d%H%M%S")
        response["Content-Disposition"] = (
            f'attachment; filename="audit-logs-{timestamp}.csv"'
        )

        writer = csv.writer(response)
        writer.writerow(
            [
                "created_at",
                "actor",
                "action",
                "resource_type",
                "resource_id",
                "result",
                "ip_address",
                "metadata",
            ]
        )
        for log in logs:
            writer.writerow(
                [
                    log.created_at.isoformat(),
                    log.actor.username if log.actor else "",
                    log.action,
                    log.resource_type,
                    log.resource_id,
                    log.result,
                    log.ip_address or "",
                    log.metadata,
                ]
            )

        applied_filters = self.get_applied_filters(form)

        log_event(
            actor=request.user,
            action="audit_exported",
            resource_type="audit_log",
            resource_id="filtered_export",
            result=AuditLog.Result.SUCCESS,
            ip_address=get_client_ip(request),
            metadata={"filters": applied_filters, "exported_rows": logs.count()},
        )
        return response


class AuditLogPdfExportView(AuditLogBaseView):
    def get(self, request, *args, **kwargs):
        form, logs = self.get_filtered_queryset(request)
        applied_filters = self.get_applied_filters(form)

        pdf_bytes = build_audit_log_pdf(logs, applied_filters)

        timestamp = timezone.now().strftime("%Y%m%d%H%M%S")
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = (
            f'attachment; filename="auditoria-{timestamp}.pdf"'
        )

        log_event(
            actor=request.user,
            action="audit_exported_pdf",
            resource_type="audit_log",
            resource_id="filtered_export",
            result=AuditLog.Result.SUCCESS,
            ip_address=get_client_ip(request),
            metadata={"filters": applied_filters, "exported_rows": logs.count()},
        )
        return response
