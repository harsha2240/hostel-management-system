from datetime import date, datetime

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from hostels.models import Bed

from .forms import DateField, ModelChoiceField


class DateFieldTests(SimpleTestCase):
    def test_dates_text_and_optional_empty_values_keep_standard_behavior(self):
        field = DateField(required=False)
        for value in ("2026-10-26", date(2026, 10, 26), datetime(2026, 10, 26, 12)):
            with self.subTest(value=value):
                self.assertEqual(field.clean(value), date(2026, 10, 26))
        self.assertIsNone(field.clean(None))
        self.assertIsNone(field.clean(""))

    def test_unexpected_json_types_produce_validation_errors(self):
        field = DateField(required=False)
        for value in (0, 123, 1.5, True, False, [], ["2026-10-26"], {}, {"day": 26}):
            with self.subTest(value=value), self.assertRaises(ValidationError) as error:
                field.clean(value)
            self.assertEqual(error.exception.code, "invalid")


class ModelChoiceFieldTests(SimpleTestCase):
    def test_non_integer_json_keys_are_rejected_without_a_query(self):
        field = ModelChoiceField(queryset=Bed.objects.none())
        for value in (True, False, 1.0, 1.5, float("inf"), float("nan"), [], {"pk": 1}):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError) as error:
                    field.clean(value)
                self.assertEqual(error.exception.code, "invalid_choice")
