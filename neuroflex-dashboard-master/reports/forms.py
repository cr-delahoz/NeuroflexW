from django import forms

from .models import ReportRequest


class ReportRequestForm(forms.ModelForm):
    class Meta:
        model = ReportRequest
        fields = ["session_id", "specialist_observation"]
        labels = {
            "session_id": "ID de sesion",
            "specialist_observation": "Observacion opcional del especialista",
        }
        widgets = {
            "specialist_observation": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            existing_classes = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing_classes} nf-input".strip()


class ReportReviewForm(forms.Form):
    rejection_reason = forms.CharField(
        required=False,
        widget=forms.Textarea,
        label="Motivo del rechazo",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            existing_classes = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing_classes} nf-input".strip()

    def clean_rejection_reason(self):
        return self.cleaned_data["rejection_reason"].strip()


class ReportAdminFilterForm(forms.Form):
    status = forms.ChoiceField(
        required=False,
        label="Estado",
        choices=[("", "Todos"), *ReportRequest.Status.choices],
    )
    specialist = forms.ModelChoiceField(
        queryset=None,
        required=False,
        label="Especialista",
    )
    requested_at = forms.DateField(
        required=False,
        label="Fecha de solicitud",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    session_id = forms.CharField(required=False, label="ID de sesion")

    def __init__(self, *args, **kwargs):
        specialist_queryset = kwargs.pop("specialist_queryset")
        super().__init__(*args, **kwargs)
        self.fields["specialist"].queryset = specialist_queryset
        for field in self.fields.values():
            existing_classes = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing_classes} nf-input".strip()
