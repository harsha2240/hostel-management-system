from .http import api_error


def form_error_response(form, *, missing_fields=()):
    """Map invalid references to 404 without treating other choices as missing."""
    errors = form.errors.as_data()
    missing = any(
        error.code == "invalid_choice"
        for field in missing_fields
        for error in errors.get(field, [])
    )
    return api_error(
        "Please correct the highlighted fields.",
        fields=form.errors.get_json_data(),
        code="NOT_FOUND" if missing else "VALIDATION_ERROR",
        status=404 if missing else 400,
    )


def validation_response(error):
    code = getattr(error, "code", None) or "VALIDATION_ERROR"
    if code == "NOT_FOUND":
        status = 404
    elif code in {
        "BED_OCCUPIED",
        "ALREADY_ALLOCATED",
        "ALREADY_RELEASED",
        "HAS_ACTIVE_ALLOCATION",
    }:
        status = 409
    elif code in {
        "GENDER_MISMATCH",
        "IMMUTABLE_FIELD",
        "INACTIVE_STUDENT",
        "INACTIVE_HOSTEL",
    }:
        status = 422
    else:
        status = 400
    return api_error("; ".join(error.messages), code=code, status=status)
