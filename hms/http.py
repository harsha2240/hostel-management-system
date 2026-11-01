"""Small shared helpers for the rendered pages and documented JSON APIs."""

import json

from django.core.exceptions import ValidationError
from django.http import JsonResponse


def wants_json(request):
    return (
        request.content_type == "application/json"
        or "application/json" in request.headers.get("Accept", "")
    )


def request_data(request):
    if request.content_type == "application/json":
        try:
            data = json.loads(request.body)
        except ValueError:
            raise ValidationError("Enter a valid JSON object.") from None
        if not isinstance(data, dict):
            raise ValidationError("Enter a valid JSON object.")
        return data
    return request.POST


def api_error(message, *, code="VALIDATION_ERROR", status=400, fields=None):
    error = {"code": code, "message": message}
    if fields:
        error["fields"] = fields
    return JsonResponse({"error": error}, status=status)
