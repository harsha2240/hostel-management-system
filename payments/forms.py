from decimal import Decimal

from django import forms
from django.utils import timezone

from hms.forms import DateField, ModelChoiceField
from students.models import Student

from .models import Payment


class PaymentForm(forms.Form):
    student = ModelChoiceField(queryset=Student.objects.all())
    amount = forms.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal("0.01"), label="Amount (INR)"
    )
    date = DateField(
        initial=timezone.localdate, widget=forms.DateInput(attrs={"type": "date"})
    )
    mode = forms.ChoiceField(choices=Payment.Mode.choices)
    reference = forms.RegexField(
        r"^[A-Za-z0-9]*$", max_length=30, required=False, label="Reference number"
    )


class AdjustmentForm(PaymentForm):
    amount = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        label="Adjustment (INR)",
        help_text="Use a negative amount to reverse a payment, or a positive amount to add to it.",
    )
    adjustment_reason = forms.CharField(
        max_length=200, widget=forms.Textarea(attrs={"rows": 3})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        del self.fields["student"]
