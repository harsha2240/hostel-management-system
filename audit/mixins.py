from .models import AuditEvent
from .services import record_event


class AuditedAdminMixin:
    """Include changes made through Django admin in the application audit log."""

    def save_model(self, request, obj, form, change):
        action = AuditEvent.Action.UPDATE if change else AuditEvent.Action.CREATE
        if change:
            previous = type(obj).objects.get(pk=obj.pk)
            was_active = getattr(previous, "is_active", None) is True
            is_active = getattr(obj, "is_active", None) is True
            was_status_active = getattr(previous, "status", None) == "Active"
            status_inactive = getattr(obj, "status", None) == "Inactive"
            if (was_active and not is_active) or (
                was_status_active and status_inactive
            ):
                action = AuditEvent.Action.DEACTIVATE
        obj._audit_action = action
        super().save_model(request, obj, form, change)

    def has_delete_permission(self, request, obj=None):
        # The audit schema intentionally has no delete action. Preserve records
        # so that destructive, unaudited removal cannot bypass the event log.
        return False

    def log_addition(self, request, obj, message):
        super().log_addition(request, obj, message)
        record_event(user=request.user, action=AuditEvent.Action.CREATE, record=obj)

    def log_change(self, request, obj, message):
        super().log_change(request, obj, message)
        record_event(
            user=request.user,
            action=getattr(obj, "_audit_action", AuditEvent.Action.UPDATE),
            record=obj,
        )
