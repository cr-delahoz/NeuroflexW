from django.template import Context, Template
from django.test import SimpleTestCase


class UpdateModalTemplateTest(SimpleTestCase):
    def test_modal_renders_progress_bar_and_status(self):
        template = Template(
            '{% load static %}'
            '{% include "updater/update_modal.html" %}'
        )
        rendered = template.render(Context({}))

        self.assertIn('id="nf-update-progress-bar"', rendered)
        self.assertIn('max="100"', rendered)
        self.assertIn('id="nf-update-status"', rendered)
        self.assertIn('aria-live="polite"', rendered)
        self.assertIn('id="nf-update-progress"', rendered)

    def test_progress_section_is_hidden_by_default(self):
        template = Template(
            '{% load static %}'
            '{% include "updater/update_modal.html" %}'
        )
        rendered = template.render(Context({}))

        self.assertIn(
            'id="nf-update-progress" class="hidden mb-4"',
            rendered,
        )
