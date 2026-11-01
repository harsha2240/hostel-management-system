from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponseForbidden

from audit.models import AuditEvent
from audit.services import record_event
from hms.http import api_error, wants_json


def roles_required(*roles):
    def decorate(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                if wants_json(request):
                    return api_error(
                        "Sign in to continue.",
                        code="AUTH_REQUIRED",
                        status=401,
                    )
                return redirect_to_login(request.get_full_path())
            if request.user.role not in roles:
                record_event(
                    user=request.user,
                    action=AuditEvent.Action.ACCESS_DENIED,
                    record_type="view",
                    record_id=view.__name__,
                )
                if wants_json(request):
                    return api_error(
                        "Access denied",
                        code="ACCESS_DENIED",
                        status=403,
                    )
                return HttpResponseForbidden("Access denied")
            return view(request, *args, **kwargs)

        return wrapped

    return decorate
