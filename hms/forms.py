"""Form fields shared by the HTML and JSON entry points."""

from datetime import date

from django import forms
from django.core.exceptions import ValidationError


class DateField(forms.DateField):
    """Reject JSON values that Django's text/date parser cannot handle."""

    def to_python(self, value):
        if value is not None and not isinstance(value, (str, date)):
            raise ValidationError(self.error_messages["invalid"], code="invalid")
        return super().to_python(value)


class ModelChoiceField(forms.ModelChoiceField):
    """Require integer keys instead of truncating JSON numbers or booleans."""

    def to_python(self, value):
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (str, int, self.queryset.model))
        ):
            raise ValidationError(
                self.error_messages["invalid_choice"],
                code="invalid_choice",
                params={"value": value},
            )
        return super().to_python(value)
