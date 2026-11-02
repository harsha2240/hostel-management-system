from django import forms

from .models import Hostel, Room


class BedFilterForm(forms.Form):
    hostel = forms.IntegerField(required=False, min_value=1, max_value=2**63 - 1)
    # The configured MySQL backend stores room floors as unsigned SMALLINTs.
    floor = forms.IntegerField(required=False, min_value=0, max_value=65535)


class HostelForm(forms.ModelForm):
    class Meta:
        model = Hostel
        fields = ["name", "hostel_type", "is_active"]


class RoomForm(forms.ModelForm):
    class Meta:
        model = Room
        fields = [
            "hostel",
            "room_number",
            "floor",
            "room_type",
            "capacity",
            "fee_amount",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["fee_amount"].required = False

    def clean_fee_amount(self):
        fee = self.cleaned_data.get("fee_amount")
        return self.instance.fee_amount if fee is None else fee

    def clean(self):
        cleaned_data = super().clean()
        room = self.instance
        capacity = cleaned_data.get("capacity")

        if room.pk and capacity is not None:
            from allocations.models import Allocation

            active_bed_count = (
                room.beds.filter(allocations__status=Allocation.AllocationStatus.ACTIVE)
                .distinct()
                .count()
            )

            if active_bed_count > capacity:
                self.add_error(
                    "capacity",
                    f"This room has {active_bed_count} beds with active "
                    "allocations. Complete or move allocations before "
                    "reducing capacity further.",
                )

        return cleaned_data
