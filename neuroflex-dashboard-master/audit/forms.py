from django import forms
from django.contrib.auth import get_user_model

from .models import AuditLog


User = get_user_model()


class AuditLogFilterForm(forms.Form):
    start_date = forms.DateField(
        required=False,
        label="Desde",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    end_date = forms.DateField(
        required=False,
        label="Hasta",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    actor = forms.ModelChoiceField(
        queryset=User.objects.none(),
        required=False,
        label="Usuario",
    )
    action = forms.CharField(required=False, label="Accion")
    result = forms.ChoiceField(
        required=False,
        label="Resultado",
        choices=[("", "Todos"), *AuditLog.Result.choices],
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["actor"].queryset = User.objects.order_by("username")
        for field in self.fields.values():
            existing_classes = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing_classes} nf-input".strip()
