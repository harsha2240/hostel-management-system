from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from accounts.models import User
from audit.models import AuditEvent
from audit.services import record_event

from .forms import BedFilterForm, HostelForm, RoomForm
from .models import Bed, Hostel, Room


def can_manage_hostels(user):
    return user.is_authenticated and user.role == User.Role.ADMIN


@login_required
@require_http_methods(["GET", "POST"])
def hostel_list(request):
    if not can_manage_hostels(request.user):
        return HttpResponseForbidden("Only admins can manage hostels.")

    form = HostelForm(request.POST if request.method == "POST" else None)

    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            hostel = form.save()
            record_event(
                user=request.user,
                action=AuditEvent.Action.CREATE,
                record=hostel,
            )
        return redirect("hostel-list")

    hostels = Hostel.objects.all()
    return render(
        request,
        "hostels/hostel_list.html",
        {
            "hostels": hostels,
            "form": form,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def hostel_update(request, pk):
    if not can_manage_hostels(request.user):
        return HttpResponseForbidden("Only admins can manage hostels.")

    hostel = get_object_or_404(Hostel, pk=pk)
    form = HostelForm(
        request.POST if request.method == "POST" else None, instance=hostel
    )

    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            # ModelForm validation mutates its instance before save(), so read
            # the persisted value to classify deactivation reliably.
            was_active = Hostel.objects.values_list("is_active", flat=True).get(
                pk=hostel.pk
            )
            hostel = form.save()
            action = (
                AuditEvent.Action.DEACTIVATE
                if was_active and not hostel.is_active
                else AuditEvent.Action.UPDATE
            )
            record_event(user=request.user, action=action, record=hostel)
        return redirect("hostel-list")

    return render(
        request,
        "hostels/hostel_form.html",
        {
            "form": form,
            "heading": "Edit Hostel",
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def room_create(request):
    if not can_manage_hostels(request.user):
        return HttpResponseForbidden("Only admins can manage rooms.")

    form = RoomForm(request.POST if request.method == "POST" else None)

    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            room = form.save()
            record_event(
                user=request.user,
                action=AuditEvent.Action.CREATE,
                record=room,
            )
        return redirect("bed-list")

    return render(
        request,
        "hostels/room_form.html",
        {
            "form": form,
            "heading": "Add Room",
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def room_update(request, pk):
    if not can_manage_hostels(request.user):
        return HttpResponseForbidden("Only admins can manage rooms.")

    room = get_object_or_404(Room, pk=pk)
    form = RoomForm(request.POST if request.method == "POST" else None, instance=room)

    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            room = form.save()
            record_event(
                user=request.user,
                action=AuditEvent.Action.UPDATE,
                record=room,
            )
        return redirect("bed-list")

    return render(
        request,
        "hostels/room_form.html",
        {
            "form": form,
            "heading": "Edit Room",
        },
    )


@login_required
def bed_list(request):
    beds = Bed.objects.select_related("room__hostel")
    filter_form = BedFilterForm(request.GET)
    valid_filters = filter_form.is_valid()

    hostel_id = request.GET.get("hostel")
    floor = request.GET.get("floor")
    room_type = request.GET.get("room_type")
    status = request.GET.get("status", Bed.BedStatus.AVAILABLE)

    if valid_filters:
        cleaned_hostel = filter_form.cleaned_data["hostel"]
        cleaned_floor = filter_form.cleaned_data["floor"]
        if cleaned_hostel is not None:
            beds = beds.filter(room__hostel_id=cleaned_hostel)
        if cleaned_floor is not None:
            beds = beds.filter(room__floor=cleaned_floor)
        if room_type:
            beds = beds.filter(room__room_type=room_type)
        if status:
            beds = beds.filter(status=status)
    else:
        beds = beds.none()

    page_obj = Paginator(beds, 50).get_page(request.GET.get("page"))

    return render(
        request,
        "hostels/bed_list.html",
        {
            "beds": page_obj.object_list,
            "filter_form": filter_form,
            "page_obj": page_obj,
            "hostels": Hostel.objects.filter(is_active=True),
            "room_types": Room.RoomType.choices,
            "statuses": Bed.BedStatus.choices,
            "selected_hostel": hostel_id or "",
            "selected_floor": floor or "",
            "selected_room_type": room_type or "",
            "selected_status": status,
        },
        status=200 if valid_filters else 400,
    )
