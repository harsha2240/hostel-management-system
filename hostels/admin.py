from django.contrib import admin

from audit.mixins import AuditedAdminMixin
from audit.models import AuditEvent
from audit.services import record_event

from .models import Bed, Hostel, Room


class RoomInline(admin.TabularInline):
    model = Room
    extra = 1
    can_delete = False


class BedInline(admin.TabularInline):
    model = Bed
    extra = 0
    readonly_fields = ("label",)
    can_delete = False


def save_audited_formset(request, formset):
    """Save inline records with audit events in the admin transaction."""
    instances = formset.save(commit=False)
    for obj in instances:
        action = (
            AuditEvent.Action.CREATE
            if obj._state.adding
            else AuditEvent.Action.UPDATE
        )
        obj.save()
        record_event(user=request.user, action=action, record=obj)
    formset.save_m2m()


@admin.register(Hostel)
class HostelAdmin(AuditedAdminMixin, admin.ModelAdmin):
    list_display = ("name", "hostel_type", "is_active")
    search_fields = ("name",)
    list_filter = ("hostel_type", "is_active")
    inlines = (RoomInline,)

    def save_formset(self, request, form, formset, change):
        save_audited_formset(request, formset)


@admin.register(Room)
class RoomAdmin(AuditedAdminMixin, admin.ModelAdmin):
    list_display = ("room_number", "hostel", "floor", "room_type", "capacity")
    list_filter = ("hostel", "floor", "room_type")
    search_fields = ("room_number", "hostel__name")
    inlines = (BedInline,)

    def save_formset(self, request, form, formset, change):
        save_audited_formset(request, formset)


@admin.register(Bed)
class BedAdmin(AuditedAdminMixin, admin.ModelAdmin):
    list_display = ("label", "room", "status")
    list_filter = ("status", "room__hostel")
    search_fields = ("label", "room__room_number", "room__hostel__name")
