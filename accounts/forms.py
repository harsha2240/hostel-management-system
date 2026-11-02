from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .models import User


class AccountCreationForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput, strip=False)

    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "email", "role")

    def _post_clean(self):
        super()._post_clean()
        password = self.cleaned_data.get("password")
        if not password:
            return
        try:
            validate_password(password, self.instance)
        except ValidationError as error:
            self.add_error("password", error)

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
        return user


class AccountUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("first_name", "last_name", "email", "role")

    def clean_role(self):
        role = self.cleaned_data["role"]
        if self.instance.is_superuser and role != User.Role.ADMIN:
            raise ValidationError("A superuser must retain the Admin role.")
        return role


class ProfileSettingsForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("first_name", "last_name", "email")
        labels = {
            "first_name": "First name",
            "last_name": "Last name",
            "email": "Email address",
        }
