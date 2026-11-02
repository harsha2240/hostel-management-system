import json

from django import forms
from django.test import SimpleTestCase

from .responses import form_error_response


class FormErrorResponseTests(SimpleTestCase):
    class ExampleForm(forms.Form):
        student = forms.ChoiceField(choices=[("1", "Student One")])
        mode = forms.ChoiceField(choices=[("Cash", "Cash")])

    def test_invalid_reference_preserves_field_errors_and_returns_not_found(self):
        form = self.ExampleForm({"student": "missing", "mode": "Cash"})

        response = form_error_response(form, missing_fields=("student", "bed"))

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            json.loads(response.content),
            {
                "error": {
                    "code": "NOT_FOUND",
                    "message": "Please correct the highlighted fields.",
                    "fields": form.errors.get_json_data(),
                }
            },
        )

    def test_other_invalid_choices_and_required_references_remain_bad_requests(self):
        for data in (
            {"student": "1", "mode": "Card"},
            {"mode": "Cash"},
        ):
            with self.subTest(data=data):
                response = form_error_response(
                    self.ExampleForm(data), missing_fields=("student",)
                )

                self.assertEqual(response.status_code, 400)
                self.assertEqual(
                    json.loads(response.content)["error"]["code"], "VALIDATION_ERROR"
                )

    def test_invalid_choices_require_an_explicit_reference_field_to_return_404(self):
        response = form_error_response(
            self.ExampleForm({"student": "missing", "mode": "Cash"})
        )

        self.assertEqual(response.status_code, 400)
