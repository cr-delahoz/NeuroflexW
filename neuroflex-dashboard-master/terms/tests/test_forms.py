from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase

from terms.forms import TERMS_CONTENT_FILE_MAX_BYTES, TermsVersionCreateForm


def _data(**overrides):
    data = {
        "title": "Terminos y condiciones NeuroFlex",
        "language": "es",
        "published": "on",
        "content": "1. Uso del sistema...\n2. Responsabilidades...",
    }
    data.update(overrides)
    return data


class TermsVersionCreateFormTests(SimpleTestCase):
    def test_valid_with_pasted_text(self):
        form = TermsVersionCreateForm(data=_data())

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["content"], "1. Uso del sistema...\n2. Responsabilidades...")
        self.assertEqual(form.cleaned_data["language"], "es")
        self.assertTrue(form.cleaned_data["published"])

    def test_empty_content_and_no_file_is_invalid(self):
        form = TermsVersionCreateForm(data=_data(content=""))

        self.assertFalse(form.is_valid())
        self.assertIn(
            "Ingresa el contenido de los terminos o sube un archivo.",
            form.non_field_errors(),
        )

    def test_file_upload_becomes_content(self):
        upload = SimpleUploadedFile("terminos.md", "Terminos desde archivo".encode("utf-8"))
        form = TermsVersionCreateForm(data=_data(content=""), files={"content_file": upload})

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["content"], "Terminos desde archivo")

    def test_unsupported_file_extension_is_rejected(self):
        upload = SimpleUploadedFile("terminos.pdf", b"binary")
        form = TermsVersionCreateForm(data=_data(content=""), files={"content_file": upload})

        self.assertFalse(form.is_valid())
        self.assertIn("content_file", form.errors)

    def test_non_utf8_file_is_rejected(self):
        upload = SimpleUploadedFile("terminos.txt", b"\xff\xfe\x01\x02")
        form = TermsVersionCreateForm(data=_data(content=""), files={"content_file": upload})

        self.assertFalse(form.is_valid())
        self.assertIn("content_file", form.errors)

    def test_title_is_required(self):
        form = TermsVersionCreateForm(data=_data(title=""))

        self.assertFalse(form.is_valid())
        self.assertIn("title", form.errors)

    def test_file_larger_than_1mb_is_rejected(self):
        big = SimpleUploadedFile("terminos.txt", b"a" * (TERMS_CONTENT_FILE_MAX_BYTES + 1))
        form = TermsVersionCreateForm(data=_data(content=""), files={"content_file": big})

        self.assertFalse(form.is_valid())
        self.assertIn("content_file", form.errors)
        self.assertIn("1 MB", form.errors["content_file"][0])

    def test_file_wins_over_pasted_text(self):
        upload = SimpleUploadedFile("terminos.html", "Contenido del archivo".encode("utf-8"))
        form = TermsVersionCreateForm(
            data=_data(content="Texto pegado que debe ignorarse"),
            files={"content_file": upload},
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["content"], "Contenido del archivo")
