from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.db import transaction

from audit.mixins import AuditedAdminMixin

from .models import User


@admin.register(User)
class HMSUserAdmin(AuditedAdminMixin, UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ('HMS access', {'fields': ('role', 'failed_attempts', 'locked_until')}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('HMS access', {'fields': ('role',)}),
    )
    readonly_fields = ('failed_attempts', 'locked_until')

    @transaction.atomic
    def user_change_password(self, request, id, form_url=''):
        return super().user_change_password(request, id, form_url)

    def has_module_permission(self, request):
        return request.user.is_superuser and request.user.role == User.Role.ADMIN

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_add_permission(self, request):
        return self.has_module_permission(request)

    def has_change_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_delete_permission(self, request, obj=None):
        return False  # Accounts are deactivated, never deleted.
