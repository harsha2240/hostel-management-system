from django.contrib import admin

from .models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "user", "action", "record_type", "record_id")
    list_filter = ("action", "record_type")
    readonly_fields = ("timestamp", "user", "action", "record_type", "record_id")

    def has_module_permission(self, request):
        return request.user.is_superuser and request.user.role == "admin"

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
