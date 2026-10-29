from accounts.models import CustomUser
from audit.models import AuditLog
from clinical_sessions.models import SpecialistSession
from reports.models import ReportRequest
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.shortcuts import redirect, render
from django.views import View


class RoleRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    required_role = None

    def test_func(self):
        user = self.request.user
        return user.is_authenticated and user.is_active and user.role == self.required_role

    def handle_no_permission(self):
        # Keep this import local: audit views also depend on this mixin.
        from audit.models import AuditLog
        from audit.services import get_client_ip, log_event

        log_event(
            actor=self.request.user if self.request.user.is_authenticated else None,
            action="authorization_denied",
            resource_type="web_view",
            resource_id="",
            result=AuditLog.Result.FAILURE,
            ip_address=get_client_ip(self.request),
            metadata={"required_role": self.required_role or ""},
        )
        if self.request.user.is_authenticated:
            return render(self.request, "errors/403.html", status=403)

        return LoginRequiredMixin.handle_no_permission(self)


class HomeRedirectView(View):
    def get(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("accounts:login")

        if request.user.role == request.user.Role.ADMIN:
            return redirect("dashboard:admin")

        return redirect("dashboard:specialist")


class AdminDashboardView(RoleRequiredMixin, View):
    required_role = CustomUser.Role.ADMIN

    def get(self, request, *args, **kwargs):
        context = {
            "active_users_count": CustomUser.objects.filter(is_active=True).count(),
            "unassociated_sessions_count": SpecialistSession.objects.filter(
                specialist__isnull=True
            ).count(),
            "pending_reports_count": ReportRequest.objects.filter(
                status=ReportRequest.Status.PENDING
            ).count(),
            "generated_reports_count": ReportRequest.objects.filter(
                status=ReportRequest.Status.GENERATED
            ).count(),
            "recent_logs": AuditLog.objects.select_related("actor")[:5],
        }
        return render(request, "dashboard/admin_dashboard.html", context)


class SpecialistDashboardView(RoleRequiredMixin, View):
    required_role = CustomUser.Role.SPECIALIST

    def get(self, request, *args, **kwargs):
        return render(request, "dashboard/specialist_dashboard.html")
