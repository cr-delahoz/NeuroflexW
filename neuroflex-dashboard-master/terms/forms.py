from django import forms

TERMS_CONTENT_FILE_EXTENSIONS = (".txt", ".md", ".html")
TERMS_CONTENT_FILE_MAX_BYTES = 1_048_576


class TermsVersionCreateForm(forms.Form):
    title = forms.CharField(label="Titulo", max_length=255)
    language = forms.ChoiceField(
        label="Idioma",
        choices=[("es", "Espanol"), ("en", "Ingles")],
        initial="es",
    )
    published = forms.BooleanField(
        label="Publicar inmediatamente (pasa a ser la version vigente)",
        required=False,
        initial=True,
    )
    content = forms.CharField(
        label="Contenido",
        required=False,
        widget=forms.Textarea(attrs={"rows": 10}),
        help_text="Pega el texto de los terminos o sube un archivo .txt, .md o .html.",
    )
    content_file = forms.FileField(
        label="Archivo de contenido",
        required=False,
        help_text="Formatos permitidos: .txt, .md, .html (maximo 1 MB).",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            existing_classes = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing_classes} nf-input".strip()

    def clean_content_file(self):
        content_file = self.cleaned_data.get("content_file")
        if not content_file:
            return None
        name = (content_file.name or "").lower()
        if not name.endswith(TERMS_CONTENT_FILE_EXTENSIONS):
            raise forms.ValidationError(
                "Formato no permitido. Usa un archivo .txt, .md o .html."
            )
        if content_file.size > TERMS_CONTENT_FILE_MAX_BYTES:
            raise forms.ValidationError("El archivo supera el maximo de 1 MB.")
        return content_file

    def clean(self):
        cleaned = super().clean()
        content = (cleaned.get("content") or "").strip()
        content_file = cleaned.get("content_file")

        if content_file:
            try:
                cleaned["content"] = content_file.read().decode("utf-8").strip()
            except UnicodeDecodeError:
                self.add_error(
                    "content_file", "El archivo debe estar codificado en UTF-8."
                )
                return cleaned
        elif content:
            cleaned["content"] = content

        if not cleaned.get("content"):
            self.add_error(
                None, "Ingresa el contenido de los terminos o sube un archivo."
            )
        return cleaned
