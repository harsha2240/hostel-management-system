from django import forms
from django.utils import timezone

from hms.forms import DateField, ModelChoiceField
from hostels.models import Bed
from students.models import Student


class AllocationForm(forms.Form):
    student = ModelChoiceField(queryset=Student.objects.all())
    bed = ModelChoiceField(queryset=Bed.objects.select_related("room__hostel"))
    allocated_on = DateField(
        required=False,
        initial=timezone.localdate,
        widget=forms.DateInput(attrs={"type": "date"}),
    )


class TransferForm(forms.Form):
    new_bed = ModelChoiceField(queryset=Bed.objects.select_related("room__hostel"))


class ReleaseForm(forms.Form):
    vacate_date = DateField(
        initial=timezone.localdate, widget=forms.DateInput(attrs={"type": "date"})
    )
