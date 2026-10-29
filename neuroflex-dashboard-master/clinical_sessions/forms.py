from django import forms


class SessionSearchForm(forms.Form):
    session_id = forms.CharField(
        required=False,
        label="Buscar por identificador",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            existing_classes = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing_classes} nf-input".strip()
            field.widget.attrs.setdefault("placeholder", "Ej. 1b7d4e29-...")


class DisplayCodeForm(forms.Form):
    display_code = forms.CharField(
        required=True,
        label="Codigo mostrado en las gafas VR",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            existing_classes = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing_classes} nf-input".strip()
            field.widget.attrs.setdefault("placeholder", "Ej. 123456")
