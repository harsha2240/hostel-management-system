"""Small shared helpers for the rendered pages and documented JSON APIs."""

import json
from math import isfinite

from django.core.exceptions import ValidationError
from django.http import JsonResponse


def wants_json(request):
    return (
        request.content_type == "application/json"
        or "application/json" in request.headers.get("Accept", "")
    )


def _finite_json_number(value):
    number = float(value)
    if not isfinite(number):
        raise ValueError("JSON numbers must be finite.")
    return number


def request_data(request):
    if request.content_type == "application/json":
        try:
            data = json.loads(
                request.body,
                parse_float=_finite_json_number,
                parse_constant=_finite_json_number,
            )
            if not isinstance(data, dict):
                raise ValueError("JSON data must be an object.")
            # Documented JSON writes use the same scalar fields as HTML forms.
            for key, value in data.items():
                key.encode("utf-8")
                if isinstance(value, (dict, list)):
                    raise ValueError("JSON fields must contain scalar values.")
                if isinstance(value, str):
                    value.encode("utf-8")
        except (ValueError, RecursionError):
            raise ValidationError("Enter a valid JSON object.") from None
        return data
    return request.POST


def api_error(message, *, code="VALIDATION_ERROR", status=400, fields=None):
    error = {"code": code, "message": message}
    if fields:
        error["fields"] = fields
    return JsonResponse({"error": error}, status=status)
