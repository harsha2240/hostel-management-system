from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from accounts.decorators import roles_required
from accounts.models import User
from hms.http import wants_json

from .models import AuditEvent


@roles_required(User.Role.ADMIN)
@require_GET
def event_list(request):
    events = AuditEvent.objects.select_related("user")
    action = request.GET.get("action", "")
    if action in AuditEvent.Action.values:
        events = events.filter(action=action)
    page = Paginator(events, 25).get_page(request.GET.get("page"))
    if wants_json(request):
        return JsonResponse(
            {
                "results": [
                    {
                        "id": event.pk,
                        "user_id": event.user_id,
                        "action": event.action,
                        "record_type": event.record_type,
                        "record_id": event.record_id,
                        "timestamp": event.timestamp.isoformat(),
                    }
                    for event in page
                ],
                "page": page.number,
                "total": page.paginator.count,
            }
        )
    return render(
        request,
        "audit/event_list.html",
        {
            "page_obj": page,
            "actions": AuditEvent.Action.choices,
            "action": action,
        },
    )
