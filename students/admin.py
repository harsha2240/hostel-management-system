from django.contrib import admin

from audit.mixins import AuditedAdminMixin

from .models import Student


@admin.register(Student)
class StudentAdmin(AuditedAdminMixin, admin.ModelAdmin):
    list_display = ("student_id", "name", "course", "year", "mobile", "status")
    search_fields = ("student_id", "name", "email", "course", "mobile")
    list_filter = ("status", "gender", "course", "year")
    ordering = ("name",)
