from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class AuditQuerySet(models.QuerySet):
    def bulk_create(
        self,
        objs,
        batch_size=None,
        ignore_conflicts=False,
        update_conflicts=False,
        update_fields=None,
        unique_fields=None,
    ):
        if update_conflicts:
            raise ValidationError("Audit entries cannot be changed.")
        return super().bulk_create(
            objs,
            batch_size=batch_size,
            ignore_conflicts=ignore_conflicts,
            update_conflicts=update_conflicts,
            update_fields=update_fields,
            unique_fields=unique_fields,
        )

    def update(self, **kwargs):
        raise ValidationError("Audit entries cannot be changed.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Audit entries cannot be changed.")

    def delete(self):
        raise ValidationError("Use purge_audit_logs to enforce one-year retention.")

    def purge_before(self, cutoff):
        # 366 days also covers a calendar year containing leap day.
        if cutoff > timezone.now() - timedelta(days=366):
            raise ValidationError("Audit logs must be retained for at least one year.")
        return models.QuerySet.delete(self.filter(timestamp__lt=cutoff))


class AuditEvent(models.Model):
    class Action(models.TextChoices):
        LOGIN = "login", "Login"
        LOGIN_FAILED = "login_failed", "Failed login"
        LOGOUT = "logout", "Logout"
        CREATE = "create", "Create"
        UPDATE = "update", "Update"
        DEACTIVATE = "deactivate", "Deactivate"
        ALLOCATE = "allocate", "Allocate"
        TRANSFER = "transfer", "Transfer"
        RELEASE = "release", "Release"
        PAYMENT = "payment", "Payment"
        ACCESS_DENIED = "access_denied", "Access denied"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    action = models.CharField(max_length=20, choices=Action.choices)
    record_type = models.CharField(max_length=100)
    record_id = models.CharField(max_length=64, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = AuditQuerySet.as_manager()

    class Meta:
        ordering = ["-timestamp", "-pk"]

    def save(self, *args, **kwargs):
        if (
            not self._state.adding
            or kwargs.get("force_update")
            or kwargs.get("update_fields")
        ):
            raise ValidationError("Audit entries cannot be changed.")
        # Never let a new Python object overwrite an existing event by its PK.
        kwargs["force_insert"] = True
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Use purge_audit_logs to enforce one-year retention.")

    def __str__(self):
        return f"{self.get_action_display()}: {self.record_type} {self.record_id}"
