"""Malformed API bodies must remain validation errors before ORM conversion."""

from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from .http import request_data


class RequestDataTests(SimpleTestCase):
    def parse(self, body):
        return request_data(SimpleNamespace(content_type="application/json", body=body))

    def test_json_object_preserves_finite_scalar_values(self):
        data = self.parse(
            b'{"student_id":"TEST123","bed_id":12,"amount":1.25,'
            b'"enabled":true,"empty":null}'
        )
        self.assertEqual(
            data,
            {
                "student_id": "TEST123",
                "bed_id": 12,
                "amount": 1.25,
                "enabled": True,
                "empty": None,
            },
        )
        self.assertIsInstance(data["bed_id"], int)
        self.assertIsInstance(data["amount"], float)

    def test_form_encoded_data_is_returned_unchanged(self):
        submitted = object()
        self.assertIs(
            request_data(
                SimpleNamespace(
                    content_type="application/x-www-form-urlencoded", POST=submitted
                )
            ),
            submitted,
        )

    def test_malformed_json_and_invalid_utf8_raise_validation_error(self):
        for body in (b"{", b'{"value":}', b"\xff", b'{"value":"\xff"}'):
            with (
                self.subTest(body=body),
                self.assertRaisesMessage(ValidationError, "Enter a valid JSON object."),
            ):
                self.parse(body)

    def test_non_object_json_raises_validation_error(self):
        for body in (b"[]", b"123", b"null", b'"text"', b"true"):
            with (
                self.subTest(body=body),
                self.assertRaisesMessage(ValidationError, "Enter a valid JSON object."),
            ):
                self.parse(body)

    def test_container_field_values_raise_validation_error(self):
        for body in (b'{"bed_id":[]}', b'{"bed_id":{}}', b'{"mode":["cash"]}'):
            with (
                self.subTest(body=body),
                self.assertRaisesMessage(ValidationError, "Enter a valid JSON object."),
            ):
                self.parse(body)

    def test_valid_unicode_strings_and_surrogate_pairs_are_preserved(self):
        self.assertEqual(
            self.parse(
                b'{"\\u0928\\u093e\\u092e":"\\u0928\\u092e\\u0938\\u094d\\u0924\\u0947",'
                b'"symbol":"\\ud83d\\ude00"}'
            ),
            {"नाम": "नमस्ते", "symbol": "😀"},
        )

    def test_unpaired_unicode_surrogates_raise_validation_error(self):
        for body in (
            b'{"student_id":"\\ud800"}',
            b'{"student_id":"\\udfff"}',
            b'{"\\ud800":"value"}',
            b'{"\\udfff":"value"}',
            b'{"student_id":"\\ud800text"}',
        ):
            with (
                self.subTest(body=body),
                self.assertRaisesMessage(ValidationError, "Enter a valid JSON object."),
            ):
                self.parse(body)

    def test_nonfinite_numbers_are_rejected_including_exponent_overflow(self):
        for number in ("NaN", "Infinity", "-Infinity", "1e999", "-1e999"):
            for shape in ('{{"bed_id":{}}}', '{{"nested":[{{"value":{}}}]}}'):
                with (
                    self.subTest(number=number, shape=shape),
                    self.assertRaisesMessage(
                        ValidationError, "Enter a valid JSON object."
                    ),
                ):
                    self.parse(shape.format(number).encode())

    def test_parser_recursion_error_becomes_validation_error(self):
        # Parser depth limits vary between Python versions and platform stacks.
        with patch("hms.http.json.loads", side_effect=RecursionError):
            with self.assertRaisesMessage(
                ValidationError, "Enter a valid JSON object."
            ):
                self.parse(b'{"nested":[]}')

    def test_deeply_nested_input_raises_validation_error(self):
        for depth in (1_500, 20_000):
            body = ('{"bed_id":' + "[" * depth + "0" + "]" * depth + "}").encode()
            with (
                self.subTest(depth=depth),
                self.assertRaisesMessage(ValidationError, "Enter a valid JSON object."),
            ):
                self.parse(body)
