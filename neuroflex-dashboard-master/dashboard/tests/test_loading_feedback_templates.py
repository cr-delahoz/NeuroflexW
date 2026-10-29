from pathlib import Path

from django.template import Context, Template
from django.test import SimpleTestCase
from django.urls import reverse


ROOT = Path(__file__).resolve().parents[2]


class LoadingFeedbackTemplateTest(SimpleTestCase):
    def test_spinner_has_stable_accessibility_markup_and_size(self):
        html = Template(
            '{% include "components/loading_spinner.html" with size="sm" %}'
        ).render(Context())

        self.assertIn('data-loading-spinner="true"', html)
        self.assertIn('class="h-4 w-4 animate-spin text-current"', html)
        self.assertIn('aria-hidden="true"', html)

    def test_button_renders_spinner_only_when_loading_is_true(self):
        loading_html = Template(
            '{% include "components/button.html" with label="Guardar" loading=True %}'
        ).render(Context())
        idle_html = Template(
            '{% include "components/button.html" with label="Guardar" %}'
        ).render(Context())

        self.assertIn('data-loading-spinner="true"', loading_html)
        self.assertIn('disabled', loading_html)
        self.assertNotIn('data-loading-spinner="true"', idle_html)

    def test_base_loads_ui_feedback_after_page_content(self):
        html = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")

        self.assertIn("{% static 'js/ui-feedback.js' %}", html)
        self.assertLess(html.index("{% block content %}"), html.index("ui-feedback.js"))

    def test_pagination_exposes_the_shared_loading_hook(self):
        html = (ROOT / "templates" / "components" / "pagination.html").read_text(encoding="utf-8")

        self.assertIn('data-pagination="true"', html)

    def test_critical_templates_opt_into_loading_feedback(self):
        expectations = {
            "templates/accounts/login.html": ('data-loading-text="{% if form.new_password_required or form.challenge_data %}',),
            "templates/accounts/user_form.html": ('data-loading-text="Guardando especialista…"',),
            "templates/accounts/user_list.html": ('data-loading-text="Filtrando usuarios…"',),
            "templates/reports/report_request_form.html": ('data-loading-text="Enviando solicitud…"',),
            "templates/reports/admin_report_list.html": ('data-loading-text="Generando PDF…"', 'data-loading-text="Rechazando solicitud…"', 'data-loading-text="Aplicando filtros…"'),
            "templates/reports/specialist_report_list.html": ('data-loading="true"', 'data-loading-text="Preparando descarga…"'),
            "templates/clinical_sessions/session_confirm.html": ('data-loading-text="Confirmando sesión…"',),
            "templates/clinical_sessions/session_detail.html": ('data-loading="true"', 'data-loading-text="Preparando descarga…"', 'data-loading-text="Enviando solicitud…"'),
            "templates/clinical_sessions/session_list.html": ('data-loading="true"', 'data-loading-text="Preparando descarga…"', 'data-loading-text="Enviando solicitud…"', 'data-loading-text="Filtrando sesiones…"'),
            "templates/clinical_sessions/unassociated_sessions.html": ('data-loading-text="Generando informe…"',),
            "templates/audit/log_list.html": ('data-loading="true"', 'data-loading-text="Exportando CSV…"', 'data-loading-text="Exportando PDF…"', 'data-loading-text="Aplicando filtros…"'),
            "templates/components/sidebar.html": ('data-loading="true"', 'data-loading-text="Cargando…"'),
        }
        for relative_path, markers in expectations.items():
            html = (ROOT / relative_path).read_text(encoding="utf-8")
            for marker in markers:
                self.assertIn(marker, html, f"{relative_path}: {marker}")
